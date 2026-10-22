from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from ui import db
from ui.models import Host, HostStatus, InstanceStatus, QLInstance
from ui.task_logic import interrupted_job_recovery as recovery
from ui.task_logic.interrupted_job_recovery import (
    CONFIG_UNCONFIRMED_LOG,
    reconcile_stale_instance_jobs,
    recover_interrupted_instance,
)
from ui.task_logic.service_runtime import RuntimeObservation


def _obs(active):
    return RuntimeObservation(status=None, invocation_id=None, active=active, service_started_at=None)


@pytest.fixture
def make_instance(app):
    def _make(status=InstanceStatus.CONFIGURING):
        host = Host(id=1, name='host', provider='vultr', status=HostStatus.ACTIVE)
        inst = QLInstance(id=1, name='test', host_id=1, port=27960, hostname='h', status=status)
        db.session.add_all([host, inst])
        db.session.commit()
        return inst
    with app.app_context():
        db.create_all()
        yield _make


@pytest.fixture
def locks():
    with patch('ui.task_lock.lock_superseded', return_value=False) as superseded, \
            patch('ui.task_lock.release_lock') as release:
        yield superseded, release


def _recover(token='tok'):
    return recover_interrupted_instance(1, 'job-1', token, 'AbandonedJobError')


def _status():
    return db.session.get(QLInstance, 1)


def test_active_probe_sets_running_and_logs_unconfirmed(make_instance, locks):
    make_instance()
    with patch.object(recovery, 'probe_host_runtime', return_value={'27960': _obs(True)}):
        assert _recover() is True
    assert _status().status == InstanceStatus.RUNNING
    assert CONFIG_UNCONFIRMED_LOG in _status().logs


def test_inactive_probe_sets_stopped(make_instance, locks):
    make_instance()
    with patch.object(recovery, 'probe_host_runtime', return_value={'27960': _obs(False)}):
        _recover()
    assert _status().status == InstanceStatus.STOPPED
    assert CONFIG_UNCONFIRMED_LOG not in _status().logs


def test_probe_failure_sets_error(make_instance, locks):
    make_instance()
    with patch.object(recovery, 'probe_host_runtime', return_value=None):
        _recover()
    assert _status().status == InstanceStatus.ERROR


def test_missing_port_in_probe_sets_error(make_instance, locks):
    make_instance()
    with patch.object(recovery, 'probe_host_runtime', return_value={'27961': _obs(True)}):
        _recover()
    assert _status().status == InstanceStatus.ERROR


@pytest.mark.parametrize('status', [InstanceStatus.DEPLOYING, InstanceStatus.DELETING])
def test_deploying_and_deleting_go_to_error_without_probe(make_instance, locks, status):
    make_instance(status)
    with patch.object(recovery, 'probe_host_runtime') as probe:
        _recover()
    probe.assert_not_called()
    assert _status().status == InstanceStatus.ERROR


def test_superseded_lock_changes_nothing(make_instance, locks):
    superseded, release = locks
    superseded.return_value = True
    make_instance()
    with patch.object(recovery, 'probe_host_runtime') as probe:
        assert _recover() is False
    probe.assert_not_called()
    assert _status().status == InstanceStatus.CONFIGURING
    release.assert_not_called()


def test_expired_lock_still_recovers(make_instance, locks):
    # lock_superseded is False for a missing key, so recovery proceeds.
    make_instance()
    with patch.object(recovery, 'probe_host_runtime', return_value={'27960': _obs(True)}):
        assert _recover() is True
    assert _status().status == InstanceStatus.RUNNING


def test_none_lock_token_recovers_without_release(make_instance, locks):
    _, release = locks
    make_instance()
    with patch.object(recovery, 'probe_host_runtime', return_value={'27960': _obs(True)}):
        assert _recover(token=None) is True
    release.assert_not_called()


def test_non_transitional_instance_is_noop_without_probe(make_instance, locks):
    make_instance(InstanceStatus.RUNNING)
    with patch.object(recovery, 'probe_host_runtime') as probe:
        assert _recover() is False
    probe.assert_not_called()


def test_missing_instance_is_noop(app, locks):
    with app.app_context():
        db.create_all()
        assert _recover() is False


def test_releases_own_lock_after_recovery(make_instance, locks):
    _, release = locks
    make_instance()
    with patch.object(recovery, 'probe_host_runtime', return_value={'27960': _obs(True)}):
        _recover(token='tok-abc')
    release.assert_called_once_with('instance', 1, 'tok-abc')


NOW = datetime(2026, 10, 21, 16, 0, 0, tzinfo=timezone.utc)


def _job(heartbeat_age=None, started_age=600, handler=None, token='tok'):
    from ui.task_logic.job_failure_handlers import instance_job_failure_handler
    job = MagicMock()
    job.id = 'job-1'
    job.args = [1]
    job.meta = {'lock_token': token}
    job.failure_callback = handler or instance_job_failure_handler
    job.last_heartbeat = NOW - timedelta(seconds=heartbeat_age) if heartbeat_age is not None else None
    job.started_at = NOW - timedelta(seconds=started_age)
    return job


def _reconcile(*jobs):
    with patch.object(recovery, '_started_jobs', return_value=iter(jobs)):
        return reconcile_stale_instance_jobs(now=NOW)


def test_stale_job_is_recovered(make_instance, locks):
    make_instance()
    with patch.object(recovery, 'probe_host_runtime', return_value={'27960': _obs(True)}):
        assert _reconcile(_job(heartbeat_age=300)) == 1
    assert _status().status == InstanceStatus.RUNNING


def test_fresh_heartbeat_job_is_left_alone(make_instance, locks):
    make_instance()
    with patch.object(recovery, 'probe_host_runtime') as probe:
        assert _reconcile(_job(heartbeat_age=30)) == 0
    probe.assert_not_called()
    assert _status().status == InstanceStatus.CONFIGURING


def test_no_heartbeat_uses_started_at(make_instance, locks):
    make_instance()
    with patch.object(recovery, 'probe_host_runtime', return_value={'27960': _obs(True)}):
        assert _reconcile(_job(heartbeat_age=None, started_age=10)) == 0
        assert _reconcile(_job(heartbeat_age=None, started_age=600)) == 1


def test_job_with_other_failure_handler_is_ignored(make_instance, locks):
    from ui.task_logic.job_failure_handlers import host_job_failure_handler
    make_instance()
    assert _reconcile(_job(heartbeat_age=300, handler=host_job_failure_handler)) == 0
    assert _status().status == InstanceStatus.CONFIGURING


def test_second_run_is_noop(make_instance, locks):
    make_instance()
    stale = _job(heartbeat_age=300)
    with patch.object(recovery, 'probe_host_runtime', return_value={'27960': _obs(True)}) as probe:
        _reconcile(stale)
        _reconcile(stale)
    assert probe.call_count == 1


def test_vanished_job_is_skipped(app):
    queue = MagicMock()
    queue.started_job_registry.get_job_ids.return_value = ['gone']
    with patch.object(recovery.rq, 'get_queue', return_value=queue), \
            patch.object(recovery.Job, 'fetch', side_effect=recovery.NoSuchJobError('gone')):
        assert reconcile_stale_instance_jobs(now=NOW) == 0
