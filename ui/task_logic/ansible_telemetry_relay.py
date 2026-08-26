"""Deploys/configures ql-telemetry-relay on a host via Ansible.

Wires install_telemetry_relay.yml into the qlsm task queue (previously a
manual-only playbook, see its own header + qlsm-becomes-platform-plugin-sot
in project memory) and keeps its config's routes in sync with whichever
instances on the host have a reserved stats-hub server_id.
"""
from flask import current_app
from ui import db
from ui.models import Host, QLInstance
from ui.task_logic.ansible_runner import _run_host_ansible_playbook
from ui.telemetry_relay_settings import (
    get_stats_hub_url,
    get_or_create_relay_local_token,
    get_instance_server_id,
    is_relay_enabled,
    set_relay_enabled,
)

RELAY_LOCAL_URL = 'http://127.0.0.1:8190/api/ingest/telemetry'


def build_relay_routes_for_host(host_id):
    """{"<server_id>": {"telemetry": "<stats-hub>/api/ingest/telemetry", "server_name": ...}}
    for every instance on this host that already has a reserved server_id."""
    stats_hub_url = get_stats_hub_url()
    if not stats_hub_url:
        return {}
    routes = {}
    for instance in QLInstance.query.filter_by(host_id=host_id).all():
        server_id = get_instance_server_id(instance.id)
        if not server_id:
            continue
        routes[str(server_id)] = {
            'telemetry': f'{stats_hub_url}/api/ingest/telemetry',
            'server_name': instance.name,
        }
    return routes


def push_relay_config_logic(host_id):
    """Re-render + push telemetry-relay.json for a host whose relay is
    already enabled (e.g. after a new instance reserved a server_id).
    No-op if the relay isn't enabled on this host."""
    host = db.session.get(Host, host_id)
    if not host:
        current_app.logger.error(f"Host {host_id} not found for telemetry-relay config push.")
        return False
    if not is_relay_enabled(host_id):
        return True

    extra_vars = {
        'telemetry_relay_enabled': True,
        'telemetry_relay_token': get_or_create_relay_local_token(host_id),
        'telemetry_relay_routes': build_relay_routes_for_host(host_id),
    }
    success, _stdout, _stderr = _run_host_ansible_playbook(
        host=host,
        playbook_name='install_telemetry_relay.yml',
        extravars=extra_vars,
    )
    if not success:
        current_app.logger.error(f"Failed to push telemetry-relay config for host {host.name}.")
    return success


def configure_host_telemetry_relay_logic(host_id, enabled):
    """Enables/disables the ql-telemetry-relay sidecar on a host.

    Disabling stops routing new instances through it but deliberately does
    NOT touch already-applied instance cvars (an instance pointed at
    127.0.0.1:8190 with the relay stopped just stops sending, same failure
    mode as any other misconfiguration - avoids this action silently
    rewriting instance config it doesn't own).
    """
    host = db.session.get(Host, host_id)
    if not host:
        current_app.logger.error(f"Host {host_id} not found for telemetry-relay configuration.")
        return False

    current_app.logger.info(
        f"Configuring telemetry relay for host: {host.name} (enabled={enabled})"
    )

    extra_vars = {
        'telemetry_relay_enabled': bool(enabled),
        'telemetry_relay_token': get_or_create_relay_local_token(host_id) if enabled else '',
        'telemetry_relay_routes': build_relay_routes_for_host(host_id) if enabled else {},
    }

    success, stdout_str, stderr_str = _run_host_ansible_playbook(
        host=host,
        playbook_name='install_telemetry_relay.yml',
        extravars=extra_vars,
    )

    if success:
        current_app.logger.info(f"Successfully configured telemetry relay for host {host.name}.")
        set_relay_enabled(host_id, enabled)
        host.logs = f"Telemetry relay {'enabled' if enabled else 'disabled'}.\n{host.logs or ''}"
    else:
        current_app.logger.error(f"Failed to configure telemetry relay for host {host.name}.")
        host.logs = f"Telemetry relay configuration failed.\n{host.logs or ''}"

    db.session.commit()
    return success
