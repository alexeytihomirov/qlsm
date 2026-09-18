"""Parse + validate an addon's `qlsm-addon.json` manifest.

Design: docs/superpowers/specs/2026-09-14-qlsm-addon-system-design.md (monorepo).

Validation never raises. A malformed manifest yields a list of human-readable
errors and the addon is reported as `broken` in the catalog instead of loading
-- same principle as ui/plugin_manifest.load_manifest_file(), one level up: a
bad addon must never take qlsm's startup down with it.
"""
import json
import os
import re

MANIFEST_FILENAME = 'qlsm-addon.json'
MANIFEST_MAX_SIZE = 64 * 1024  # metadata only, not a data file

ADDON_ID_RE = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')
ADDON_ID_MAX = 64

SCOPES = ('global', 'host', 'instance')
FIELD_TYPES = ('bool', 'number', 'string', 'secret')
PANEL_KINDS = ('form', 'table', 'logs')
MOUNT_POINTS = ('host_menu', 'instance_menu', 'instance_tabs', 'settings_section', 'page')

# `panel` = core renders its shell and the addon fills the body.
# `modal`  = the addon's component *is* the whole dialog. Needed so a
# migration addon can mount a purpose-built screen unchanged rather than a
# generic panel that loses half its controls.
RENDER_MODES = ('panel', 'modal')

# A component core already builds, referenced by name instead of shipped as a
# file. Only meaningful for addons bundled in the image.
BUNDLED_COMPONENT_PREFIX = 'bundled:'

# Bumped when the contract a mounted component sees (ctx shape, ui kit) changes
# in a way an already-built addon bundle cannot survive. An addon declaring a
# higher value is listed but not mounted -- see ui/addons/registry.py.
CURRENT_UI_API = 2


class ManifestError(ValueError):
    """Only raised by parse_manifest_strict(); the normal path collects errors."""


def _err(errors, msg):
    errors.append(msg)
    return errors


def _validate_field(field, where, errors):
    """One settings field / declarative form field."""
    if not isinstance(field, dict):
        return _err(errors, f'{where}: field must be an object')
    key = field.get('key')
    if not isinstance(key, str) or not key.strip():
        return _err(errors, f'{where}: field is missing a "key"')
    ftype = field.get('type')
    if ftype not in FIELD_TYPES:
        return _err(errors, f'{where}.{key}: type must be one of {", ".join(FIELD_TYPES)}')
    for bound in ('min', 'max'):
        if bound in field:
            if ftype != 'number':
                _err(errors, f'{where}.{key}: "{bound}" only applies to type "number"')
            elif not isinstance(field[bound], (int, float)) or isinstance(field[bound], bool):
                _err(errors, f'{where}.{key}: "{bound}" must be a number')
    return errors


def _validate_settings(settings, errors):
    """`settings` maps a scope name to that scope's list of fields."""
    if settings is None:
        return {}
    if not isinstance(settings, dict):
        _err(errors, '"settings" must be an object keyed by scope')
        return {}
    for scope, fields in settings.items():
        if scope not in SCOPES:
            _err(errors, f'"settings": unknown scope "{scope}"')
            continue
        if not isinstance(fields, list):
            _err(errors, f'"settings.{scope}" must be a list of fields')
            continue
        seen = set()
        for field in fields:
            _validate_field(field, f'settings.{scope}', errors)
            key = field.get('key') if isinstance(field, dict) else None
            if key in seen:
                _err(errors, f'settings.{scope}: duplicate field key "{key}"')
            seen.add(key)
    return settings


def _validate_panel(name, panel, errors):
    if not isinstance(panel, dict):
        return _err(errors, f'panels.{name}: must be an object')
    kind = panel.get('kind')
    if kind not in PANEL_KINDS:
        return _err(errors, f'panels.{name}: kind must be one of {", ".join(PANEL_KINDS)}')
    for route_key in ('load', 'submit'):
        route = panel.get(route_key)
        if route is None:
            continue
        if not isinstance(route, str) or not route.strip():
            _err(errors, f'panels.{name}.{route_key}: must be a non-empty string')
            continue
        # Routes are relative to the addon's own /api/addons/<id>/ prefix.
        # Rejecting absolute paths here is what stops a panel from being
        # pointed at a core endpoint (see spec 5.1).
        path = route.split(' ', 1)[-1]
        if path.startswith('/api/') or path.startswith('http://') or path.startswith('https://'):
            _err(errors, f'panels.{name}.{route_key}: must be relative to the addon prefix, not absolute')
    for field in panel.get('fields') or []:
        _validate_field(field, f'panels.{name}', errors)
    return errors


