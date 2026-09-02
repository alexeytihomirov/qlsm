import io

from flask import Blueprint, jsonify, request, send_file
from ui import limiter
from ui.database import get_instance, get_instances
from ui.routes.settings_routes import require_api_key

external_api_bp = Blueprint('external_api', __name__)

_EXCLUDED_FIELDS = {'zmq_rcon_port', 'zmq_rcon_password', 'logs', 'config'}

_QLMATCH_SUFFIX = '.qlmatch'
_REPLAY_SUFFIX = '.replay.json.gz'


@external_api_bp.route('/instances', methods=['GET'])
@limiter.limit("200 per minute")
def external_list_instances():
    """List all QLDS instances for external services.

    Secured via Bearer token (API key), not JWT cookies.
    Excludes ZMQ RCON fields for security.
    """
    ok, err_response = require_api_key()
    if not ok:
        return err_response
    instances = get_instances()
    data = []
    for inst in instances:
        d = inst.to_dict()
        for field in _EXCLUDED_FIELDS:
            d.pop(field, None)
        data.append(d)
    return jsonify({'data': data})


def _require_instance(instance_id):
    """Look up an instance for the matches endpoints below.

    Returns (instance, None) on success or (None, error_response) on failure,
    mirroring the instance/host checks instance_routes.py's demo endpoints do
    before touching ansible_instance_demos.py.
    """
    instance = get_instance(instance_id)
    if not instance:
        return None, (jsonify({'error': {'message': 'Instance not found.'}}), 404)
    if not instance.host:
        return None, (jsonify({'error': {'message': 'Instance has no associated host.'}}), 400)
    return instance, None


@external_api_bp.route('/instances/<int:instance_id>/matches', methods=['GET'])
@limiter.limit("200 per minute")
def external_list_instance_matches(instance_id):
    """List recorded .qlmatch demos for an instance, flagging replay availability.

    Secured via Bearer token (API key), not JWT cookies. Reuses the same
    SFTP-backed listing ansible_instance_demos.py already exposes to the
    JWT-authenticated /instances/<id>/demos endpoint in instance_routes.py,
    filtered down to .qlmatch packs (the per-POV .dm_91 files and packer logs
    aren't useful to an external consumer of this API).
    """
    ok, err_response = require_api_key()
    if not ok:
        return err_response

    instance, err_response = _require_instance(instance_id)
    if err_response:
        return err_response

    from ui.task_logic.ansible_instance_demos import list_instance_demos

    success, demos, error_msg = list_instance_demos(instance_id)
    if not success:
        return jsonify({'error': {'message': error_msg}}), 500

    names = {d['name'] for d in demos}
    matches = []
    for d in demos:
        if not d['name'].endswith(_QLMATCH_SUFFIX):
            continue
        replay_name = d['name'][:-len(_QLMATCH_SUFFIX)] + _REPLAY_SUFFIX
        matches.append({
            'name': d['name'],
            'size': d['size'],
            'mtime': d['mtime'],
            'has_replay': replay_name in names,
            'replay_name': replay_name if replay_name in names else None,
        })

    return jsonify({'data': {'matches': matches, 'instance_name': instance.name}})


def _external_download_demo(instance_id, filename, expected_suffix):
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos

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


@external_api_bp.route('/instances/<int:instance_id>/matches/download', methods=['GET'])
@limiter.limit("200 per minute")
def external_download_instance_match(instance_id):
    """Download a single .qlmatch file by name for an instance.

    Secured via Bearer token (API key), not JWT cookies.
    """
    ok, err_response = require_api_key()
    if not ok:
        return err_response

    _, err_response = _require_instance(instance_id)
    if err_response:
        return err_response

    filename = request.args.get('filename', '')
    return _external_download_demo(instance_id, filename, _QLMATCH_SUFFIX)


@external_api_bp.route('/instances/<int:instance_id>/matches/replay', methods=['GET'])
@limiter.limit("200 per minute")
def external_download_instance_match_replay(instance_id):
    """Download the .replay.json.gz sidecar for a recorded match, by name.

    Secured via Bearer token (API key), not JWT cookies.
    """
    ok, err_response = require_api_key()
    if not ok:
        return err_response

    _, err_response = _require_instance(instance_id)
    if err_response:
        return err_response

    filename = request.args.get('filename', '')
    return _external_download_demo(instance_id, filename, _REPLAY_SUFFIX)
