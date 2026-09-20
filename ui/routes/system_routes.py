"""Process-level operations on qlsm itself, as opposed to the servers it manages.

Today that is one thing: asking the stack to restart so newly installed addons
actually load. Flask cannot hot-add a blueprint, so an addon installed at
runtime stays inert until create_app() runs again.

The mechanism is deliberately dumb: this endpoint only updates the mtime of a
stamp file on the ./data mount that every app container shares. restart-watcher.sh
(started by entrypoint.sh in web/worker/poller) notices and signals its own PID 1.
No control channel, no subscriber code in any service, no docker.sock -- the web
container must not have one (see addons/TRUST.md).
"""
import os

from flask import Blueprint, current_app, jsonify
from flask_jwt_extended import jwt_required

system_api_bp = Blueprint('system_routes', __name__)

# Not every deployment can survive having its processes killed. Under Docker
# the restart policy brings them back; under run-dev.sh nothing does, and a
# restart would simply end qlsm. entrypoint.sh is the only place that sets
# this, and only for services it starts a watcher for, so its presence is an
# exact answer rather than a guess about /.dockerenv or PID 1.
_SUPERVISED_ENV = 'QLSM_SUPERVISED'

_UNSUPPORTED_MESSAGE = (
    'This qlsm is not running under a process supervisor, so a restart would '
    'stop it for good instead of bringing it back. Restart it the way you '
    'started it (for a dev run: stop run-dev.sh and start it again).'
)


def restart_supported():
    """True when killing our own process is safe because something restarts it."""
    return os.environ.get(_SUPERVISED_ENV) == '1'


def _stamp_path():
    return current_app.config.get('RESTART_STAMP_FILE') or '/app/data/.restart-stamp'


@system_api_bp.route('/info', methods=['GET'])
@jwt_required()
def system_info_api():
    """What the UI needs to decide whether to offer a restart at all."""
    return jsonify({"data": {"restart_supported": restart_supported()}}), 200


@system_api_bp.route('/restart', methods=['POST'])
@jwt_required()
def restart_system_api():
    """Ask every qlsm app process to come back on freshly loaded code."""
    if not restart_supported():
        return jsonify({"error": {"message": _UNSUPPORTED_MESSAGE}}), 409

    path = _stamp_path()
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        # Truncating is fine: only the mtime carries meaning, and an empty file
        # keeps `touch data/.restart-stamp` on the host equivalent to this call.
        with open(path, 'w'):
            pass
        os.utime(path, None)
    except OSError as exc:
        current_app.logger.error('Restart request could not write %s: %s', path, exc)
        return jsonify({"error": {
            "message": f'Could not request a restart: {exc}',
        }}), 500

    current_app.logger.warning('Restart requested via API — stamped %s', path)
    return jsonify({
        "data": {"stamped": True},
        "message": 'Restart requested. qlsm will be back shortly.',
    }), 202
