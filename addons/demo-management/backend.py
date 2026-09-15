"""Server-side demo listing and download, as an addon.

The built-in Demos modal and its core endpoints were deleted once this addon
was verified against real recordings on a real host - this is now the only
place the feature lives, including `ansible_instance_demos.py` itself (moved
in alongside this backend rather than staying in ui/task_logic/, so the
security-relevant filename validation -- DEMO_FILENAME_RE, checked *before*
a name is concatenated into a remote SFTP path -- lives next to its only
caller instead of split across core and addon).

Also owns the external, Bearer-token-authenticated match-listing API
(`/instances/<id>/matches*` below) that used to live in core's
external_api_routes.py: third-party services authenticate the same way
against this addon's URL now. Uninstalling this addon removes that
integration along with the operator-facing UI - by design, since the two
share the same underlying SFTP/validation logic.
"""
import io
import re
import zipfile

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import jwt_required
from ui import limiter

bp = Blueprint('demo_management_addon', __name__)


def _instance_or_error(instance_id):
    from ui.database import get_instance

    instance = get_instance(instance_id)
    if not instance:
        return None, (jsonify({"error": {"message": "Instance not found."}}), 404)
    if not instance.host:
        return None, (jsonify({"error": {"message": "Instance has no associated host."}}), 400)
    return instance, None


@bp.route('/instances/<int:instance_id>/demos', methods=['GET'], endpoint='list_demos')
@jwt_required()
def list_demos(instance_id):
    from .ansible_instance_demos import list_instance_demos

    instance, error = _instance_or_error(instance_id)
    if error:
        return error

    success, demos, error_msg = list_instance_demos(instance_id)
    if not success:
        current_app.logger.error(f'Addon demo-management: list failed for {instance_id}: {error_msg}')
        return jsonify({"error": {"message": error_msg}}), 500

    return jsonify({"data": {"demos": demos, "instance_name": instance.name}})


@bp.route('/instances/<int:instance_id>/demos/download', methods=['GET'], endpoint='download_demo')
@jwt_required()
def download_demo(instance_id):
    from .ansible_instance_demos import fetch_instance_demos

    instance, error = _instance_or_error(instance_id)
    if error:
        return error

    filename = request.args.get('filename', '')
    if not filename:
        return jsonify({"error": {"message": "filename is required."}}), 400

    success, files, missing, error_msg = fetch_instance_demos(instance_id, [filename])
    if not success:
        current_app.logger.error(f'Addon demo-management: download failed for {instance_id}: {error_msg}')
        return jsonify({"error": {"message": error_msg}}), 500
    if filename in missing or filename not in files:
        return jsonify({"error": {"message": "Demo file not found on the remote host."}}), 404

    return send_file(
        io.BytesIO(files[filename]),
        as_attachment=True,
        download_name=filename,
        mimetype='application/octet-stream',
    )


