"""Enables telemetry-relay wiring for a single QL instance:
reserve a cluster-wide server_id from ql-stats-hub, point the instance's
qlx_statsHub* cvars at the host's local relay, push the host's relay
routes, and apply+restart the instance (same mechanism the Plugins tab
config-save flow already uses)."""
import os
import re

import requests
from flask import current_app

from ui import db
from ui.models import QLInstance
from ui.task_logic.ansible_telemetry_relay import RELAY_LOCAL_URL, push_relay_config_logic
from ui.telemetry_relay_settings import (
    get_stats_hub_ingest_token,
    get_stats_hub_url,
    get_or_create_relay_local_token,
    get_instance_server_id,
    is_relay_enabled,
    is_stats_hub_configured,
    set_instance_server_id,
)

_RESERVE_TIMEOUT_SEC = 10


def _reserve_server_id(label):
    url = f"{get_stats_hub_url()}/api/admin/server-ids/reserve"
    headers = {'Authorization': f'Bearer {get_stats_hub_ingest_token()}'}
    resp = requests.post(url, json={'label': label}, headers=headers, timeout=_RESERVE_TIMEOUT_SEC)
    resp.raise_for_status()
    return int(resp.json()['server_id'])


def upsert_cvars_in_text(text, cvars):
    """Replace/append `set <cvar> "value"` lines in raw server.cfg text.

    Only touches the given cvar names - every other line (including cvars
    the operator set by hand through the Plugins tab) is left alone.
    """
    lines = text.splitlines()
    remaining = dict(cvars)
    out = []
    for line in lines:
        m = re.match(r'^(\s*set\s+)([A-Za-z0-9_]+)(\s+)"(.*)"(\s*)$', line)
        if m and m.group(2) in remaining:
            value = remaining.pop(m.group(2))
            out.append(f'{m.group(1)}{m.group(2)}{m.group(3)}"{value}"{m.group(5)}')
        else:
            out.append(line)
    for cvar, value in remaining.items():
        out.append(f'set {cvar} "{value}"')
    return '\n'.join(out) + '\n'


def _finish(instance, ok, message):
    if instance is not None:
        instance.logs = f"{message}\n{instance.logs or ''}"
        db.session.commit()
    return ok, message


def enable_instance_telemetry_logic(instance_id):
    """Returns (ok: bool, message: str)."""
    instance = db.session.get(QLInstance, instance_id)
    if not instance or not instance.host:
        return False, "Instance or associated host not found."

    if not is_stats_hub_configured():
        return _finish(instance, False, "Configure the stats-hub URL/ingest token in Settings first.")
    if not is_relay_enabled(instance.host_id):
        return _finish(instance, False, "Enable the telemetry relay for this host first.")

    server_id = get_instance_server_id(instance.id)
    if server_id is None:
        try:
            server_id = _reserve_server_id(instance.name)
        except (requests.RequestException, ValueError, KeyError) as exc:
            current_app.logger.error(
                f"Failed to reserve stats-hub server_id for instance {instance.id}: {exc}"
            )
            return _finish(instance, False, f"Could not reserve a server_id from stats-hub: {exc}")
        set_instance_server_id(instance.id, server_id)
        db.session.commit()

    config_path = os.path.join('configs', instance.host.name, str(instance.id), 'server.cfg')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        text = ''

    text = upsert_cvars_in_text(text, {
        'qlx_statsHubUnifiedEnabled': '1',
        'qlx_statsHubUrl': RELAY_LOCAL_URL,
        'qlx_statsHubToken': get_or_create_relay_local_token(instance.host_id),
        'qlx_statsHubServerId': str(server_id),
    })
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)

    if not push_relay_config_logic(instance.host_id):
        return _finish(instance, False, (
            f"server_id {server_id} reserved and server.cfg updated, but pushing the "
            "relay's routes to the host failed - re-run once the host is reachable."
        ))

    from ui.tasks import apply_instance_config, enqueue_task
    from ui.task_logic.job_failure_handlers import instance_job_failure_handler

    job = enqueue_task(
        apply_instance_config,
        instance.id,
        restart=True,
        on_failure=instance_job_failure_handler,
    )
    if not job:
        return _finish(
            instance, False, f"server_id {server_id} reserved, but queuing the config apply/restart failed."
        )

    return _finish(
        instance, True,
        f"Telemetry enabled, server_id={server_id}. Applying config and restarting (job {job.id}).",
    )
