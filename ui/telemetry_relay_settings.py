"""DB-backed settings for the telemetry-relay feature.

Mirrors ui/vultr_settings.py's pattern (generic AppSetting key/value table,
no dedicated columns/migration needed - see qlsm-migrations-branched-heads
in project memory for why a new column was avoided here).

Three kinds of state, all in AppSetting:
- Global: real ql-stats-hub base URL + its STATS_HUB_INGEST_TOKEN. The
  cluster-wide default target, used by every host's relay and by the
  server-id reservation call unless a host overrides it below.
- Per host (key suffixed `:<host_id>`): whether the local relay is
  installed+enabled, and an optional override of the stats-hub URL/ingest
  token for that host only (multi-stats-hub setups, or a host that needs
  to point somewhere other than the cluster default). The relay forwards
  every POST it accepts upstream using this host's *effective* ingest
  token (override if set, else the global one) as the real
  `Authorization: Bearer` credential - relay.py does not validate the
  inbound Authorization header at all (see relay.py do_POST), so this
  token only matters for the outbound hop to stats-hub.
- Per instance (key suffixed `:<instance_id>`): the cluster-wide
  qlx_statsHubServerId reserved for it via ql-stats-hub's
  /api/admin/server-ids/reserve (see stats_hub_server_id_registry.py).
"""
from ui import db
from ui.models import AppSetting

STATS_HUB_URL_SETTING = 'stats_hub_url'
STATS_HUB_INGEST_TOKEN_SETTING = 'stats_hub_ingest_token'
_RELAY_ENABLED_PREFIX = 'telemetry_relay_enabled:'
_HOST_STATS_HUB_URL_PREFIX = 'telemetry_relay_host_stats_hub_url:'
_HOST_STATS_HUB_TOKEN_PREFIX = 'telemetry_relay_host_stats_hub_token:'
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


def get_instance_server_id(instance_id):
    value = _get(f'{_INSTANCE_SERVER_ID_PREFIX}{instance_id}')
    return int(value) if value else None


def set_instance_server_id(instance_id, server_id):
    _set(f'{_INSTANCE_SERVER_ID_PREFIX}{instance_id}', str(int(server_id)) if server_id else None)
