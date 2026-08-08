import os
import pytest
from ui import db
from ui.models import AppSetting
from ui.vultr_settings import get_vultr_api_key, set_vultr_api_key, is_vultr_configured


class TestVultrSettings:
    def test_get_returns_none_when_unset(self, app, monkeypatch):
        monkeypatch.delenv('VULTR_API_KEY', raising=False)
        with app.app_context():
            assert get_vultr_api_key() == ''
            assert is_vultr_configured() is False

    def test_set_then_get(self, app):
        with app.app_context():
            set_vultr_api_key('abc123')
            db.session.commit()
            assert get_vultr_api_key() == 'abc123'
            assert is_vultr_configured() is True

    def test_set_overwrites_existing(self, app):
        with app.app_context():
            set_vultr_api_key('first')
            db.session.commit()
            set_vultr_api_key('second')
            db.session.commit()
            assert get_vultr_api_key() == 'second'
            assert AppSetting.query.count() == 1

    def test_set_empty_string_clears_existing(self, app, monkeypatch):
        monkeypatch.delenv('VULTR_API_KEY', raising=False)
        with app.app_context():
            set_vultr_api_key('abc123')
            db.session.commit()
            set_vultr_api_key('')
            db.session.commit()
            assert get_vultr_api_key() == ''
            assert AppSetting.query.count() == 0

    def test_db_value_takes_priority_over_env(self, app, monkeypatch):
        monkeypatch.setenv('VULTR_API_KEY', 'from-env')
        with app.app_context():
            set_vultr_api_key('from-db')
            db.session.commit()
            assert get_vultr_api_key() == 'from-db'

    def test_falls_back_to_env_when_db_empty(self, app, monkeypatch):
        monkeypatch.setenv('VULTR_API_KEY', 'from-env')
        with app.app_context():
            assert get_vultr_api_key() == 'from-env'
            assert is_vultr_configured() is True
