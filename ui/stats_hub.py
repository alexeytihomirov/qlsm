"""Shared ql-stats-hub integration: where it is, and per-instance server IDs.

Split out of the old per-feature settings module when telemetry-relay moved
into an addon. The split line is deliberate:

* **Here (core):** where ql-stats-hub is (cluster URL + ingest token, and a
  per-host override of both), the cluster-wide server ID reserved for each
  instance, and the server.cfg cvar helpers. Two different features already
  depend on all of it -- the telemetry-relay addon and the live demo stream --
  so it is shared infrastructure, not one feature's private state.
* **In the addon:** whether the relay *sidecar* is installed and running on a
  given host. That is the telemetry-relay feature and nothing else uses it.

Putting the shared half in an addon would mean uninstalling telemetry-relay
silently breaks the demo stream, which is exactly the kind of coupling the
addon system exists to prevent.

State lives in the generic AppSetting key/value table, as it always has.
"""
import re

import requests

from ui import db
from ui.models import AppSetting

STATS_HUB_URL_SETTING = 'stats_hub_url'
STATS_HUB_INGEST_TOKEN_SETTING = 'stats_hub_ingest_token'
_HOST_STATS_HUB_URL_PREFIX = 'telemetry_relay_host_stats_hub_url:'
_HOST_STATS_HUB_TOKEN_PREFIX = 'telemetry_relay_host_stats_hub_token:'
_INSTANCE_SERVER_ID_PREFIX = 'stats_hub_server_id:'

# The two `telemetry_relay_host_*` prefixes are kept verbatim from before the
# split, despite no longer being telemetry's alone: they name rows that
# already exist in every deployed database, and renaming them would silently
# orphan a live host's override.

RESERVE_TIMEOUT_SEC = 10


def _get(key):
    row = AppSetting.query.get(key)
    return row.value.strip() if row and row.value and row.value.strip() else None


def _set(key, value):
    """Create/update/clear a setting. Does not commit."""
    value = (value or '').strip()
    row = AppSetting.query.get(key)
    if not value:
        if row:
            db.session.delete(row)
        return
    if row:
        row.value = value
    else:
        db.session.add(AppSetting(key=key, value=value))


# ---- cluster-wide target ----------------------------------------------

def get_stats_hub_url():
    return _get(STATS_HUB_URL_SETTING)


def set_stats_hub_url(value):
    _set(STATS_HUB_URL_SETTING, (value or '').strip().rstrip('/'))


def get_stats_hub_ingest_token():
    return _get(STATS_HUB_INGEST_TOKEN_SETTING)


def set_stats_hub_ingest_token(value):
    _set(STATS_HUB_INGEST_TOKEN_SETTING, value)


def is_stats_hub_configured():
    return bool(get_stats_hub_url() and get_stats_hub_ingest_token())


# ---- per-host override -------------------------------------------------

def get_host_stats_hub_url(host_id):
    """This host's stats-hub URL override, or None if it inherits the global one."""
    return _get(f'{_HOST_STATS_HUB_URL_PREFIX}{host_id}')


def set_host_stats_hub_url(host_id, value):
    _set(f'{_HOST_STATS_HUB_URL_PREFIX}{host_id}', (value or '').strip().rstrip('/'))


def get_host_stats_hub_ingest_token(host_id):
    """This host's ingest-token override, or None if it inherits the global one."""
    return _get(f'{_HOST_STATS_HUB_TOKEN_PREFIX}{host_id}')


def set_host_stats_hub_ingest_token(host_id, value):
    _set(f'{_HOST_STATS_HUB_TOKEN_PREFIX}{host_id}', value)


def get_effective_stats_hub_url(host_id):
    """This host's override if set, else the global default."""
    return get_host_stats_hub_url(host_id) or get_stats_hub_url()


def get_effective_stats_hub_ingest_token(host_id):
    """This host's override if set, else the global default."""
    return get_host_stats_hub_ingest_token(host_id) or get_stats_hub_ingest_token()


def is_stats_hub_configured_for_host(host_id):
    return bool(get_effective_stats_hub_url(host_id) and get_effective_stats_hub_ingest_token(host_id))


# ---- per-instance server id --------------------------------------------

def get_instance_server_id(instance_id):
    value = _get(f'{_INSTANCE_SERVER_ID_PREFIX}{instance_id}')
    return int(value) if value else None


def set_instance_server_id(instance_id, server_id):
    _set(f'{_INSTANCE_SERVER_ID_PREFIX}{instance_id}', str(int(server_id)) if server_id else None)


def reserve_server_id(label, host_id):
    """Reserve a cluster-wide server ID from ql-stats-hub.

    Shared by telemetry and the demo stream: both need the instance to be
    identifiable to stats-hub by the same number, and reserving twice would
    hand out two IDs for one server.
    """
    url = f"{get_effective_stats_hub_url(host_id)}/api/admin/server-ids/reserve"
    headers = {'Authorization': f'Bearer {get_effective_stats_hub_ingest_token(host_id)}'}
    resp = requests.post(url, json={'label': label}, headers=headers, timeout=RESERVE_TIMEOUT_SEC)
    resp.raise_for_status()
    return int(resp.json()['server_id'])


# ---- server.cfg cvar helpers -------------------------------------------

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
