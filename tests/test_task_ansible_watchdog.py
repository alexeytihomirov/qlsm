import json

import pytest
from unittest.mock import patch, MagicMock
from ui.task_logic.ansible_watchdog import configure_host_watchdog_logic
from ui.models import HostStatus
from ui.database import create_host, get_host


@pytest.fixture
def mock_run_playbook():
    with patch('ui.task_logic.ansible_watchdog._run_host_ansible_playbook') as mock:
        yield mock


@pytest.fixture
def mock_get_current_job():
    with patch('ui.task_logic.ansible_watchdog.get_current_job') as mock:
        mock_job = MagicMock()
        mock_job.id = 'test-watchdog-job-id'
        mock.return_value = mock_job
        yield mock


def test_configure_host_watchdog_enable(app, mock_run_playbook, mock_get_current_job):
    mock_run_playbook.return_value = (True, "mock stdout", "")

    with app.app_context():
        host = create_host(name='test-host-watchdog', provider='vultr', status=HostStatus.ACTIVE)
        host_id = host.id

        result = configure_host_watchdog_logic(host_id, True, {'strikes': 5, 'forensics': False})

        assert result is True
        mock_run_playbook.assert_called_once()
        args, kwargs = mock_run_playbook.call_args
        assert kwargs['playbook_name'] == 'configure_watchdog.yml'
        assert kwargs['extravars'] == {
            'watchdog_enabled': True,
            'watchdog_strikes': 5,
            'watchdog_forensics': False,
        }

        updated_host = get_host(host_id)
        assert updated_host.status == HostStatus.ACTIVE
        assert updated_host.watchdog_enabled is True
        assert json.loads(updated_host.watchdog_config) == {'strikes': 5, 'forensics': False}


def test_configure_host_watchdog_disable(app, mock_run_playbook, mock_get_current_job):
    mock_run_playbook.return_value = (True, "mock stdout", "")

    with app.app_context():
        host = create_host(name='test-host-watchdog2', provider='vultr', status=HostStatus.ACTIVE,
                            watchdog_enabled=True, watchdog_config=json.dumps({'strikes': 5}))
        host_id = host.id

        result = configure_host_watchdog_logic(host_id, False)

        assert result is True
        mock_run_playbook.assert_called_once()
        args, kwargs = mock_run_playbook.call_args
        assert kwargs['extravars'] == {'watchdog_enabled': False}

        updated_host = get_host(host_id)
        assert updated_host.watchdog_enabled is False
        assert updated_host.watchdog_config is None


def test_configure_host_watchdog_ansible_failure(app, mock_run_playbook, mock_get_current_job):
    mock_run_playbook.return_value = (False, "mock stdout", "error running playbook")

    with app.app_context():
        host = create_host(name='test-host-watchdog3', provider='vultr', status=HostStatus.ACTIVE)
        host_id = host.id

        result = configure_host_watchdog_logic(host_id, True)

        assert result is False
        updated_host = get_host(host_id)
        assert updated_host.status == HostStatus.ERROR
        assert updated_host.watchdog_enabled is False  # Not persisted on failure


def test_configure_host_watchdog_host_not_found(app):
    with app.app_context():
        result = configure_host_watchdog_logic(99999, True)
        assert result is False
