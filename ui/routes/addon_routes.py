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
    """
    return jsonify({"data": {"addons": catalog()}})


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
