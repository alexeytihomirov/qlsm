from unittest.mock import patch, MagicMock
from ui.task_logic.terraform_runner import _terraform_env


class TestTerraformEnv:
    def test_includes_db_vultr_key(self, app, monkeypatch):
        monkeypatch.delenv('VULTR_API_KEY', raising=False)
        with app.app_context():
            from ui.vultr_settings import set_vultr_api_key
            from ui import db
            set_vultr_api_key('db-key-value')
            db.session.commit()
            env = _terraform_env()
            assert env['VULTR_API_KEY'] == 'db-key-value'

    def test_omits_key_when_unconfigured(self, app, monkeypatch):
        monkeypatch.delenv('VULTR_API_KEY', raising=False)
        with app.app_context():
            env = _terraform_env()
            assert 'VULTR_API_KEY' not in env
