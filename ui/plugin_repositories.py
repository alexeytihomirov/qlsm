"""External repositories: fetch a manifest over plain HTTP from an
operator-supplied repo URL, and install its contents locally -- individual
plugin files into the operator tier of the local pool
(data/shared-plugins/<runtime>/, see ui/plugin_pool.py), and addon packages
(.zip) into ADDON_PACKAGES_DIR via the same installer the zip-upload path
uses.

This is deliberately separate from `.ql-plugin.json` (plugin_manifest.py,
per-plugin display/edit metadata for a file already in the pool) and from
`qlsm-addon.json` (ui/addons/manifest.py, the manifest *inside* an addon
package) -- a repository is just a remote source list.

Two manifest filenames, tried in this order:

    qlsm-repository.json  -- current format, plugins and/or addons:
        {"plugins": [...same entries as below...],
         "addons": [
            {"id": "my-addon", "version": "1.2.0", "zip": "my-addon.zip",
             "sha256": "<hex of the zip>", "label": "...",
             "description": "...", "requires_qlsm_version": "1.30.0"},
            ...
         ]}
    qlsm-plugins.json     -- original plugins-only format, kept working:
        {"plugins": [
            {"filename": "some_plugin.py", "label": "...",
             "description": "...", "version": "...",
             "sha256": "<hex of the LF-normalized .py>",
             "runtime": "minqlx" | "minqlxtended" | "minqlxtended-patched",
             "requires_qlsm_version": "1.30.0",
             "depends_on": ["some_helper.py"],
             "cvars": [...], "commands": [...]},
        ]}

All fields but `filename` / `id`+`zip` are optional. `filename` must be a
bare, root-level, importable module name ending in .py -- same constraint the
pool itself enforces (see plugin_manifest.py / pluginSelection.js
isEnableablePluginPath). `requires_qlsm_version` is the author's own claim,
compared against this qlsm's own VERSION file by version_risk() below -- see
that function's docstring for what "risk" does and does not mean here
(operator decision, 2026-09-14).
`cvars`/`commands`/`depends_on` use the `.ql-plugin.json` shape; on download
they (with label/description) become the plugin's pool sidecar unless the repo
also ships a separate `<plugin>.ql-plugin.json`, which wins.

`depends_on` names other entries in this same manifest that the plugin needs
on disk but that are not loadable plugins themselves (a shared helper module
-- e.g. chat_rcon.py needs chat_rcon_acl.py). A named entry gets no row of its
own in the UI and is downloaded automatically together with whatever depends
on it (see dependency_filenames / expand_with_dependencies below) -- the
repository list offers plugins, not the files they happen to be made of. It
also lands in the downloaded sidecar, which is what makes the Plugins tab
hide the same helper from its own checkbox list (pluginSelection.js).

A declared `sha256` is what update detection runs on (plugin_update_status /
addon_update_status): no hash in the manifest means qlsm cannot tell whether
the repo's copy changed without downloading it, so the entry reports status
"unknown". A plugin entry's hash is of the LF-normalized source (matching
the CRLF-insensitive comparison download_plugin() already does); an addon
entry's hash is of the .zip exactly as served.
"""
import hashlib
import json
import logging
import os
import re

import requests

from ui.addons.install import (
    AddonInstallError,
    MAX_ARCHIVE_BYTES,
    install_addon_zip,
    read_manifest_from_blob,
)
from ui.addons.manifest import (
    ADDON_ID_MAX,
    ADDON_ID_RE,
    MANIFEST_FILENAME as ADDON_MANIFEST_FILENAME,
    read_manifest as read_addon_manifest,
)
from ui.plugin_manifest import PLUGIN_MANIFEST_MAX_SIZE
from ui.plugin_pool import operator_pool_dir, resolve_pool_file
from ui.runtime import is_valid_runtime, normalize_runtime

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = 'qlsm-plugins.json'           # legacy, plugins only
REPO_MANIFEST_FILENAME = 'qlsm-repository.json'   # current, plugins + addons
MANIFEST_MAX_SIZE = 256 * 1024
PLUGIN_FILE_MAX_SIZE = 512 * 1024
FETCH_TIMEOUT_SECONDS = 10

