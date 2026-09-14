from ui import db
from ui.models import AppSetting
from ui.demo_stream_settings import (
    get_instance_demo_stream_token,
    get_relay_host,
    get_relay_port,
    is_instance_demo_stream_enabled,
    is_relay_configured,
    set_instance_demo_stream_enabled,
    set_instance_demo_stream_token,
    set_relay_host,
    set_relay_port,
)


class TestRelaySettings:
    def test_unset_is_not_configured(self, app):
        with app.app_context():
            assert get_relay_host() is None
            assert get_relay_port() is None
            assert is_relay_configured() is False

    def test_set_both_marks_configured(self, app):
        with app.app_context():
            set_relay_host('relay.example.com')
            set_relay_port('27999')
            db.session.commit()
            assert get_relay_host() == 'relay.example.com'
            assert get_relay_port() == '27999'
            assert is_relay_configured() is True

    def test_only_host_set_is_not_configured(self, app):
        with app.app_context():
            set_relay_host('relay.example.com')
            db.session.commit()
            assert is_relay_configured() is False

    def test_clearing_host_removes_the_row(self, app):
        with app.app_context():
            set_relay_host('relay.example.com')
            db.session.commit()
            set_relay_host('')
            db.session.commit()
            assert get_relay_host() is None
            assert AppSetting.query.count() == 0


class TestInstanceState:
    def test_default_disabled_no_token(self, app):
        with app.app_context():
            assert is_instance_demo_stream_enabled(1) is False
            assert get_instance_demo_stream_token(1) is None

    def test_enable_and_token_are_isolated_per_instance(self, app):
        with app.app_context():
            set_instance_demo_stream_enabled(1, True)
            set_instance_demo_stream_token(1, 'token-a')
            set_instance_demo_stream_token(2, 'token-b')
            db.session.commit()

            assert is_instance_demo_stream_enabled(1) is True
            assert is_instance_demo_stream_enabled(2) is False
            assert get_instance_demo_stream_token(1) == 'token-a'
            assert get_instance_demo_stream_token(2) == 'token-b'

    def test_disable_clears_flag(self, app):
        with app.app_context():
            set_instance_demo_stream_enabled(5, True)
            db.session.commit()
            set_instance_demo_stream_enabled(5, False)
            db.session.commit()
            assert is_instance_demo_stream_enabled(5) is False
