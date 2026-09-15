"""server.cfg -> relay routing sync, after telemetry-relay became an addon.

The cvar reader stayed in core (ui/stats_hub.py, shared with the demo
stream); the sync itself moved into the addon and now runs off the
instance.config_applied hook instead of a direct call in
apply_instance_config_logic.
"""
import os
from unittest.mock import patch

from ui import db
from ui.database import create_host, create_instance
from ui.models import HostStatus
from ui.stats_hub import get_instance_server_id, read_cvars_from_text


def _instance_ops():
    """The addon's module, importable only once an app has loaded the addon
    registry -- hence the lazy lookup rather than a top-level import.

    Returned as the module (not the function) so patch() targets resolve: its
    string form would import the submodule itself, and nothing has yet,
    because backend.py imports it lazily inside the hook handler.
    """
    import importlib

    return importlib.import_module('qlsm_addon_telemetry_relay.instance_ops')


def _sync():
    return _instance_ops().sync_instance_server_id_from_config


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

            assert get_instance_server_id('telemetry', instance.id) is None

            _instance_ops()
            with patch(
                'qlsm_addon_telemetry_relay.instance_ops.push_relay_config_logic', return_value=True
            ) as mock_push:
                _sync()(instance)

            assert get_instance_server_id('telemetry', instance.id) == 1
            mock_push.assert_called_once_with(host.id)

    def test_disabled_plugin_clears_any_stale_mapping(self, app, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with app.app_context():
            host = create_host(name='germany', provider='vultr', status=HostStatus.ACTIVE)
            instance = create_instance(name='sD test server', host_id=host.id, port=27960, hostname='sD')
            from ui.stats_hub import set_instance_server_id
            set_instance_server_id('telemetry', instance.id, 7)
            db.session.commit()

            _write_cfg(
                tmp_path, 'germany', instance.id,
                'set qlx_statsHubUnifiedEnabled "0"\nset qlx_statsHubServerId "7"\n',
            )

            _instance_ops()
            with patch(
                'qlsm_addon_telemetry_relay.instance_ops.push_relay_config_logic', return_value=True
            ) as mock_push:
                _sync()(instance)

            assert get_instance_server_id('telemetry', instance.id) is None
            mock_push.assert_called_once_with(host.id)

    def test_already_in_sync_does_not_push_relay_config(self, app, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with app.app_context():
            host = create_host(name='germany', provider='vultr', status=HostStatus.ACTIVE)
            instance = create_instance(name='sD test server', host_id=host.id, port=27960, hostname='sD')
            from ui.stats_hub import set_instance_server_id
            set_instance_server_id('telemetry', instance.id, 1)
            db.session.commit()

            _write_cfg(
                tmp_path, 'germany', instance.id,
                'set qlx_statsHubUnifiedEnabled "1"\nset qlx_statsHubServerId "1"\n',
            )

            _instance_ops()
            with patch(
                'qlsm_addon_telemetry_relay.instance_ops.push_relay_config_logic', return_value=True
            ) as mock_push:
                _sync()(instance)

            mock_push.assert_not_called()

    def test_missing_config_file_is_a_no_op(self, app, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with app.app_context():
            host = create_host(name='germany', provider='vultr', status=HostStatus.ACTIVE)
            instance = create_instance(name='sD test server', host_id=host.id, port=27960, hostname='sD')

            _instance_ops()
            with patch(
                'qlsm_addon_telemetry_relay.instance_ops.push_relay_config_logic', return_value=True
            ) as mock_push:
                _sync()(instance)

            assert get_instance_server_id('telemetry', instance.id) is None
            mock_push.assert_not_called()
