"""Telemetry relay, as an addon.

**Migration state.** This ships *alongside* the built-in telemetry-relay code,
not instead of it: the feature is live in production on host `germany`, so the
core endpoints, tasks and modal stay until this addon has been verified
against a real host. Until then both appear in the UI, the addon's entries
suffixed "(addon)".

Because of that, this backend deliberately **delegates to the existing
`ui.telemetry_relay_settings` and `ui.task_logic.ansible_telemetry_relay`
modules rather than copying their logic.** Two implementations of a
production feature drifting apart is a far worse failure than an addon
importing from core for one release. The physical move of those modules into
this directory happens in the same change that deletes the core endpoints --
see the spec's phase 4.

Note that **no panel here is `managed`** -- every one has its own load/submit
route reading the same AppSetting keys the built-in code reads. That is on
purpose: a managed panel would store the stats-hub URL and ingest token in
AddonState while the shared relay logic kept reading AppSetting, giving a
production credential two sources of truth that silently disagree. One store,
one reader, for as long as both code paths exist.
"""
import uuid

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

bp = Blueprint('telemetry_relay_addon', __name__)


def _host_or_404(host_id):
    from ui.database import get_host

    host = get_host(host_id)
    if not host:
        return None, (jsonify({"error": {"message": "Host not found"}}), 404)
    return host, None


@bp.route('/hosts/<int:host_id>', methods=['GET'], endpoint='get_host_relay')
@jwt_required()
def get_host_relay(host_id):
    """Everything the host panel's form needs, in one round trip."""
    from ui.telemetry_relay_settings import (
        get_host_stats_hub_ingest_token, get_host_stats_hub_url, is_relay_enabled,
    )

    _, error = _host_or_404(host_id)
    if error:
        return error

    return jsonify({"data": {
        'enabled': is_relay_enabled(host_id),
        'url_override': get_host_stats_hub_url(host_id) or '',
        'ingest_token_override': get_host_stats_hub_ingest_token(host_id) or '',
    }})


@bp.route('/hosts/<int:host_id>/status', methods=['GET'], endpoint='get_host_relay_status')
@jwt_required()
def get_host_relay_status(host_id):
    """Live sidecar probe, shaped for the panel's status badge.

    One SSH round trip, so this is a separate endpoint from the form load --
    the panel fetches it once per open rather than on every keystroke.
    """
    from ui.task_logic.ansible_telemetry_relay import get_relay_status_logic

    _, error = _host_or_404(host_id)
    if error:
        return error

    status = get_relay_status_logic(host_id)
    if status is None:
        return jsonify({"error": {"message": "Host not found"}}), 404

    if not status.get('enabled'):
        label = 'Sidecar disabled'
    elif status.get('reachable'):
        routed = len(status.get('routed_instances') or [])
        label = f'Reachable, {routed} instance(s) routed'
    else:
        label = status.get('error') or 'Unreachable'

    return jsonify({"data": {
        'ok': bool(status.get('enabled') and status.get('reachable')),
        'label': label,
        'routed_instances': status.get('routed_instances') or [],
    }})


