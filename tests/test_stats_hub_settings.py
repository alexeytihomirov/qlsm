"""The ql-stats-hub target settings, per feature.

Was tests/test_telemetry_relay_settings.py, then generalized when the live
demo stream also needed a stats-hub target. Each feature ('telemetry',
'demo_stream') now has its own independent URL/token/override/server-id, so
this also covers that the two features cannot see or clobber each other's
configuration.
"""
from ui import db
from ui.models import AppSetting
from ui.stats_hub import (
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
            set_stats_hub_url('telemetry', 'https://hub.example.com')
            set_stats_hub_ingest_token('telemetry', 'global-token')
            db.session.commit()
            assert get_host_stats_hub_url('telemetry', 1) is None
            assert get_host_stats_hub_ingest_token('telemetry', 1) is None
            assert get_effective_stats_hub_url('telemetry', 1) == 'https://hub.example.com'
            assert get_effective_stats_hub_ingest_token('telemetry', 1) == 'global-token'

    def test_host_override_wins_over_global(self, app):
        with app.app_context():
            set_stats_hub_url('telemetry', 'https://hub.example.com')
            set_stats_hub_ingest_token('telemetry', 'global-token')
            set_host_stats_hub_url('telemetry', 1, 'https://hub-eu.example.com')
            set_host_stats_hub_ingest_token('telemetry', 1, 'host-token')
            db.session.commit()
            assert get_effective_stats_hub_url('telemetry', 1) == 'https://hub-eu.example.com'
            assert get_effective_stats_hub_ingest_token('telemetry', 1) == 'host-token'
            # Global config and other hosts are untouched.
            assert get_stats_hub_url('telemetry') == 'https://hub.example.com'
            assert get_effective_stats_hub_url('telemetry', 2) == 'https://hub.example.com'

    def test_host_override_strips_trailing_slash_like_global(self, app):
        with app.app_context():
            set_host_stats_hub_url('telemetry', 1, 'https://hub-eu.example.com/')
            db.session.commit()
            assert get_host_stats_hub_url('telemetry', 1) == 'https://hub-eu.example.com'

    def test_clearing_host_override_falls_back_to_global(self, app):
        with app.app_context():
            set_stats_hub_url('telemetry', 'https://hub.example.com')
            set_host_stats_hub_url('telemetry', 1, 'https://hub-eu.example.com')
            db.session.commit()
            set_host_stats_hub_url('telemetry', 1, '')
            db.session.commit()
            assert get_host_stats_hub_url('telemetry', 1) is None
            assert get_effective_stats_hub_url('telemetry', 1) == 'https://hub.example.com'

    def test_is_stats_hub_configured_for_host_uses_effective_values(self, app):
        with app.app_context():
            assert is_stats_hub_configured_for_host('telemetry', 1) is False
            set_stats_hub_url('telemetry', 'https://hub.example.com')
            db.session.commit()
            assert is_stats_hub_configured_for_host('telemetry', 1) is False
            set_stats_hub_ingest_token('telemetry', 'global-token')
            db.session.commit()
            assert is_stats_hub_configured('telemetry') is True
            assert is_stats_hub_configured_for_host('telemetry', 1) is True

    def test_host_override_does_not_require_global_configured(self, app):
        """A host can have its own fully-independent stats-hub target even
        with no global default set at all (multi-stats-hub setups)."""
        with app.app_context():
            assert is_stats_hub_configured('telemetry') is False
            set_host_stats_hub_url('telemetry', 1, 'https://hub-eu.example.com')
            set_host_stats_hub_ingest_token('telemetry', 1, 'host-token')
            db.session.commit()
            assert is_stats_hub_configured_for_host('telemetry', 1) is True
            assert is_stats_hub_configured('telemetry') is False

    def test_host_overrides_are_isolated_per_host(self, app):
        with app.app_context():
            set_host_stats_hub_url('telemetry', 1, 'https://hub-a.example.com')
            set_host_stats_hub_url('telemetry', 2, 'https://hub-b.example.com')
            db.session.commit()
            assert get_host_stats_hub_url('telemetry', 1) == 'https://hub-a.example.com'
            assert get_host_stats_hub_url('telemetry', 2) == 'https://hub-b.example.com'
            assert AppSetting.query.count() == 2


class TestFeatureIsolation:
    """telemetry and demo_stream may point at different stats-hub clusters,
    so neither the global target nor a per-host override may leak between
    them. Before this split they shared one set of keys - a URL typed into
    telemetry's host panel silently became the demo stream's target too."""

    def test_global_targets_are_independent(self, app):
        with app.app_context():
            set_stats_hub_url('telemetry', 'https://telemetry-hub.example.com')
            set_stats_hub_ingest_token('telemetry', 'telemetry-token')
            set_stats_hub_url('demo_stream', 'https://stream-hub.example.com')
            set_stats_hub_ingest_token('demo_stream', 'stream-token')
            db.session.commit()

            assert get_stats_hub_url('telemetry') == 'https://telemetry-hub.example.com'
            assert get_stats_hub_url('demo_stream') == 'https://stream-hub.example.com'

    def test_host_override_on_one_feature_does_not_affect_the_other(self, app):
        with app.app_context():
            set_stats_hub_url('telemetry', 'https://global-hub.example.com')
            set_stats_hub_ingest_token('telemetry', 'global-token')
            set_stats_hub_url('demo_stream', 'https://global-hub.example.com')
            set_stats_hub_ingest_token('demo_stream', 'global-token')
            set_host_stats_hub_url('telemetry', 1, 'https://telemetry-only.example.com')
            db.session.commit()

            assert get_effective_stats_hub_url('telemetry', 1) == 'https://telemetry-only.example.com'
            assert get_effective_stats_hub_url('demo_stream', 1) == 'https://global-hub.example.com'

    def test_unknown_feature_is_rejected(self, app):
        import pytest

        with app.app_context():
            with pytest.raises(ValueError):
                get_stats_hub_url('not-a-real-feature')
