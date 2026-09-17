"""Content-hash diff engine for "Check for Updates".

Replaces the old blind "Update Plugins" backfill (which silently skipped any
file an instance had explicitly selected — see the match_restore.py incident)
with an explicit diff: hash the source of truth (ql-assets pool, on the qlsm
controller) against whatever's actually deployed, and let the operator pick
which changes to apply. Two comparison shapes are needed:

- Local vs local (instance-selected plugins: ql-assets pool vs
  configs/{host}/{instance}/scripts/, both live on the qlsm controller's own
  filesystem — no SSH needed).
- Local vs remote (host common plugin pool on the target VPS) — needs an
  ansible ad-hoc hash listing, see ansible_adhoc.py.
"""

import hashlib
import os

PLUGIN_EXTENSIONS = ('.py', '.ql-plugin.json')


def hash_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def hash_local_tree(root_dir, extensions=None):
    """Returns {relpath: sha256} for every file under root_dir, recursive.
    Plugin pools aren't guaranteed flat (e.g. discord_extensions/,
    extras/ already ship as subfolders under minqlx-plugins/), so this
    walks subdirectories too. relpath keys use forward slashes regardless
    of OS, matching the remote find/sha256sum output parsed by
    parse_sha256sum_output()."""
    result = {}
    if not os.path.isdir(root_dir):
        return result
    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for filename in filenames:
            if extensions and not filename.endswith(extensions):
                continue
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, root_dir).replace(os.sep, '/')
            result[rel_path] = hash_file(full_path)
    return result


def parse_sha256sum_output(output, strip_prefix=None):
    """Parses `sha256sum <files>` output ("<hash>  <path>\\n" per line) into
    {relpath: hash}. strip_prefix removes a leading directory so remote
    absolute paths become the same relative keys as hash_local_tree()."""
    result = {}
    for line in output.splitlines():
        line = line.rstrip('\n')
        if not line or '  ' not in line:
            continue
        digest, _, path = line.partition('  ')
        digest = digest.strip()
        path = path.strip()
        if strip_prefix and path.startswith(strip_prefix):
            path = path[len(strip_prefix):]
        path = path.lstrip('/')
        if digest and path:
            result[path] = digest
    return result


def diff_trees(source, target):
    """source = what SHOULD be deployed (pool), target = what IS deployed.
    Returns a list of {"name": ..., "change": "added"|"modified"|"removed"},
    sorted by name. "added" = in source but missing from target (new file
    upstream). "removed" = in target but gone from source (only reported for
    visibility — apply never deletes instance-selected files)."""
    changes = []
    for name, src_hash in source.items():
        tgt_hash = target.get(name)
        if tgt_hash is None:
            changes.append({"name": name, "change": "added"})
        elif tgt_hash != src_hash:
            changes.append({"name": name, "change": "modified"})
    for name in target:
        if name not in source:
            changes.append({"name": name, "change": "removed"})
    changes.sort(key=lambda c: c["name"])
    return changes