@bp.route('/hosts/<int:host_id>', methods=['PUT'], endpoint='update_host_relay')
@jwt_required()
def update_host_relay(host_id):
    """Applies the host panel in one submit: overrides first, then the
    enable/disable toggle if it actually changed.

    Order matters. Writing the overrides before flipping the switch means a
    relay being turned on is configured with the values the operator just
    typed, not the previous ones -- the built-in UI got this right by having
    two separate buttons, and collapsing them into one form is exactly where
    it would be easy to get wrong.
    """
    from ui import db
    from ui.database import update_host
    from ui.models import HostStatus
    from ui.task_lock import acquire_lock, release_lock
    from ui.task_logic.ansible_telemetry_relay import push_relay_config_logic
    from ui.task_logic.job_failure_handlers import host_job_failure_handler
    from ui.tasks import configure_host_telemetry_relay_task, enqueue_task
    from ui.telemetry_relay_settings import (
        is_relay_enabled, set_host_stats_hub_ingest_token, set_host_stats_hub_url,
    )

    host, error = _host_or_404(host_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    url = data.get('url_override', '')
    token = data.get('ingest_token_override', '')
    if not isinstance(url, str) or not isinstance(token, str):
        return jsonify({"error": {"message": "url_override and ingest_token_override must be strings."}}), 400
    wanted = bool(data.get('enabled', False))

    set_host_stats_hub_url(host_id, url)
    set_host_stats_hub_ingest_token(host_id, token)
    db.session.commit()

    if wanted == is_relay_enabled(host_id):
        # Nothing to install or remove -- just re-push the config so an edited
        # URL/token reaches a relay that is already running.
        push_relay_config_logic(host_id)
        return jsonify({"data": {"enabled": wanted}, "message": "Relay configuration updated."})

    if host.status != HostStatus.ACTIVE:
        return jsonify({"error": {
            "message": f"Host must be ACTIVE to change the relay. Current state: {host.status.value}"
        }}), 400

    lock_token = str(uuid.uuid4())
    if not acquire_lock('host', host.id, lock_token, ttl=180):
        return jsonify({"error": {
            "message": f'Another operation is running on host "{host.name}". Please wait for it to complete.'
        }}), 409
    try:
        update_host(host.id, status=HostStatus.CONFIGURING)
        enqueue_task(configure_host_telemetry_relay_task, host.id, wanted,
                     lock_token=lock_token, on_failure=host_job_failure_handler)
    except Exception as e:
        release_lock('host', host.id, lock_token)
        current_app.logger.error(f'Addon telemetry-relay: failed to queue host {host_id}: {e}', exc_info=True)
        return jsonify({"error": {"message": "Failed to initiate relay configuration"}}), 500

    return jsonify({
        "data": {"enabled": wanted},
        "message": "Telemetry relay configuration started.",
    }), 202


@bp.route('/stats-hub', methods=['GET'], endpoint='get_stats_hub')
@jwt_required()
def get_stats_hub():
    from ui.telemetry_relay_settings import get_stats_hub_ingest_token, get_stats_hub_url

    return jsonify({"data": {
        'url': get_stats_hub_url() or '',
        'ingest_token': get_stats_hub_ingest_token() or '',
    }})


@bp.route('/stats-hub', methods=['PUT'], endpoint='update_stats_hub')
@jwt_required()
def update_stats_hub():
    """Cluster-wide stats-hub target. Same AppSetting keys the built-in
    Settings page writes, so the two cannot disagree while both exist."""
    from ui import db
    from ui.telemetry_relay_settings import set_stats_hub_ingest_token, set_stats_hub_url

    data = request.get_json(silent=True) or {}
    url = data.get('url', '')
    token = data.get('ingest_token', '')
    if not isinstance(url, str) or not isinstance(token, str):
        return jsonify({"error": {"message": "url and ingest_token must be strings."}}), 400

    set_stats_hub_url(url)
    set_stats_hub_ingest_token(token)
    db.session.commit()
    return jsonify({"data": {'url': url.strip().rstrip('/'), 'ingest_token': token.strip()}})


@bp.route('/instances/<int:instance_id>', methods=['GET'], endpoint='get_instance_telemetry')
@jwt_required()
def get_instance_telemetry(instance_id):
    from ui.database import get_instance
    from ui.telemetry_relay_settings import get_instance_server_id

    instance = get_instance(instance_id)
    if not instance:
        return jsonify({"error": {"message": "Instance not found."}}), 404
    return jsonify({"data": {"server_id": get_instance_server_id(instance.id) or 0}})


@bp.route('/instances/<int:instance_id>/enable', methods=['POST', 'PUT'], endpoint='enable_instance_telemetry')
@jwt_required()
def enable_instance_telemetry(instance_id):
    """Reserve a server ID and wire the instance's cvars at the host relay.

    Refuses early with a readable reason rather than queueing a task that
    would fail on the host: the relay must already be on, since the instance
    points its cvars at a sidecar that has to exist.
    """
    from ui.database import get_instance, update_instance
    from ui.models import InstanceStatus
    from ui.task_lock import acquire_lock, release_lock
    from ui.task_logic.job_failure_handlers import instance_job_failure_handler
    from ui.tasks import enable_instance_telemetry_task, enqueue_task
    from ui.telemetry_relay_settings import is_relay_enabled, is_stats_hub_configured_for_host

    instance = get_instance(instance_id)
    if not instance:
        return jsonify({"error": {"message": "Instance not found."}}), 404
    if not instance.host:
        return jsonify({"error": {"message": "Instance has no associated host."}}), 400

    if not is_relay_enabled(instance.host_id):
        return jsonify({"error": {
            "message": "Enable the telemetry relay on this instance's host first."
        }}), 409
    if not is_stats_hub_configured_for_host(instance.host_id):
        return jsonify({"error": {
            "message": "Set the stats-hub URL and ingest token (globally or on this host) first."
        }}), 409

    busy = [InstanceStatus.DEPLOYING, InstanceStatus.CONFIGURING, InstanceStatus.RESTARTING,
            InstanceStatus.DELETING, InstanceStatus.STOPPING, InstanceStatus.STARTING]
    if instance.status in busy:
        return jsonify({"error": {
            "message": f'Instance "{instance.name}" is busy ({instance.status.value}). Try again shortly.'
        }}), 409

    lock_token = str(uuid.uuid4())
    if not acquire_lock('instance', instance.id, lock_token, ttl=180):
        return jsonify({"error": {
            "message": f'Another operation is running on instance "{instance.name}".'
        }}), 409
    try:
        update_instance(instance.id, status=InstanceStatus.CONFIGURING)
        enqueue_task(enable_instance_telemetry_task, instance.id,
                     lock_token=lock_token, on_failure=instance_job_failure_handler)
    except Exception as e:
        release_lock('instance', instance.id, lock_token)
        current_app.logger.error(f'Addon telemetry-relay: failed to queue instance {instance_id}: {e}',
                                 exc_info=True)
        return jsonify({"error": {"message": "Failed to queue telemetry enable."}}), 500

    return jsonify({"message": f'Telemetry enable queued for "{instance.name}".'}), 202


def register(ctx):
    ctx.blueprint(bp)

    @ctx.on('host.delete')
    def forget_host(host_id):
        """Drop this host's relay settings when the host goes away.

        Core clears the addon's own AddonState rows; these are the legacy
        AppSetting keys the shared logic still reads, which nothing else
        would clean up.
        """
        from ui.telemetry_relay_settings import (
            set_host_stats_hub_ingest_token, set_host_stats_hub_url, set_relay_enabled,
        )
        set_relay_enabled(host_id, False)
        set_host_stats_hub_url(host_id, '')
        set_host_stats_hub_ingest_token(host_id, '')

    @ctx.on('instance.delete')
    def forget_instance(instance_id):
        from ui.telemetry_relay_settings import set_instance_server_id
        set_instance_server_id(instance_id, None)