def _validate_ui(ui, errors):
    if ui is None:
        return {}
    if not isinstance(ui, dict):
        _err(errors, '"ui" must be an object')
        return {}

    panels = ui.get('panels') or {}
    if not isinstance(panels, dict):
        _err(errors, '"ui.panels" must be an object')
        panels = {}
    for name, panel in panels.items():
        _validate_panel(name, panel, errors)

    for mount in MOUNT_POINTS:
        entries = ui.get(mount)
        if entries is None:
            continue
        # settings_section / page are single objects; the menu/tab points are lists.
        items = entries if isinstance(entries, list) else [entries]
        for item in items:
            if not isinstance(item, dict):
                _err(errors, f'ui.{mount}: entry must be an object')
                continue
            has_panel = isinstance(item.get('panel'), str) and item['panel'].strip()
            has_component = isinstance(item.get('component'), str) and item['component'].strip()
            if not has_panel and not has_component:
                _err(errors, f'ui.{mount}: entry needs either "panel" or "component"')
            if has_panel and has_component:
                _err(errors, f'ui.{mount}: entry has both "panel" and "component" -- pick one')
            if has_panel and item['panel'] not in panels:
                _err(errors, f'ui.{mount}: panel "{item["panel"]}" is not declared in ui.panels')
            if has_component:
                comp = item['component']
                if comp.startswith(BUNDLED_COMPONENT_PREFIX):
                    # A component core already builds, named rather than
                    # shipped. Only resolvable for addons that live in the
                    # image -- the frontend refuses it for an installed one,
                    # since a .zip cannot reach into core's build. This is how
                    # a migration addon mounts the exact screen the built-in
                    # menu mounts instead of a look-alike.
                    name = comp[len(BUNDLED_COMPONENT_PREFIX):]
                    if not name or '/' in name:
                        _err(errors, f'ui.{mount}: bundled component name "{name}" is not valid')
                # Tier-2 components are served from the addon's own ui/ dir;
                # anything escaping it is a path-traversal attempt.
                elif comp.startswith('/') or '..' in comp.split('/'):
                    _err(errors, f'ui.{mount}: component path "{comp}" must stay inside the addon')
            renders = item.get('renders')
            if renders is not None and renders not in RENDER_MODES:
                _err(errors, f'ui.{mount}: "renders" must be one of {", ".join(RENDER_MODES)}')
            if renders == 'modal' and not has_component:
                _err(errors, f'ui.{mount}: "renders": "modal" needs a component, not a panel')
    return ui


def validate_manifest(data):
    """Return (normalized_manifest, errors). `errors` empty means loadable."""
    errors = []
    if not isinstance(data, dict):
        return None, ['manifest must be a JSON object']

    addon_id = data.get('id')
    if not isinstance(addon_id, str) or not addon_id.strip():
        _err(errors, '"id" is required')
        addon_id = None
    else:
        addon_id = addon_id.strip()
        if len(addon_id) > ADDON_ID_MAX:
            _err(errors, f'"id" must be at most {ADDON_ID_MAX} characters')
        if not ADDON_ID_RE.match(addon_id):
            _err(errors, '"id" must be kebab-case (lowercase letters, digits, single dashes)')

    version = data.get('version')
    if not isinstance(version, str) or not version.strip():
        _err(errors, '"version" is required')

    scopes = data.get('scopes') or ['global']
    if not isinstance(scopes, list) or not scopes:
        _err(errors, '"scopes" must be a non-empty list')
        scopes = ['global']
    else:
        for scope in scopes:
            if scope not in SCOPES:
                _err(errors, f'"scopes": unknown scope "{scope}"')
        scopes = [s for s in SCOPES if s in scopes]  # canonical order, deduped

    ui_api = data.get('ui_api', CURRENT_UI_API)
    if not isinstance(ui_api, int) or isinstance(ui_api, bool) or ui_api < 1:
        _err(errors, '"ui_api" must be a positive integer')
        ui_api = CURRENT_UI_API

    depends = data.get('depends') or []
    if not isinstance(depends, list) or any(not isinstance(d, str) for d in depends):
        _err(errors, '"depends" must be a list of addon ids')
        depends = []

    settings = _validate_settings(data.get('settings'), errors)
    ui = _validate_ui(data.get('ui'), errors)

    manifest = {
        'id': addon_id,
        'version': (version or '').strip() if isinstance(version, str) else '',
        'name': data.get('name') or addon_id or '',
        'description': data.get('description') or '',
        'scopes': scopes,
        'ui_api': ui_api,
        'depends': depends,
        'settings': settings,
        'ui': ui,
    }
    return manifest, errors


def read_manifest(directory):
    """Read + validate the manifest in `directory`.

    Returns (manifest_or_None, errors). A missing file is reported as an error
    too -- the caller decides whether a directory without one is simply not an
    addon (registry.py skips those before calling here).
    """
    path = os.path.join(directory, MANIFEST_FILENAME)
    if not os.path.isfile(path):
        return None, [f'{MANIFEST_FILENAME} not found']
    try:
        if os.path.getsize(path) > MANIFEST_MAX_SIZE:
            return None, [f'{MANIFEST_FILENAME} is larger than {MANIFEST_MAX_SIZE} bytes']
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return None, [f'{MANIFEST_FILENAME} could not be read: {e}']
    return validate_manifest(data)