_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')

# A plugin file is a Python module loaded by bare name -- no dots, no path
# separators, nothing but what a valid module name and this pool allow.
_FILENAME_RE = re.compile(r'^[A-Za-z0-9_\-]+\.py$')


def is_safe_plugin_filename(filename):
    """A bare `<name>.py` -- no path separators, no dots besides the
    extension. Anything else never reaches a pool path."""
    return isinstance(filename, str) and bool(_FILENAME_RE.match(filename))

# The part of a repo manifest entry that becomes the plugin's pool sidecar
# (<plugin>.ql-plugin.json). Everything else on an entry (filename, runtime,
# requires_qlsm_version) only matters for listing/downloading.
_SIDECAR_FIELDS = ('label', 'description', 'cvars', 'commands', 'depends_on')
_INLINE_LIST_FIELDS = ('cvars', 'commands')


class PluginRepositoryError(Exception):
    """Any fetch/parse/download failure. The message is written to be shown
    to the operator verbatim -- it never carries raw exception internals.
    `code` is set only for failures the caller (the route, then the UI) needs
    to branch on rather than just display -- currently just 'exists', so a
    download-blocked-by-an-existing-file can offer an overwrite confirmation
    instead of a dead-end error."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def _fetch(url, max_size):
    try:
        response = requests.get(url, timeout=FETCH_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise PluginRepositoryError(f"Could not reach {url}: {e}") from e
    if response.status_code != 200:
        raise PluginRepositoryError(f"{url} returned HTTP {response.status_code}")
    content = response.content
    if len(content) > max_size:
        raise PluginRepositoryError(f"{url} is larger than the {max_size} byte limit")
    return content


def _normalize_eol(data):
    """CRLF/CR -> LF, so two copies of a plugin that differ only in line
    endings compare equal (CodeMirror shows them as identical too)."""
    return data.replace(b'\r\n', b'\n').replace(b'\r', b'\n')


def fetch_plugin_source(base_url, filename):
    """The raw bytes of <base_url>/<filename>, under the plugin size cap.
    Shared by download and diff so both read exactly the same URL."""
    return _fetch(base_url.rstrip('/') + '/' + filename, PLUGIN_FILE_MAX_SIZE)


# GitHub's repository page serves HTML, not files, so a pasted repo URL has to
# become a raw.githubusercontent.com base before anything can be fetched from
# it. The branch is rarely in the URL, so both common defaults are tried in
# turn (cheaper and more reliable than the rate-limited GitHub API).
GITHUB_BRANCH_CANDIDATES = ('main', 'master')
_GITHUB_REPO_RE = re.compile(
    r'^https?://(?:www\.)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?'
    r'(?:/tree/(?P<branch>[^/]+)(?P<subdir>/.*)?)?/?$'
)
_GITHUB_RAW_BASE = 'https://raw.githubusercontent.com'


def github_raw_bases(url):
    """Raw base URLs to try for a github.com repository URL, best first.

    Returns [] for anything else (including a raw URL already), which the
    caller treats as "use this URL as given". A URL naming its own branch
    (/tree/<branch>, optionally with a subfolder) yields exactly one
    candidate; otherwise one per GITHUB_BRANCH_CANDIDATES.
    """
    match = _GITHUB_REPO_RE.match((url or '').strip())
    if not match:
        return []
    owner, repo = match.group('owner'), match.group('repo')
    subdir = (match.group('subdir') or '').strip('/')
    tail = f'/{subdir}' if subdir else ''
    branches = [match.group('branch')] if match.group('branch') else list(GITHUB_BRANCH_CANDIDATES)
    return [f'{_GITHUB_RAW_BASE}/{owner}/{repo}/{branch}{tail}/' for branch in branches]


def resolve_manifest_source(url, fetch=None):
    """(fetch_url, manifest) for a repository URL the operator typed.

    A github.com URL is rewritten to its raw form and each branch candidate
    tried until one serves a manifest; every other URL is fetched as given.
    Raises PluginRepositoryError when nothing works -- naming the branches
    tried, since "not valid JSON" would not tell the operator what to fix.
    `fetch` is the manifest fetcher to use, so the caller can pass the name
    its own module exports (which is what tests patch).
    """
    fetch = fetch or fetch_manifest
    candidates = github_raw_bases(url)
    if not candidates:
        return url, fetch(url)

    last_error = None
    for candidate in candidates:
        try:
            return candidate, fetch(candidate)
        except PluginRepositoryError as e:
            last_error = e
    if len(candidates) > 1:
        raise PluginRepositoryError(
            f"No {REPO_MANIFEST_FILENAME} or {MANIFEST_FILENAME} found in that repository on "
            f"{' or '.join(GITHUB_BRANCH_CANDIDATES)}."
        )
    raise last_error


def _manifest_url(base_url, filename=MANIFEST_FILENAME):
    return base_url.rstrip('/') + '/' + filename


def _optional_str(entry, key):
    value = entry.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _optional_sha256(entry):
    value = entry.get('sha256')
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if _SHA256_RE.match(value) else None


def _optional_filename_list(entry, key):
    """A list of bare plugin filenames, or []. Same filename constraint as an
    entry's own `filename`: anything else is dropped rather than failing the
    manifest, matching the "one bad field never breaks the fetch" rule."""
    value = entry.get(key)
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if is_safe_plugin_filename(name) and name not in out:
            out.append(name)
    return out


def _zip_path(entry):
    """The addon entry's `zip` as a safe relative path, or None. Same
    reject-don't-sanitize stance as addons/install.py's _safe_member_path."""
    value = entry.get('zip')
    if not isinstance(value, str) or not value.strip():
        return None
    path = value.strip().replace('\\', '/')
    if path.startswith('/') or not path.lower().endswith('.zip'):
        return None
    parts = [p for p in path.split('/') if p]
    if any(p in ('.', '..') or ':' in p for p in parts):
        return None
    return '/'.join(parts)


def _normalize_plugins(entries):
    plugins = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        filename = entry.get('filename')
        if not isinstance(filename, str) or not _FILENAME_RE.match(filename):
            continue
        plugin = {
            'filename': filename,
            'label': _optional_str(entry, 'label'),
            'description': _optional_str(entry, 'description'),
            'runtime': entry.get('runtime') if is_valid_runtime(entry.get('runtime')) else None,
            'version': _optional_str(entry, 'version'),
            'sha256': _optional_sha256(entry),
            'requires_qlsm_version': _optional_str(entry, 'requires_qlsm_version'),
            'depends_on': _optional_filename_list(entry, 'depends_on'),
        }
        # Inline sidecar metadata: kept only when well-formed, and only added
        # when present so plain entries keep their existing shape.
        for field in _INLINE_LIST_FIELDS:
            if isinstance(entry.get(field), list):
                plugin[field] = entry[field]
        plugins.append(plugin)
    return plugins


def dependency_filenames(plugins):
    """Filenames some *other* entry in the same manifest declares in its
    `depends_on` -- the helper modules that get no row of their own.

    Only names that are themselves entries count: a `depends_on` pointing at
    something this repository does not publish cannot be downloaded, and
    hiding a row that does not exist would be a no-op anyway. A self-reference
    is ignored so a malformed entry cannot hide itself.
    """
    known = {e['filename'] for e in plugins}
    deps = set()
    for entry in plugins:
        for name in entry.get('depends_on') or []:
            if name in known and name != entry['filename']:
                deps.add(name)
    return deps


def expand_with_dependencies(plugins, selected):
    """`selected` filenames plus every dependency they need, transitively.

    Returns (ordered, pulled_by). `ordered` puts dependencies before the
    entries that need them, so a batch that fails partway never leaves a
    plugin in the pool whose helper is missing. `pulled_by` maps each
    auto-added helper to the entry that declared it -- the caller needs that
    both for the operator-facing message and to give a helper with no runtime
    of its own the runtime of whatever dragged it in. Only dependencies this
    manifest actually publishes are followed (see dependency_filenames); a
    cycle terminates rather than recursing forever. Names not in the manifest
    at all are kept in place -- the route still has to report them, and
    dropping them here would hide the reason.
    """
    by_name = {e['filename']: e for e in plugins}
    ordered, pulled_by, visiting = [], {}, set()

    def visit(name):
        if name in ordered or name in visiting:
            return
        visiting.add(name)
        for dep in (by_name.get(name) or {}).get('depends_on') or []:
            if dep in by_name and dep != name:
                pulled_by.setdefault(dep, name)
                visit(dep)
        visiting.discard(name)
        ordered.append(name)

    for name in selected:
        visit(name)
    for name in selected:
        pulled_by.pop(name, None)
    return ordered, pulled_by


def _normalize_addons(entries):
    addons = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        addon_id = entry.get('id')
        if (not isinstance(addon_id, str) or len(addon_id) > ADDON_ID_MAX
                or not ADDON_ID_RE.match(addon_id)):
            continue
        zip_path = _zip_path(entry)
        if zip_path is None:
            continue
        addons.append({
            'id': addon_id,
            'zip': zip_path,
            'label': _optional_str(entry, 'label'),
            'description': _optional_str(entry, 'description'),
            'version': _optional_str(entry, 'version'),
            'sha256': _optional_sha256(entry),
            'requires_qlsm_version': _optional_str(entry, 'requires_qlsm_version'),
        })
    return addons


def fetch_manifest(base_url):
    """Fetch and validate the repository manifest.

    Tries <base_url>/qlsm-repository.json first; if that fetch fails (not
    published, older repo), falls back to the original plugins-only
    <base_url>/qlsm-plugins.json. Returns {'plugins': [...], 'addons': [...]},
    both lists always present even if empty. A malformed individual entry is
    dropped rather than failing the whole fetch -- same "never throws on one
    bad entry" rule plugin_manifest.py already applies to `.ql-plugin.json`.
    Raises PluginRepositoryError for anything wrong with the fetch itself or
    the manifest's outer shape (a v2 file that exists but is broken is an
    error, not a fall-through to v1 -- it would silently hide the breakage).
    """
    url = _manifest_url(base_url, REPO_MANIFEST_FILENAME)
    try:
        content = _fetch(url, MANIFEST_MAX_SIZE)
    except PluginRepositoryError:
        url = _manifest_url(base_url)
        try:
            content = _fetch(url, MANIFEST_MAX_SIZE)
        except PluginRepositoryError as e:
            raise PluginRepositoryError(f"{e} (also tried {REPO_MANIFEST_FILENAME})") from e

    try:
        data = json.loads(content)
    except ValueError as e:
        raise PluginRepositoryError(f"{url} is not valid JSON: {e}") from e
    if (not isinstance(data, dict)
            or not (isinstance(data.get('plugins'), list) or isinstance(data.get('addons'), list))):
        raise PluginRepositoryError(
            f"{url} must be a JSON object with a \"plugins\" and/or \"addons\" array"
        )

    return {
        'plugins': _normalize_plugins(data.get('plugins') or []),
        'addons': _normalize_addons(data.get('addons') or []),
    }


def build_inline_manifest(entry):
    """The pool sidecar dict for a repo manifest entry, or None when the entry
    carries no metadata (a bare {"filename": ...}, or only empty values) or
    the result is bigger than plugin_manifest.py would read anyway. The size
    is measured on compact json.dumps() output, which is exactly what
    download_plugin() writes."""
    if not entry:
        return None
    # Falsy means absent: None, '' and [] all count as "no metadata here".
    manifest = {field: entry[field] for field in _SIDECAR_FIELDS if entry.get(field)}
    if not manifest:
        return None
    if len(json.dumps(manifest).encode('utf-8')) > PLUGIN_MANIFEST_MAX_SIZE:
        logger.warning(f"Inline manifest for {entry.get('filename')} exceeds {PLUGIN_MANIFEST_MAX_SIZE} bytes, skipping")
        return None
    return manifest


def _read_app_version():
    """This qlsm install's own VERSION file. Mirrors
    ui/task_logic/backup_export.py's _read_app_version() -- kept as its own
    copy rather than a shared import since it's five lines and the two
    modules have no other reason to depend on each other."""
    try:
        with open('VERSION', 'r', encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return None


def _parse_dotted_version(value):
    if not isinstance(value, str):
        return None
    parts = value.strip().split('.')
    if not parts:
        return None
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def version_risk(requires_qlsm_version, current_qlsm_version=None):
    """Whether a plugin's declared `requires_qlsm_version` is a known problem
    for this install.

    We cannot confirm a plugin works at all -- not below its stated
    requirement, and not above it either, since "requires >= X" says nothing
    about whether a much newer qlsm broke something the plugin relies on.
    The one thing we CAN state with certainty is the opposite case: this
    install is older than what the plugin declares it needs, so a feature it
    depends on (e.g. a `.ql-plugin.json` field a later qlsm release added)
    may simply not exist yet. That -- and only that -- gets a hard warning;
    everything else returns None (no verdict, shown as plain info in the UI).
    """
    if current_qlsm_version is None:
        current_qlsm_version = _read_app_version()
    required = _parse_dotted_version(requires_qlsm_version)
    current = _parse_dotted_version(current_qlsm_version)
    if required is None or current is None or required <= current:
        return None
    return {
        'level': 'hard',
        'message': f"Needs qlsm >= {requires_qlsm_version}; this install runs {current_qlsm_version}.",
    }


def download_plugin(base_url, filename, runtime, overwrite=False, inline_manifest=None):
    """Fetch <base_url>/<filename> over HTTP and write it into the local pool
    for `runtime`, together with its `.ql-plugin.json` sidecar: the repo's own
    separate sidecar file when it ships a parseable one, else
    `inline_manifest` (the entry's metadata from qlsm-plugins.json, see
    build_inline_manifest), else none -- and any stale pool sidecar is
    removed. The separate-sidecar fetch is always attempted, even when
    `inline_manifest` is given, because the separate file wins by design;
    for a single-file repo that is one expected 404 per plugin. Raises
    PluginRepositoryError if the plugin source itself can't be fetched; a
    missing, malformed or non-object separate sidecar is not an error.

    Writes always land in the operator tier (data/shared-plugins/<runtime>/);
    the built-in tier inside the image is never modified. Refuses to shadow a
    file already in the merged pool -- an earlier download, or a bundled
    plugin such as balance.py -- unless `overwrite` is set (a copy that
    matches apart from line endings is left alone instead): the operator copy
    then wins over the bundled one on every host and breaks the manifest.json
    sha256 baseline, so it has to be a deliberate choice. The caller (the
    route) is the one that turns this into an operator-facing
    confirm-and-retry. Sidecar handling is scoped to the operator tier: a
    bundled plugin's own sidecar stays where it is, and read_plugin_manifest()
    still falls back to it when the download brings none of its own.
    """
    if not is_safe_plugin_filename(filename):
        raise PluginRepositoryError(f"Refusing to download unsafe filename: {filename!r}")

    pool_dir = operator_pool_dir(runtime)
    dest_path = os.path.join(pool_dir, filename)

    source = fetch_plugin_source(base_url, filename)
    existing_path = resolve_pool_file(runtime, filename)
    if existing_path and not overwrite:
        # Same code already in the pool (ignoring CRLF/LF) is "up to date",
        # not a collision: keep the local copy as is. Otherwise the operator
        # decides via the prompt.
        with open(existing_path, 'rb') as f:
            existing = f.read()
        if _normalize_eol(existing) != _normalize_eol(source):
            raise PluginRepositoryError(
                f"{filename} already exists in the local pool.", code='exists',
            )
        if existing_path != dest_path:
            # The match is the built-in copy. Writing a sidecar next to a
            # .py that isn't there would leave an orphan in the operator
            # tier that shadows the bundled sidecar for every later release.
            # An earlier operator download, by contrast, still gets its
            # sidecar synced below.
            return
    else:
        os.makedirs(pool_dir, exist_ok=True)
        with open(dest_path, 'wb') as f:
            f.write(source)

    manifest_filename = filename[:-len('.py')] + '.ql-plugin.json'
    manifest_path = os.path.join(pool_dir, manifest_filename)
    try:
        manifest_content = _fetch(base_url.rstrip('/') + '/' + manifest_filename, MANIFEST_MAX_SIZE)
        # Validate before writing -- same trust boundary as the .py source.
        # Must be a JSON object: load_manifest_file() rejects anything else,
        # so a repo shipping `[]` here should fall through to inline instead.
        if not isinstance(json.loads(manifest_content), dict):
            raise ValueError('sidecar is not a JSON object')
    except (PluginRepositoryError, ValueError):
        # Compact JSON on purpose: build_inline_manifest() measured the
        # compact form against PLUGIN_MANIFEST_MAX_SIZE, and the pool reader
        # checks the on-disk size against the same cap.
        manifest_content = json.dumps(inline_manifest).encode('utf-8') if inline_manifest else None
    if manifest_content is None:
        # No usable sidecar this time around -- a stale one from a previous
        # download of this same filename must not linger and describe the
        # new .py incorrectly.
        if os.path.exists(manifest_path):
            os.remove(manifest_path)
        return
    with open(manifest_path, 'wb') as f:
        f.write(manifest_content)


def download_addon(base_url, entry, packages_dir):
    """Fetch the addon .zip a normalized manifest entry points at and install
    it through the same installer the upload path uses (install_addon_zip,
    with all its archive guards and its atomic replace-with-rollback -- which
    is also what makes this the update path: installing over an existing
    addon *is* the upgrade). Returns the installed addon's parsed
    qlsm-addon.json manifest. The addon is not live until QLSM restarts,
    exactly like an uploaded one.
    """
    blob = _fetch(base_url.rstrip('/') + '/' + entry['zip'], MAX_ARCHIVE_BYTES)

    declared = entry.get('sha256')
    if declared and hashlib.sha256(blob).hexdigest() != declared:
        raise PluginRepositoryError(
            f"{entry['zip']} does not match the sha256 the repository manifest "
            f"declares -- refusing to install."
        )

    # Validate the archive and its manifest *before* touching the packages
    # dir, so an id mismatch never leaves a half-trusted package installed.
    try:
        manifest = read_manifest_from_blob(blob)
    except AddonInstallError as e:
        raise PluginRepositoryError(f"{entry['zip']} is not a valid addon package: {e}") from e
    if manifest['id'] != entry['id']:
        raise PluginRepositoryError(
            f"{entry['zip']} contains addon \"{manifest['id']}\" but the repository "
            f"manifest entry says \"{entry['id']}\" -- refusing to install."
        )

    try:
        install_addon_zip(blob, packages_dir)
    except AddonInstallError as e:
        raise PluginRepositoryError(f"Could not install \"{entry['id']}\": {e}") from e
    return manifest


# Shared update-status vocabulary for both artifact kinds. 'unknown' means
# the manifest doesn't carry enough to compare (no sha256 / no version /
# no runtime to locate the pool file), not that anything is wrong.
STATUS_NOT_INSTALLED = 'not_installed'
STATUS_UP_TO_DATE = 'up_to_date'
STATUS_UPDATE_AVAILABLE = 'update_available'
STATUS_UNKNOWN = 'unknown'


def plugin_update_status(entry):
    """One normalized repo plugin entry vs the local pool, by content hash.

    Purely local -- compares the manifest's declared sha256 against the
    hash of the pool file's LF-normalized content (the same CRLF-insensitive
    equality download_plugin() applies), no network. The pool copy examined
    is the merged view (resolve_pool_file: operator tier over built-in),
    i.e. exactly the copy a download would be compared against. Which pool
    to look in comes from the entry's own declared runtime; without one
    there is nothing to compare against. Note this is name-based: a
    same-named file the operator authored themselves will honestly show as
    differing from the repository's copy.
    """
    runtime = entry.get('runtime')
    if not is_valid_runtime(runtime):
        return STATUS_UNKNOWN
    path = resolve_pool_file(normalize_runtime(runtime), entry['filename'])
    if path is None:
        return STATUS_NOT_INSTALLED
    declared = entry.get('sha256')
    if not declared:
        return STATUS_UNKNOWN
    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError:
        return STATUS_NOT_INSTALLED
    return (STATUS_UP_TO_DATE
            if hashlib.sha256(_normalize_eol(content)).hexdigest() == declared
            else STATUS_UPDATE_AVAILABLE)


def plugin_update_status_with_dependencies(plugins, entry):
    """plugin_update_status() for one entry, folding in its `depends_on`
    closure.

    A hidden helper has no row of its own to carry a badge, so a plugin whose
    helper is missing or stale must not read "Up to date" -- clicking Download
    on it genuinely has something to fetch. The plugin's own verdict still
    wins when it is `not_installed`: the helper is beside the point until the
    plugin itself is there.
    """
    own = plugin_update_status(entry)
    if own == STATUS_NOT_INSTALLED:
        return own
    by_name = {e['filename']: e for e in plugins}
    closure, _pulled_by = expand_with_dependencies(plugins, [entry['filename']])
    for name in closure:
        if name == entry['filename'] or name not in by_name:
            continue
        if plugin_update_status(by_name[name]) in (STATUS_NOT_INSTALLED, STATUS_UPDATE_AVAILABLE):
            return STATUS_UPDATE_AVAILABLE
    return own


def addon_update_status(entry, packages_dir):
    """One normalized repo addon entry vs what's installed on the volume.

    Compares versions (the repo entry's against the installed package's own
    qlsm-addon.json), reading the volume directly rather than the registry so
    a just-installed, pending-restart addon is already judged by its new
    version. Only looks at ADDON_PACKAGES_DIR: a bundled-only addon reports
    not_installed, since installing from the repo would create the volume
    copy that overrides it -- which is the supported way to update a bundled
    addon anyway. Returns {'id', 'status', 'installed_version',
    'available_version'}.
    """
    result = {
        'id': entry['id'],
        'status': STATUS_UNKNOWN,
        'installed_version': None,
        'available_version': entry.get('version'),
    }
    if not packages_dir:
        return result
    target = os.path.join(packages_dir, entry['id'])
    if not os.path.isfile(os.path.join(target, ADDON_MANIFEST_FILENAME)):
        result['status'] = STATUS_NOT_INSTALLED
        return result
    manifest, _errors = read_addon_manifest(target)
    installed = (manifest or {}).get('version') or None
    result['installed_version'] = installed
    available = entry.get('version')
    if not installed or not available:
        return result
    parsed_available = _parse_dotted_version(available)
    parsed_installed = _parse_dotted_version(installed)
    if parsed_available is not None and parsed_installed is not None:
        newer = parsed_available > parsed_installed
    else:
        # Unparseable version strings still deserve a verdict: different
        # string = the repo ships something else than what's installed.
        newer = available.strip() != installed.strip()
    result['status'] = STATUS_UPDATE_AVAILABLE if newer else STATUS_UP_TO_DATE
    return result
