"""Server-side demo listing and download, as an addon.

**Migration state.** Ships alongside the built-in Demos modal, which stays
until this has been checked against real recordings on a real host. Both
appear in the instance menu meanwhile; this one is suffixed "(addon)".

Like the telemetry-relay addon, this delegates to the existing
`ui.task_logic.ansible_instance_demos` helpers instead of copying them. Those
helpers do the security-relevant work -- validating every filename against
DEMO_FILENAME_RE *before* it is concatenated into a remote path for SFTP --
and re-implementing that check here would be the single most dangerous thing
this port could do.
"""
import io
import re
import zipfile

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import jwt_required

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
    from ui.task_logic.ansible_instance_demos import list_instance_demos

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
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos

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
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos

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


def register(ctx):
    ctx.blueprint(bp)
