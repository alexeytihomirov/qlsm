from unittest.mock import MagicMock, patch

import pytest

from ui import db
from ui.database import create_host, create_instance
from ui.demo_stream_settings import (
    get_instance_demo_stream_token,
    is_instance_demo_stream_enabled,
    set_relay_host,
    set_relay_port,
)
from ui.models import HostStatus
from ui.task_logic.demo_stream_instance import enable_instance_demo_stream_logic
from ui.stats_hub import read_cvars_from_text
from ui.stats_hub import (
    get_instance_server_id,
    set_stats_hub_ingest_token,
    set_stats_hub_url,
)


def _configure_globals():
    set_relay_host('relay.example.com')
    set_relay_port('27999')
    set_stats_hub_url('demo_stream', 'https://hub.example.com')
    set_stats_hub_ingest_token('demo_stream', 'ingest-token')
    db.session.commit()


def _read_cfg(tmp_path, host_name, instance_id):
    path = tmp_path / 'configs' / host_name / str(instance_id) / 'server.cfg'
    return path.read_text(encoding='utf-8')


@pytest.fixture
def mock_route_registration():
    with patch('ui.task_logic.demo_stream_instance.requests.post') as mock_post:
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        yield mock_post


@pytest.fixture
def mock_apply_config():
    with patch('ui.tasks.enqueue_task') as mock_enqueue:
        mock_enqueue.return_value = MagicMock(id='job-123')
        yield mock_enqueue


class TestEnableInstanceDemoStream:
    def test_missing_instance_fails(self, app):
        with app.app_context():
            ok, message = enable_instance_demo_stream_logic(999999)
            assert ok is False
            assert 'not found' in message

    def test_relay_not_configured_fails(self, app):
        with app.app_context():
            host = create_host(name='germany', provider='vultr', status=HostStatus.ACTIVE)
            instance = create_instance(name='sD test', host_id=host.id, port=27960, hostname='sD')
            ok, message = enable_instance_demo_stream_logic(instance.id)
            assert ok is False
            assert 'relay' in message.lower()

    def test_stats_hub_not_configured_fails(self, app):
        with app.app_context():
            set_relay_host('relay.example.com')
            set_relay_port('27999')
            db.session.commit()
            host = create_host(name='germany', provider='vultr', status=HostStatus.ACTIVE)
            instance = create_instance(name='sD test', host_id=host.id, port=27960, hostname='sD')
            ok, message = enable_instance_demo_stream_logic(instance.id)
            assert ok is False
            assert 'stats-hub' in message.lower()

    def test_route_registration_failure_does_not_write_config(self, app, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with app.app_context():
            _configure_globals()
            host = create_host(name='germany', provider='vultr', status=HostStatus.ACTIVE)
            instance = create_instance(name='sD test', host_id=host.id, port=27960, hostname='sD')

            import requests

            with patch(
                'ui.task_logic.demo_stream_instance.reserve_server_id', return_value=7
            ), patch(
                'ui.task_logic.demo_stream_instance.requests.post',
                side_effect=requests.RequestException('boom'),
            ):
                ok, message = enable_instance_demo_stream_logic(instance.id)

            assert ok is False
            assert 'route' in message.lower()
            assert is_instance_demo_stream_enabled(instance.id) is False

    def test_success_reserves_id_writes_cvars_and_queues_restart(
        self, app, tmp_path, monkeypatch, mock_route_registration, mock_apply_config
    ):
        monkeypatch.chdir(tmp_path)
        with app.app_context():
            _configure_globals()
            host = create_host(name='germany', provider='vultr', status=HostStatus.ACTIVE)
            instance = create_instance(name='sD test', host_id=host.id, port=27960, hostname='sD')

            with patch('ui.task_logic.demo_stream_instance.reserve_server_id', return_value=7) as mock_reserve:
                ok, message = enable_instance_demo_stream_logic(instance.id)

            assert ok is True
            assert 'server_id=7' in message
            mock_reserve.assert_called_once_with(instance.name, host.id)
            assert get_instance_server_id('demo_stream', instance.id) == 7
            assert is_instance_demo_stream_enabled(instance.id) is True

            token = get_instance_demo_stream_token(instance.id)
            assert token

            mock_route_registration.assert_called_once()
            call_kwargs = mock_route_registration.call_args
            assert call_kwargs.args[0] == 'https://hub.example.com/api/demo-stream/routes'
            assert call_kwargs.kwargs['json'] == {
                'token': token, 'server_id': 7, 'server_name': instance.name,
            }
            assert call_kwargs.kwargs['headers']['Authorization'] == 'Bearer ingest-token'

            cfg_text = _read_cfg(tmp_path, 'germany', instance.id)
            cvars = read_cvars_from_text(
                cfg_text,
                ('sv_demoStream', 'sv_demoStreamHost', 'sv_demoStreamPort', 'sv_demoStreamToken'),
            )
            assert cvars == {
                'sv_demoStream': '1',
                'sv_demoStreamHost': 'relay.example.com',
                'sv_demoStreamPort': '27999',
                'sv_demoStreamToken': token,
            }

            mock_apply_config.assert_called_once()

    def test_reuses_existing_server_id_and_token(self, app, tmp_path, monkeypatch, mock_route_registration, mock_apply_config):
        monkeypatch.chdir(tmp_path)
        with app.app_context():
            _configure_globals()
            host = create_host(name='germany', provider='vultr', status=HostStatus.ACTIVE)
            instance = create_instance(name='sD test', host_id=host.id, port=27960, hostname='sD')

            from ui.demo_stream_settings import set_instance_demo_stream_token
            from ui.stats_hub import set_instance_server_id
            set_instance_server_id('demo_stream', instance.id, 3)
            set_instance_demo_stream_token(instance.id, 'existing-token')
            db.session.commit()

            with patch('ui.task_logic.demo_stream_instance.reserve_server_id') as mock_reserve:
                ok, _message = enable_instance_demo_stream_logic(instance.id)

            assert ok is True
            mock_reserve.assert_not_called()
            assert get_instance_demo_stream_token(instance.id) == 'existing-token'
            call_kwargs = mock_route_registration.call_args
            assert call_kwargs.kwargs['json']['token'] == 'existing-token'
            assert call_kwargs.kwargs['json']['server_id'] == 3
