"""Telemetry-relay's own state: is the sidecar on, for this host.

Everything about *where* ql-stats-hub is -- the cluster URL and ingest token,
the per-host override of both, and the per-instance server ID -- deliberately
stayed in core as ui/stats_hub.py when this feature moved into an addon. Two
features depend on it (telemetry and the live demo stream), so uninstalling
this addon must not take the demo stream with it.

What is left here is the one thing only telemetry-relay cares about: whether
the ql-telemetry-relay sidecar is installed and enabled on a given host.

State lives in the generic AppSetting key/value table under the same key
prefix it has always used -- renaming it would orphan every deployed host's
current setting.
"""
from ui import db
from ui.models import AppSetting

# Re-exported so this addon's other modules have one obvious place to import
# from, instead of each picking core or addon at random.
from ui.stats_hub import (  # noqa: F401
    get_effective_stats_hub_ingest_token,
    get_effective_stats_hub_url,
    get_host_stats_hub_ingest_token,
    get_host_stats_hub_url,
    get_instance_server_id,
    get_stats_hub_ingest_token,
    get_stats_hub_url,
    is_stats_hub_configured,
    is_stats_hub_configured_for_host,
    read_cvars_from_text,
    reserve_server_id,
    set_host_stats_hub_ingest_token,
    set_host_stats_hub_url,
    set_instance_server_id,
    set_stats_hub_ingest_token,
    set_stats_hub_url,
    strip_cvars_from_text,
    upsert_cvars_in_text,
)

_RELAY_ENABLED_PREFIX = 'telemetry_relay_enabled:'


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


def is_relay_enabled(host_id):
    return _get(f'{_RELAY_ENABLED_PREFIX}{host_id}') == '1'


def set_relay_enabled(host_id, enabled):
    _set(f'{_RELAY_ENABLED_PREFIX}{host_id}', '1' if enabled else '')
