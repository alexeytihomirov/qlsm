"""Shared ql-stats-hub *mechanics*: where a feature's target is stored, how a
per-instance server ID is reserved, and the server.cfg cvar helpers every
feature that talks to stats-hub needs.

Split out of the old per-feature settings module when telemetry-relay moved
into an addon. What stays here is **generic code**, not a shared config
value: telemetry and the live demo stream each get their own independent
stats-hub URL/token/server-id, because they may legitimately point at
*different* stats-hub instances (a relay sidecar forwarding to one cluster,
a demo stream registering routes with another). Every stateful function below
takes a `feature` argument for exactly that reason - `'telemetry'` and
`'demo_stream'` are the two in use, each with its own AppSetting keys, so
that a per-host override entered on one feature's panel can never silently
change what the other one targets. (It used to be able to: before this
split, a URL/token typed into the telemetry-relay host modal also became the
demo stream's route-registration target for that host, invisibly, since both
read the same per-host key.)

The cvar helpers (`upsert_cvars_in_text` and friends) are pure text
operations with no feature-specific state, so they stay ungrouped.

Putting this in an addon would mean uninstalling one addon could delete the
other's stats-hub configuration outright. Keeping it in core, with each
feature's data under its own keys, avoids both failure modes at once.

State lives in the generic AppSetting key/value table, as it always has.
"""
import re

import requests

from ui import db
from ui.models import AppSetting

# Telemetry keeps the exact key names it has used since before this module
# existed - renaming them would orphan every deployed database's current
# telemetry settings. demo_stream is new and gets its own namespaced keys, so
# the two can never collide or alias each other.
_FEATURE_KEYS = {
    'telemetry': {
        'url': 'stats_hub_url',
        'token': 'stats_hub_ingest_token',
        'host_url_prefix': 'telemetry_relay_host_stats_hub_url:',
        'host_token_prefix': 'telemetry_relay_host_stats_hub_token:',
        'server_id_prefix': 'stats_hub_server_id:',
    },
    'demo_stream': {
        'url': 'demo_stream_stats_hub_url',
        'token': 'demo_stream_stats_hub_ingest_token',
        'host_url_prefix': 'demo_stream_host_stats_hub_url:',
        'host_token_prefix': 'demo_stream_host_stats_hub_token:',
        'server_id_prefix': 'demo_stream_stats_hub_server_id:',
    },
}

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


def _keys(feature):
    try:
        return _FEATURE_KEYS[feature]
    except KeyError:
        raise ValueError(f"Unknown stats-hub feature: {feature!r}") from None


# ---- cluster-wide target ----------------------------------------------

def get_stats_hub_url(feature):
    return _get(_keys(feature)['url'])


def set_stats_hub_url(feature, value):
    _set(_keys(feature)['url'], (value or '').strip().rstrip('/'))


def get_stats_hub_ingest_token(feature):
    return _get(_keys(feature)['token'])


def set_stats_hub_ingest_token(feature, value):
    _set(_keys(feature)['token'], value)


def is_stats_hub_configured(feature):
    return bool(get_stats_hub_url(feature) and get_stats_hub_ingest_token(feature))


# ---- per-host override -------------------------------------------------

def get_host_stats_hub_url(feature, host_id):
    """This host's stats-hub URL override for `feature`, or None if it
    inherits the feature's global default."""
    return _get(f"{_keys(feature)['host_url_prefix']}{host_id}")


def set_host_stats_hub_url(feature, host_id, value):
    _set(f"{_keys(feature)['host_url_prefix']}{host_id}", (value or '').strip().rstrip('/'))


def get_host_stats_hub_ingest_token(feature, host_id):
    """This host's ingest-token override for `feature`, or None if it
    inherits the feature's global default."""
    return _get(f"{_keys(feature)['host_token_prefix']}{host_id}")


def set_host_stats_hub_ingest_token(feature, host_id, value):
    _set(f"{_keys(feature)['host_token_prefix']}{host_id}", value)


def get_effective_stats_hub_url(feature, host_id):
    """This host's override if set, else the feature's global default."""
    return get_host_stats_hub_url(feature, host_id) or get_stats_hub_url(feature)


def get_effective_stats_hub_ingest_token(feature, host_id):
    """This host's override if set, else the feature's global default."""
    return get_host_stats_hub_ingest_token(feature, host_id) or get_stats_hub_ingest_token(feature)


def is_stats_hub_configured_for_host(feature, host_id):
    return bool(get_effective_stats_hub_url(feature, host_id)
                and get_effective_stats_hub_ingest_token(feature, host_id))


# ---- per-instance server id --------------------------------------------

def get_instance_server_id(feature, instance_id):
    value = _get(f"{_keys(feature)['server_id_prefix']}{instance_id}")
    return int(value) if value else None


def set_instance_server_id(feature, instance_id, server_id):
    _set(f"{_keys(feature)['server_id_prefix']}{instance_id}",
         str(int(server_id)) if server_id else None)


def reserve_server_id(feature, label, host_id):
    """Reserve a stats-hub server ID for `feature`'s target on this host.

    Telemetry and the demo stream reserve independently now: they may not
    even be the same stats-hub cluster, so there is no single "the" ID to
    share between them the way there was before this split.
    """
    url = f"{get_effective_stats_hub_url(feature, host_id)}/api/admin/server-ids/reserve"
    headers = {'Authorization': f'Bearer {get_effective_stats_hub_ingest_token(feature, host_id)}'}
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
