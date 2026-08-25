import pytest
from unittest.mock import patch, MagicMock
from ui.task_logic.ansible_plugin_update import update_common_plugins_logic
from ui.models import HostStatus, InstanceStatus
from ui.database import create_host, get_host, get_instance


@pytest.fixture
def mock_restart_instance_queue():
    with patch('ui.tasks.restart_instance.queue') as mock:
        yield mock


@pytest.fixture
def mock_run_playbook():
    with patch('ui.task_logic.ansible_plugin_update._run_host_ansible_playbook') as mock:
        yield mock


@pytest.fixture
def mock_get_current_job():
    with patch('ui.task_logic.ansible_plugin_update.get_current_job') as mock:
        mock_job = MagicMock()
        mock_job.id = 'test-job-id'
        mock.return_value = mock_job
        yield mock


def test_update_common_plugins_success_no_restarts(app, mock_run_playbook, mock_get_current_job, mock_restart_instance_queue):
    mock_run_playbook.return_value = (True, "mock stdout", "mock stderr")

    with app.app_context():
        host = create_host(name='test-host-plugins', provider='vultr', status=HostStatus.ACTIVE)
        from ui.database import db
        from ui.models import QLInstance

        inst1 = QLInstance(name='inst-1', port=27960, hostname='server1', host_id=host.id, status=InstanceStatus.RUNNING)
        inst2 = QLInstance(name='inst-2', port=27961, hostname='server2', host_id=host.id, status=InstanceStatus.STOPPED)
        db.session.add_all([inst1, inst2])
        db.session.commit()

        host_id = host.id

        result = update_common_plugins_logic(host_id, [])

        assert result is True
        mock_run_playbook.assert_called_once()
        mock_restart_instance_queue.assert_not_called()

        updated_host = get_host(host_id)
        assert updated_host.status == HostStatus.ACTIVE
        assert 'Common plugin pool updated' in updated_host.logs


def test_update_common_plugins_success_with_restarts(app, mock_run_playbook, mock_get_current_job, mock_restart_instance_queue):
    mock_run_playbook.return_value = (True, "mock stdout", "")

    with app.app_context():
        host = create_host(name='test-host-plugins2', provider='vultr', status=HostStatus.ACTIVE)
        from ui.database import db
        from ui.models import QLInstance

        inst1 = QLInstance(name='inst-1', port=27960, hostname='server1', host_id=host.id, status=InstanceStatus.RUNNING)
        inst2 = QLInstance(name='inst-2', port=27961, hostname='server2', host_id=host.id, status=InstanceStatus.STOPPED)
        db.session.add_all([inst1, inst2])
        db.session.commit()

        host_id = host.id
        inst1_id = inst1.id
        inst2_id = inst2.id

        result = update_common_plugins_logic(host_id, [inst1_id, inst2_id])

        assert result is True
        mock_run_playbook.assert_called_once()
        # Only inst-1 gets queued: inst-2 is STOPPED and must stay stopped.
        mock_restart_instance_queue.assert_called_once_with(inst1_id)

        updated_inst1 = get_instance(inst1_id)
        assert updated_inst1.status == InstanceStatus.RESTARTING

        updated_inst2 = get_instance(inst2_id)
        assert updated_inst2.status == InstanceStatus.STOPPED


def test_update_common_plugins_ansible_failure(app, mock_run_playbook, mock_get_current_job, mock_restart_instance_queue):
    mock_run_playbook.return_value = (False, "mock stdout", "error running playbook")

    with app.app_context():
        host = create_host(name='test-host-plugins3', provider='vultr', status=HostStatus.ACTIVE)
        host_id = host.id

        result = update_common_plugins_logic(host_id, [])

        assert result is False
        mock_run_playbook.assert_called_once()
        mock_restart_instance_queue.assert_not_called()

        updated_host = get_host(host_id)
        assert updated_host.status == HostStatus.ERROR
        assert 'Common plugin pool update failed: error running playbook' in updated_host.logs


def test_update_common_plugins_host_not_found(app):
    with app.app_context():
        result = update_common_plugins_logic(99999, [])
        assert result is False
