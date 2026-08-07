"""Global backup export/import endpoints."""
import io

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import jwt_required

from ui.task_lock import any_lock_held
from ui.task_logic.backup_db_import import BackupImportError
from ui.task_logic.backup_export import build_backup_archive
from ui.task_logic.backup_import import BackupRestoreError, restore_backup_archive

backup_api_bp = Blueprint('backup_api_routes', __name__)

MAX_BACKUP_UPLOAD_BYTES = 500 * 1024 * 1024


def _locked_response():
    return jsonify({'error': {'message': 'Cannot do this while a background task is running. Try again shortly.'}}), 409


@backup_api_bp.route('/export', methods=['POST'])
@jwt_required()
def export_backup():
    if any_lock_held():
        return _locked_response()

    data = request.get_json(silent=True) or {}
    password = data.get('password') or None
    if password is not None and not isinstance(password, str):
        return jsonify({'error': {'message': 'password must be a string.'}}), 400

    try:
        blob, filename = build_backup_archive(password)
    except Exception as e:
        current_app.logger.error('Error building backup archive: %s', e, exc_info=True)
        return jsonify({'error': {'message': 'Failed to build backup archive.'}}), 500

    current_app.logger.info('Global backup exported (encrypted=%s).', bool(password))
    return send_file(
        io.BytesIO(blob),
        as_attachment=True,
        download_name=filename,
        mimetype='application/octet-stream',
    )


@backup_api_bp.route('/import', methods=['POST'])
@jwt_required()
def import_backup():
    if any_lock_held():
        return _locked_response()

    if 'file' not in request.files:
        return jsonify({'error': {'message': 'No file provided'}}), 400
    upload = request.files['file']
    if not upload.filename:
        return jsonify({'error': {'message': 'No file selected'}}), 400

    upload.seek(0, 2)
    size = upload.tell()
    upload.seek(0)
    if size == 0:
        return jsonify({'error': {'message': 'Empty file.'}}), 400
    if size > MAX_BACKUP_UPLOAD_BYTES:
        limit_mb = MAX_BACKUP_UPLOAD_BYTES // (1024 * 1024)
        return jsonify({'error': {'message': f'Archive exceeds {limit_mb}MB.'}}), 400

    password = request.form.get('password') or None
    blob = upload.read()

    try:
        summary = restore_backup_archive(blob, password)
    except (BackupRestoreError, BackupImportError) as e:
        return jsonify({'error': {'message': str(e)}}), 400
    except Exception as e:
        current_app.logger.error('Error restoring backup: %s', e, exc_info=True)
        return jsonify({'error': {'message': 'Failed to restore backup.'}}), 500

    current_app.logger.warning('Global backup restored — prior state was wiped and replaced.')
    return jsonify({'data': summary, 'message': 'Backup restored successfully.'})
