"""Reference addon backend.

Shows the three things an addon's backend can do -- serve its own endpoints,
register a background task, and hook into core's lifecycle -- with no real
side effects. Read alongside qlsm-addon.json, which declares the UI that
calls into these endpoints.

Everything an addon is allowed to touch arrives through `ctx`; see
ui/addons/context.py.
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

bp = Blueprint('hello_addon', __name__)

# Static stand-in for whatever an addon would really list (remote demo files,
# uploads, jobs). Shaped to match the `files_table` panel in the manifest.
_FILES = [
    {"name": "2026-09-14_duel_aerowalk.dm_91", "size": 4_718_592, "mtime": 1_757_800_000},
    {"name": "2026-09-13_ca_toxicity.dm_91", "size": 12_058_624, "mtime": 1_757_700_000},
]


@bp.route('/status', methods=['GET'])
@jwt_required()
def status():
    """Feeds the `status` badge on the host form panel."""
    return jsonify({"data": {"ok": True, "label": "Reachable"}})


@bp.route('/files', methods=['GET'])
@jwt_required()
def list_files():
    """Feeds the `table` panels. `instance_id` arrives from {instance_id}."""
    instance_id = request.args.get('instance_id')
    return jsonify({"data": {"files": _FILES, "instance_id": instance_id}})


@bp.route('/files/download', methods=['GET'])
@jwt_required()
def download_file():
    """A row action. Returning a `url` is what makes the panel open it."""
    filename = request.args.get('filename', '')
    return jsonify({"data": {"url": None, "filename": filename}})


@bp.route('/files/download-batch', methods=['POST'])
@jwt_required()
def download_batch():
    """A bulk action. The panel posts {"selected": [row_key, ...]}."""
    selected = (request.get_json(silent=True) or {}).get('selected') or []
    return jsonify({"data": {"url": None, "count": len(selected)}})


def register(ctx):
    ctx.blueprint(bp)

    @ctx.task(timeout=60, lock_scope='host')
    def hello_host_task(host_id):
        """Core wraps this with app context + lock release, so this body does
        not have to remember either."""
        ctx.logger.info('hello-addon task ran for host %s', host_id)
        return True

    @ctx.on('instance.launch_args')
    def launch_args(instance_id):
        """Only called when the addon is effectively enabled for this instance
        -- the registry checks the three-layer rule before dispatching."""
        settings = ctx.settings.get('instance', instance_id)
        server_id = settings.get('server_id') or 0
        if not server_id:
            return []
        return [f'+set qlx_helloAddonServerId {server_id}']