@bp.route('/instances/<int:instance_id>/demos/download-batch', methods=['POST'], endpoint='download_demos_batch')
@jwt_required()
def download_demos_batch(instance_id):
    """Zip up a checkbox selection.

    The table panel posts the selection under the key the manifest declares
    (`selection_key: "filenames"`), which is the name this endpoint and the
    built-in one already use.
    """
    from .ansible_instance_demos import fetch_instance_demos

    instance, error = _instance_or_error(instance_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    filenames = data.get('filenames')
    if not isinstance(filenames, list) or not filenames:
        return jsonify({"error": {"message": "filenames must be a non-empty list."}}), 400

    success, files, missing, error_msg = fetch_instance_demos(instance_id, filenames)
    if not success:
        current_app.logger.error(f'Addon demo-management: batch failed for {instance_id}: {error_msg}')
        return jsonify({"error": {"message": error_msg}}), 500
    if not files:
        return jsonify({"error": {"message": "None of the selected files were found on the remote host."}}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    buf.seek(0)

    safe_name = re.sub(r'[^A-Za-z0-9._-]+', '-', instance.name or '').strip('.-') or 'instance'
    return send_file(
        buf,
        as_attachment=True,
        download_name=f'{safe_name}-demos.zip',
        mimetype='application/zip',
    )


# ---- external API (Bearer token, not JWT) -------------------------------
# Moved from ui/routes/external_api_routes.py's /api/v1/instances/<id>/matches*
# - same require_api_key() auth, now mounted under this addon's own prefix.
# The generic /api/v1/instances listing stayed in core (nothing demo-specific
# about it); only the three match-listing/download routes moved.

_QLMATCH_SUFFIX = '.qlmatch'
_REPLAY_SUFFIX = '.replay.json.gz'  # keep in sync with ansible_instance_demos.SIDECAR_EXT


def _require_instance_external(instance_id):
    from ui.database import get_instance

    instance = get_instance(instance_id)
    if not instance:
        return None, (jsonify({'error': {'message': 'Instance not found.'}}), 404)
    if not instance.host:
        return None, (jsonify({'error': {'message': 'Instance has no associated host.'}}), 400)
    return instance, None


def _external_download_demo(instance_id, filename, expected_suffix):
    from .ansible_instance_demos import fetch_instance_demos

    if not filename.endswith(expected_suffix):
        return jsonify({'error': {'message': f"filename must end with '{expected_suffix}'."}}), 400

    success, files, missing, error_msg = fetch_instance_demos(instance_id, [filename])
    if not success:
        return jsonify({'error': {'message': error_msg}}), 500
    if filename in missing or filename not in files:
        return jsonify({'error': {'message': 'File not found on the remote host.'}}), 404

    return send_file(
        io.BytesIO(files[filename]),
        as_attachment=True,
        download_name=filename,
        mimetype='application/octet-stream',
    )


@bp.route('/instances/<int:instance_id>/matches', methods=['GET'], endpoint='external_list_instance_matches')
@limiter.limit("200 per minute")
def external_list_instance_matches(instance_id):
    """List recorded .qlmatch demos for an instance, flagging replay availability.

    Secured via Bearer token (API key), not JWT cookies - for external
    services, unlike every other route in this blueprint.
    """
    from ui.routes.settings_routes import require_api_key

    ok, err_response = require_api_key()
    if not ok:
        return err_response

    instance, err_response = _require_instance_external(instance_id)
    if err_response:
        return err_response

    from .ansible_instance_demos import list_instance_qlmatches

    success, matches, error_msg = list_instance_qlmatches(instance_id)
    if not success:
        return jsonify({'error': {'message': error_msg}}), 500

    return jsonify({'data': {'matches': matches, 'instance_name': instance.name}})


@bp.route('/instances/<int:instance_id>/matches/download', methods=['GET'], endpoint='external_download_instance_match')
@limiter.limit("200 per minute")
def external_download_instance_match(instance_id):
    """Download a single .qlmatch file by name for an instance. Bearer token."""
    from ui.routes.settings_routes import require_api_key

    ok, err_response = require_api_key()
    if not ok:
        return err_response

    _, err_response = _require_instance_external(instance_id)
    if err_response:
        return err_response

    filename = request.args.get('filename', '')
    return _external_download_demo(instance_id, filename, _QLMATCH_SUFFIX)


@bp.route('/instances/<int:instance_id>/matches/replay', methods=['GET'], endpoint='external_download_instance_match_replay')
@limiter.limit("200 per minute")
def external_download_instance_match_replay(instance_id):
    """Download the .replay.json.gz sidecar for a recorded match, by name. Bearer token."""
    from ui.routes.settings_routes import require_api_key

    ok, err_response = require_api_key()
    if not ok:
        return err_response

    _, err_response = _require_instance_external(instance_id)
    if err_response:
        return err_response

    filename = request.args.get('filename', '')
    return _external_download_demo(instance_id, filename, _REPLAY_SUFFIX)


def register(ctx):
    ctx.blueprint(bp)
