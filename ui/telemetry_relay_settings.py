"""DB-backed settings for the telemetry-relay feature.

Mirrors ui/vultr_settings.py's pattern (generic AppSetting key/value table,
no dedicated columns/migration needed - see qlsm-migrations-branched-heads
in project memory for why a new column was avoided here).

Three kinds of state, all in AppSetting:
- Global: real ql-stats-hub base URL + its STATS_HUB_INGEST_TOKEN. One
  cluster-wide target, same value used by every host's relay and by the
  server-id reservation call (the operator confirmed a single stats-hub
  for all VPS today).
- Per host (key suffixed `:<host_id>`): whether the local relay is
  installed+enabled, and the local secret its config's "token" field uses
  (relay.py doesn't actually verify inbound Authorization - see relay.py
  do_POST - but every instance's qlx_statsHubToken cvar still needs some
  value to sit in, so this keeps that value out of the real ingest token).
- Per instance (key suffixed `:<instance_id>`): the cluster-wide
  qlx_statsHubServerId reserved for it via ql-stats-hub's
  /api/admin/server-ids/reserve (see stats_hub_server_id_registry.py).
"""
import secrets

from ui import db
from ui.models import AppSetting

STATS_HUB_URL_SETTING = 'stats_hub_url'
STATS_HUB_INGEST_TOKEN_SETTING = 'stats_hub_ingest_token'
_RELAY_ENABLED_PREFIX = 'telemetry_relay_enabled:'
_RELAY_LOCAL_TOKEN_PREFIX = 'telemetry_relay_local_token:'
_INSTANCE_SERVER_ID_PREFIX = 'stats_hub_server_id:'


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


def is_relay_enabled(host_id):
    return _get(f'{_RELAY_ENABLED_PREFIX}{host_id}') == '1'


def set_relay_enabled(host_id, enabled):
    _set(f'{_RELAY_ENABLED_PREFIX}{host_id}', '1' if enabled else '')


def get_or_create_relay_local_token(host_id):
    """Local secret carried in qlx_statsHubToken + telemetry-relay.json's
    "token" field for this host. Not a real security boundary (relay.py
    only listens on 127.0.0.1 and doesn't check it today) - just keeps a
    stable, non-guessable placeholder instead of a literal "local"."""
    key = f'{_RELAY_LOCAL_TOKEN_PREFIX}{host_id}'
    existing = _get(key)
    if existing:
        return existing
    token = secrets.token_urlsafe(24)
    _set(key, token)
    return token


def get_instance_server_id(instance_id):
    value = _get(f'{_INSTANCE_SERVER_ID_PREFIX}{instance_id}')
    return int(value) if value else None


def set_instance_server_id(instance_id, server_id):
    _set(f'{_INSTANCE_SERVER_ID_PREFIX}{instance_id}', str(int(server_id)) if server_id else None)
