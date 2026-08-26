import os
from unittest.mock import patch

from ui import db
from ui.database import create_host, create_instance
from ui.models import HostStatus
from ui.task_logic.telemetry_relay_instance import (
    read_cvars_from_text,
    sync_instance_server_id_from_config,
)
from ui.telemetry_relay_settings import get_instance_server_id


class TestReadCvarsFromText:
    def test_reads_requested_cvars_only(self):
        text = 'set qlx_statsHubUnifiedEnabled "1"\nset sv_hostname "foo"\nset qlx_statsHubServerId "3"\n'
        result = read_cvars_from_text(text, ('qlx_statsHubUnifiedEnabled', 'qlx_statsHubServerId'))
        assert result == {'qlx_statsHubUnifiedEnabled': '1', 'qlx_statsHubServerId': '3'}

    def test_missing_cvar_absent_from_result(self):
        text = 'set sv_hostname "foo"\n'
        assert read_cvars_from_text(text, ('qlx_statsHubServerId',)) == {}

    def test_last_occurrence_wins(self):
        text = 'set qlx_statsHubServerId "1"\nset qlx_statsHubServerId "2"\n'
        assert read_cvars_from_text(text, ('qlx_statsHubServerId',)) == {'qlx_statsHubServerId': '2'}


def _write_cfg(tmp_path, host_name, instance_id, text):
    cfg_dir = tmp_path / 'configs' / host_name / str(instance_id)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / 'server.cfg').write_text(text, encoding='utf-8')


class TestSyncInstanceServerIdFromConfig:
    def test_picks_up_cvar_set_by_hand_without_enable_flow(self, app, tmp_path, monkeypatch):
        """The bug this closes: an operator sets qlx_statsHubUnifiedEnabled /
        qlx_statsHubServerId directly (e.g. via the Plugins-tab cvar editor)
        without ever calling enable_instance_telemetry_logic. The relay's
        routing table must still end up knowing about this instance."""
        monkeypatch.chdir(tmp_path)
        with app.app_context():
            host = create_host(name='germany', provider='vultr', status=HostStatus.ACTIVE)
            instance = create_instance(name='sD test server', host_id=host.id, port=27960, hostname='sD')
            _write_cfg(
                tmp_path, 'germany', instance.id,
                'set qlx_statsHubUnifiedEnabled "1"\nset qlx_statsHubServerId "1"\n',
            )

            assert get_instance_server_id(instance.id) is None

            with patch(
                'ui.task_logic.telemetry_relay_instance.push_relay_config_logic', return_value=True
            ) as mock_push:
                sync_instance_server_id_from_config(instance)

            assert get_instance_server_id(instance.id) == 1
            mock_push.assert_called_once_with(host.id)

    def test_disabled_plugin_clears_any_stale_mapping(self, app, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with app.app_context():
            host = create_host(name='germany', provider='vultr', status=HostStatus.ACTIVE)
            instance = create_instance(name='sD test server', host_id=host.id, port=27960, hostname='sD')
            from ui.telemetry_relay_settings import set_instance_server_id
            set_instance_server_id(instance.id, 7)
            db.session.commit()

            _write_cfg(
                tmp_path, 'germany', instance.id,
                'set qlx_statsHubUnifiedEnabled "0"\nset qlx_statsHubServerId "7"\n',
            )

            with patch(
                'ui.task_logic.telemetry_relay_instance.push_relay_config_logic', return_value=True
            ) as mock_push:
                sync_instance_server_id_from_config(instance)

            assert get_instance_server_id(instance.id) is None
            mock_push.assert_called_once_with(host.id)

    def test_already_in_sync_does_not_push_relay_config(self, app, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with app.app_context():
            host = create_host(name='germany', provider='vultr', status=HostStatus.ACTIVE)
            instance = create_instance(name='sD test server', host_id=host.id, port=27960, hostname='sD')
            from ui.telemetry_relay_settings import set_instance_server_id
            set_instance_server_id(instance.id, 1)
            db.session.commit()

            _write_cfg(
                tmp_path, 'germany', instance.id,
                'set qlx_statsHubUnifiedEnabled "1"\nset qlx_statsHubServerId "1"\n',
            )

            with patch(
                'ui.task_logic.telemetry_relay_instance.push_relay_config_logic', return_value=True
            ) as mock_push:
                sync_instance_server_id_from_config(instance)

            mock_push.assert_not_called()

    def test_missing_config_file_is_a_no_op(self, app, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with app.app_context():
            host = create_host(name='germany', provider='vultr', status=HostStatus.ACTIVE)
            instance = create_instance(name='sD test server', host_id=host.id, port=27960, hostname='sD')

            with patch(
                'ui.task_logic.telemetry_relay_instance.push_relay_config_logic', return_value=True
            ) as mock_push:
                sync_instance_server_id_from_config(instance)

            assert get_instance_server_id(instance.id) is None
            mock_push.assert_not_called()
