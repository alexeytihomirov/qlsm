"""Core-owned addon endpoints: the catalog, per-scope state, and tier-2 assets.

Everything here is about addons; an addon's *own* endpoints live in its own
blueprint, mounted by the registry at /api/addons/<id>/. This module owns
/api/addons (no id) plus the /state and /ui sub-resources of an addon, which
core must own because an addon cannot be trusted to report its own enable
state or to serve its own files safely.
"""
import os

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import jwt_required

from ui.addons import catalog, get_addon
from ui.addons.settings import AddonSettingsError

addon_api_bp = Blueprint('addon_routes', __name__)

_SCOPES = ('global', 'host', 'instance')


def _resolve(addon_id):
    """(addon, error_response) -- error is None when the addon is usable."""
    addon = get_addon(addon_id)
    if addon is None:
        return None, (jsonify({"error": {"message": f'Addon "{addon_id}" is not installed'}}), 404)
    if not addon.loaded:
        return None, (jsonify({"error": {
            "message": f'Addon "{addon_id}" failed to load',
            "details": addon.errors,
        }}), 409)
    return addon, None


def _scope_args():
    scope = (request.args.get('scope') or 'global').strip().lower()
    if scope not in _SCOPES:
        return None, None, (jsonify({"error": {"message": f'Unknown scope "{scope}"'}}), 400)
    raw_id = request.args.get('scope_id', '0')
    try:
        scope_id = int(raw_id)
    except (TypeError, ValueError):
        return None, None, (jsonify({"error": {"message": 'scope_id must be an integer'}}), 400)
    return scope, scope_id, None


@addon_api_bp.route('', methods=['GET'], endpoint='list_addons_api')
@addon_api_bp.route('/', methods=['GET'], endpoint='list_addons_slash_api')
@jwt_required()
def list_addons_api():
    """Every discovered addon, including the broken ones.

    Broken addons are listed on purpose: an addon that silently vanished from
    the UI because its manifest has a typo is far harder to diagnose than one
    shown with its error attached.

    The list is what this *process* loaded at startup, reconciled against
    what is on the volume right now. An addon installed or removed since then
    shows up as `pending_restart` rather than silently looking active -- the
    alternative is an entry whose endpoints 404 with no explanation.
    """
    from ui.addons.install import scan_installed_ids

    entries = catalog()
    loaded_ids = {entry['id'] for entry in entries}
    on_disk = scan_installed_ids(current_app.config.get('ADDON_PACKAGES_DIR'))

    for entry in entries:
        # Loaded, but its package is gone from the volume -> uninstalled since boot.
        entry['pending_restart'] = (entry['source'] == 'installed' and entry['id'] not in on_disk)
        entry['pending_action'] = 'uninstall' if entry['pending_restart'] else None

    for addon_id in sorted(on_disk - loaded_ids):
        entries.append({
            'id': addon_id, 'name': addon_id, 'version': '', 'description': '',
            'scopes': [], 'ui': {}, 'ui_api': None, 'settings_schema': {},
            'source': 'installed', 'loaded': False, 'ui_mountable': False,
            'errors': [], 'pending_restart': True, 'pending_action': 'install',
        })

    return jsonify({"data": {"addons": entries}})


@addon_api_bp.route('/install', methods=['POST'], endpoint='install_addon_api')
@jwt_required()
def install_addon_api():
    """Install an addon package from an uploaded .zip.

    The addon is **not** live until QLSM restarts: Flask cannot unregister or
    hot-add a blueprint on a running app, and pretending otherwise would give
    the operator an addon that is listed but whose endpoints 404. The catalog
    marks it `pending_restart` instead, and the UI says so.
    """
    from ui.addons.install import AddonInstallError, install_addon_zip

    upload = request.files.get('file')
    if upload is None:
        return jsonify({"error": {"message": "No file uploaded (field name: 'file')."}}), 400

    packages_dir = current_app.config.get('ADDON_PACKAGES_DIR')
    if not packages_dir:
        return jsonify({"error": {"message": "ADDON_PACKAGES_DIR is not configured."}}), 500

    try:
        manifest = install_addon_zip(upload.read(), packages_dir)
    except AddonInstallError as e:
        return jsonify({"error": {"message": str(e)}}), 400
    except Exception as e:
        current_app.logger.error(f'Addon install failed: {e}', exc_info=True)
        return jsonify({"error": {"message": "Failed to install the addon."}}), 500

    current_app.logger.info(f'Addon "{manifest["id"]}" v{manifest["version"]} installed.')
    return jsonify({"data": {
        "id": manifest['id'],
        "name": manifest['name'],
        "version": manifest['version'],
        "pending_restart": True,
    }, "message": f'"{manifest["name"]}" installed. Restart QLSM to activate it.'}), 201


