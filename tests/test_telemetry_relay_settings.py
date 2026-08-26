from ui import db
from ui.models import AppSetting
from ui.telemetry_relay_settings import (
    get_effective_stats_hub_ingest_token,
    get_effective_stats_hub_url,
    get_host_stats_hub_ingest_token,
    get_host_stats_hub_url,
    get_stats_hub_url,
    is_stats_hub_configured,
    is_stats_hub_configured_for_host,
    set_host_stats_hub_ingest_token,
    set_host_stats_hub_url,
    set_stats_hub_ingest_token,
    set_stats_hub_url,
)


class TestHostStatsHubOverride:
    def test_host_override_unset_falls_back_to_global(self, app):
        with app.app_context():
            set_stats_hub_url('https://hub.example.com')
            set_stats_hub_ingest_token('global-token')
            db.session.commit()
            assert get_host_stats_hub_url(1) is None
            assert get_host_stats_hub_ingest_token(1) is None
            assert get_effective_stats_hub_url(1) == 'https://hub.example.com'
            assert get_effective_stats_hub_ingest_token(1) == 'global-token'

    def test_host_override_wins_over_global(self, app):
        with app.app_context():
            set_stats_hub_url('https://hub.example.com')
            set_stats_hub_ingest_token('global-token')
            set_host_stats_hub_url(1, 'https://hub-eu.example.com')
            set_host_stats_hub_ingest_token(1, 'host-token')
            db.session.commit()
            assert get_effective_stats_hub_url(1) == 'https://hub-eu.example.com'
            assert get_effective_stats_hub_ingest_token(1) == 'host-token'
            # Global config and other hosts are untouched.
            assert get_stats_hub_url() == 'https://hub.example.com'
            assert get_effective_stats_hub_url(2) == 'https://hub.example.com'

    def test_host_override_strips_trailing_slash_like_global(self, app):
        with app.app_context():
            set_host_stats_hub_url(1, 'https://hub-eu.example.com/')
            db.session.commit()
            assert get_host_stats_hub_url(1) == 'https://hub-eu.example.com'

    def test_clearing_host_override_falls_back_to_global(self, app):
        with app.app_context():
            set_stats_hub_url('https://hub.example.com')
            set_host_stats_hub_url(1, 'https://hub-eu.example.com')
            db.session.commit()
            set_host_stats_hub_url(1, '')
            db.session.commit()
            assert get_host_stats_hub_url(1) is None
            assert get_effective_stats_hub_url(1) == 'https://hub.example.com'

    def test_is_stats_hub_configured_for_host_uses_effective_values(self, app):
        with app.app_context():
            assert is_stats_hub_configured_for_host(1) is False
            set_stats_hub_url('https://hub.example.com')
            db.session.commit()
            assert is_stats_hub_configured_for_host(1) is False
            set_stats_hub_ingest_token('global-token')
            db.session.commit()
            assert is_stats_hub_configured() is True
            assert is_stats_hub_configured_for_host(1) is True

    def test_host_override_does_not_require_global_configured(self, app):
        """A host can have its own fully-independent stats-hub target even
        with no global default set at all (multi-stats-hub setups)."""
        with app.app_context():
            assert is_stats_hub_configured() is False
            set_host_stats_hub_url(1, 'https://hub-eu.example.com')
            set_host_stats_hub_ingest_token(1, 'host-token')
            db.session.commit()
            assert is_stats_hub_configured_for_host(1) is True
            assert is_stats_hub_configured() is False

    def test_host_overrides_are_isolated_per_host(self, app):
        with app.app_context():
            set_host_stats_hub_url(1, 'https://hub-a.example.com')
            set_host_stats_hub_url(2, 'https://hub-b.example.com')
            db.session.commit()
            assert get_host_stats_hub_url(1) == 'https://hub-a.example.com'
            assert get_host_stats_hub_url(2) == 'https://hub-b.example.com'
            assert AppSetting.query.count() == 2
