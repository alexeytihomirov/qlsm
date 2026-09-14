"""DB-backed settings for the live demo stream feature (sv_demoStream).

Mirrors ui/telemetry_relay_settings.py's pattern (generic AppSetting
key/value table, no dedicated columns/migration - see
qlsm-migrations-branched-heads in project memory for why a new column is
avoided here).

Two kinds of state, all in AppSetting:
- Global: the central relay's TCP ingest address (host:port) every QLDS
  instance's sv_demoStreamHost/sv_demoStreamPort point at - see
  ql-stats-hub's "Live demo stream" contour (STATS_HUB_DEMO_STREAM_TCP_HOST/
  PORT on that side). This is one address for the whole cluster, not
  per-host like the telemetry relay sidecar (that one's a local process on
  each game host; this one has nothing local to install).
- Per instance (key suffixed `:<instance_id>`): whether sv_demoStream is
  wired into this instance's server.cfg, and the per-instance secret token
  generated once and registered with stats-hub's
  POST /api/demo-stream/routes so the relay can attribute this instance's
  connection to the right server_id/name.
"""
from ui import db
from ui.models import AppSetting

RELAY_HOST_SETTING = 'demo_stream_relay_host'
RELAY_PORT_SETTING = 'demo_stream_relay_port'
_ENABLED_PREFIX = 'demo_stream_enabled:'
_TOKEN_PREFIX = 'demo_stream_token:'


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


def get_relay_host():
    return _get(RELAY_HOST_SETTING)


def set_relay_host(value):
    _set(RELAY_HOST_SETTING, value)


def get_relay_port():
    return _get(RELAY_PORT_SETTING)


def set_relay_port(value):
    _set(RELAY_PORT_SETTING, value)


def is_relay_configured():
    return bool(get_relay_host() and get_relay_port())


def is_instance_demo_stream_enabled(instance_id):
    return _get(f'{_ENABLED_PREFIX}{instance_id}') == '1'


def set_instance_demo_stream_enabled(instance_id, enabled):
    _set(f'{_ENABLED_PREFIX}{instance_id}', '1' if enabled else '')


def get_instance_demo_stream_token(instance_id):
    return _get(f'{_TOKEN_PREFIX}{instance_id}')


def set_instance_demo_stream_token(instance_id, token):
    _set(f'{_TOKEN_PREFIX}{instance_id}', token)