@addon_api_bp.route('/<addon_id>', methods=['DELETE'], endpoint='uninstall_addon_api')
@jwt_required()
def uninstall_addon_api(addon_id):
    """Remove an installed addon package.

    Refuses bundled addons: they live in the image, so deleting the directory
    would leave this container inconsistent and the addon would reappear on
    the next deploy anyway.

    AddonState rows are kept on purpose -- reinstalling the same addon should
    find its settings again. See addons/TRUST.md for what uninstalling does
    *not* undo.
    """
    from ui.addons.install import AddonInstallError, uninstall_addon

    addon = get_addon(addon_id)
    if addon is not None and addon.source == 'bundled':
        return jsonify({"error": {
            "message": "This addon ships with QLSM and cannot be uninstalled."
        }}), 400

    packages_dir = current_app.config.get('ADDON_PACKAGES_DIR')
    if not packages_dir:
        return jsonify({"error": {"message": "ADDON_PACKAGES_DIR is not configured."}}), 500

    try:
        removed = uninstall_addon(addon_id, packages_dir)
    except AddonInstallError as e:
        return jsonify({"error": {"message": str(e)}}), 400

    if not removed:
        return jsonify({"error": {"message": f'Addon "{addon_id}" is not installed.'}}), 404

    current_app.logger.info(f'Addon "{addon_id}" uninstalled.')
    return jsonify({"data": {"id": addon_id, "pending_restart": True},
                    "message": f'"{addon_id}" removed. Restart QLSM to unload it.'})


@addon_api_bp.route('/<addon_id>/state', methods=['GET'], endpoint='get_addon_state_api')
@jwt_required()
def get_addon_state_api(addon_id):
    addon, error = _resolve(addon_id)
    if error:
        return error
    scope, scope_id, error = _scope_args()
    if error:
        return error
    settings = addon.ctx.settings
    return jsonify({"data": {
        "addon_id": addon_id,
        "scope": scope,
        "scope_id": scope_id,
        # `enabled` is this layer's own switch; `effective` is it after the
        # layers above are taken into account. The UI needs both to render
        # "on, but blocked by host" rather than a misleading single toggle.
        "enabled": settings.is_layer_enabled(scope, scope_id),
        "effective": settings.is_enabled(scope, scope_id),
        "settings": settings.get(scope, scope_id),
        "schema": settings.fields(scope),
    }})


@addon_api_bp.route('/<addon_id>/state', methods=['PUT'], endpoint='update_addon_state_api')
@jwt_required()
def update_addon_state_api(addon_id):
    addon, error = _resolve(addon_id)
    if error:
        return error
    scope, scope_id, error = _scope_args()
    if error:
        return error

    body = request.get_json(silent=True) or {}
    settings = addon.ctx.settings
    try:
        if 'settings' in body:
            settings.set(scope, scope_id, body['settings'], commit=False)
        if 'enabled' in body:
            settings.set_enabled(scope, scope_id, bool(body['enabled']), commit=False)
    except AddonSettingsError as e:
        from ui import db
        db.session.rollback()
        return jsonify({"error": {"message": str(e)}}), 400
    except Exception as e:
        from ui import db
        db.session.rollback()
        current_app.logger.error(f'Addon {addon_id} state update failed: {e}', exc_info=True)
        return jsonify({"error": {"message": 'Failed to update addon state'}}), 500

    from ui import db
    db.session.commit()
    return jsonify({"data": {
        "addon_id": addon_id,
        "scope": scope,
        "scope_id": scope_id,
        "effective": settings.is_enabled(scope, scope_id),
        "settings": settings.get(scope, scope_id),
    }})


@addon_api_bp.route('/<addon_id>/ui/<path:filename>', methods=['GET'], endpoint='get_addon_ui_asset_api')
@jwt_required()
def get_addon_ui_asset_api(addon_id, filename):
    """Serve a tier-2 pre-built component from the addon's own ui/ directory.

    Only .js/.css/.map are served: the addon directory also holds backend.py,
    playbooks and assets, and this route must never become a way to read them
    over HTTP. The path is resolved and re-checked against the ui/ root, so a
    traversal attempt fails even if Flask's own converter ever changes.
    """
    addon, error = _resolve(addon_id)
    if error:
        return error
    if os.path.splitext(filename)[1].lower() not in ('.js', '.css', '.map'):
        return jsonify({"error": {"message": 'Only .js, .css and .map assets are served'}}), 403

    ui_root = os.path.abspath(addon.ctx.ui_dir)
    target = os.path.abspath(os.path.join(ui_root, filename))
    if target != ui_root and not target.startswith(ui_root + os.sep):
        return jsonify({"error": {"message": 'Invalid asset path'}}), 400
    if not os.path.isfile(target):
        return jsonify({"error": {"message": 'Asset not found'}}), 404
    return send_file(target)
