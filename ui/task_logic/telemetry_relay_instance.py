"""Enables telemetry-relay wiring for a single QL instance:
reserve a cluster-wide server_id from ql-stats-hub, flip
qlx_statsHubUnifiedEnabled on, push the host's relay routes, and apply+
restart the instance (same mechanism the Plugins tab config-save flow
already uses).

The instance itself never stores or sends the stats-hub URL/ingest token -
those live only in per-host settings (ui/telemetry_relay_settings.py) and
are read by the relay sidecar and by _reserve_server_id below. The
stream_telemetry_unified plugin talks to a fixed local relay address
(see ansible_telemetry_relay.RELAY_LOCAL_URL) hardcoded in its own
qlx_statsHubUrl default - not per-instance data, so there is nothing left
to write into server.cfg for it.
"""
import os
import re

import requests
from flask import current_app

from ui import db
from ui.models import QLInstance
from ui.task_logic.ansible_telemetry_relay import push_relay_config_logic
from ui.telemetry_relay_settings import (
    get_effective_stats_hub_ingest_token,
    get_effective_stats_hub_url,
    get_instance_server_id,
    is_relay_enabled,
    is_stats_hub_configured_for_host,
    set_instance_server_id,
)

_RESERVE_TIMEOUT_SEC = 10
# Cvars the instance-level plugin used to have written into its server.cfg
# directly (stats-hub URL / ingest token). Now host-only - stripped from any
# server.cfg still carrying them from before this change so the file doesn't
# keep advertising stale/duplicated secrets.
_LEGACY_INSTANCE_CVARS = ('qlx_statsHubUrl', 'qlx_statsHubToken')


def _reserve_server_id(label, host_id):
    url = f"{get_effective_stats_hub_url(host_id)}/api/admin/server-ids/reserve"
    headers = {'Authorization': f'Bearer {get_effective_stats_hub_ingest_token(host_id)}'}
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


def strip_cvars_from_text(text, cvar_names):
    """Removes `set <cvar> ...` lines for the given cvar names entirely
    (as opposed to upsert_cvars_in_text, which sets a value) - used to clean
    up cvars a server.cfg should no longer carry at all."""
    names = set(cvar_names)
    out = []
    for line in text.splitlines():
        m = re.match(r'^\s*set\s+([A-Za-z0-9_]+)\s+"', line)
        if m and m.group(1) in names:
            continue
        out.append(line)
    return '\n'.join(out) + ('\n' if out else '')


def read_cvars_from_text(text, cvar_names):
    """Returns {name: value} for whichever of `cvar_names` appear as
    `set <name> "value"` lines. Last occurrence wins, matching how the
    engine execs a cfg top to bottom."""
    names = set(cvar_names)
    found = {}
    for line in text.splitlines():
        m = re.match(r'^\s*set\s+([A-Za-z0-9_]+)\s+"(.*)"\s*$', line)
        if m and m.group(1) in names:
            found[m.group(1)] = m.group(2)
    return found


def sync_instance_server_id_from_config(instance):
    """Keeps this instance's telemetry-relay routing entry
    (`stats_hub_server_id:<instance_id>`, see telemetry_relay_settings.py)
    in sync with whatever qlx_statsHubServerId/qlx_statsHubUnifiedEnabled
    its server.cfg actually carries on disk.

    Without this, an operator who wires telemetry purely through the
    Plugins-tab cvar editor (set qlx_statsHubUnifiedEnabled + qlx_statsHubServerId
    by hand, never calling enable_instance_telemetry_logic /
    POST .../telemetry) ends up with a server.cfg that looks fully
    configured while the relay's routing table stays empty on this host -
    every POST is silently dropped as "no_route" even though the relay
    sidecar, its stats-hub URL/token, and the plugin cvars are all
    individually correct. Real incident, see
    qlsm-telemetry-relay-server-id-db-desync in project memory. Call from
    apply_instance_config_logic after every successful config apply, so any
    path that ends up writing server.cfg (raw editor, Plugins tab, or the
    assisted enable_instance_telemetry_logic flow itself) keeps this in
    sync automatically, in whatever order the operator did the setup steps.
    """
    if not instance.host:
        return
    config_path = os.path.join('configs', instance.host.name, str(instance.id), 'server.cfg')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        return

    cvars = read_cvars_from_text(text, ('qlx_statsHubUnifiedEnabled', 'qlx_statsHubServerId'))
    enabled = cvars.get('qlx_statsHubUnifiedEnabled') == '1'
    try:
        server_id = int(cvars.get('qlx_statsHubServerId') or 0)
    except ValueError:
        server_id = 0

    effective_id = server_id if (enabled and server_id > 0) else None
    if get_instance_server_id(instance.id) == effective_id:
        return  # already in sync, don't push relay config for nothing

    set_instance_server_id(instance.id, effective_id)
    db.session.commit()
    push_relay_config_logic(instance.host_id)


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

    host_id = instance.host_id
    if not is_stats_hub_configured_for_host(host_id):
        return _finish(instance, False, "Configure the stats-hub URL/ingest token (globally or for this host) in Settings first.")
    if not is_relay_enabled(host_id):
        return _finish(instance, False, "Enable the telemetry relay for this host first.")

    server_id = get_instance_server_id(instance.id)
    if server_id is None:
        try:
            server_id = _reserve_server_id(instance.name, host_id)
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

    text = strip_cvars_from_text(text, _LEGACY_INSTANCE_CVARS)
    text = upsert_cvars_in_text(text, {
        'qlx_statsHubUnifiedEnabled': '1',
        'qlx_statsHubServerId': str(server_id),
    })
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)

    if not push_relay_config_logic(host_id):
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
