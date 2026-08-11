from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ui import create_app
from ui.models import Host, InstanceStatus, QLInstance
from ui.task_logic import ansible_instance_mgmt, service_runtime
from ui.task_logic.ansible_runner import SimpleAnsibleResult
from ui.tasks import apply_instance_config


@pytest.fixture(scope="module")
def test_app():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "RCON_ENABLED": False,
    })
    with app.app_context():
        yield app


def _make_mock_instance(status=InstanceStatus.RUNNING, runtime_invocation_id=None):
    host = MagicMock(spec=Host)
    host.name = "test-host"
    host.provider = "vultr"

    instance = MagicMock(spec=QLInstance)
    instance.id = 12
    instance.port = 27960
    instance.status = status
    instance.host = host
    instance.lan_rate_enabled = False
    instance.ld_preload_hooks = None
    instance.runtime_invocation_id = runtime_invocation_id
    return instance


@pytest.fixture
def configured_apply(monkeypatch):
    def configure(instance):
        session = MagicMock()
        session.get.return_value = instance
        monkeypatch.setattr(ansible_instance_mgmt.db, "session", session)
        monkeypatch.setattr(
            ansible_instance_mgmt,
            "get_current_job",
            MagicMock(return_value=SimpleNamespace(id="test-job-id")),
        )
        monkeypatch.setattr(ansible_instance_mgmt, "append_log", MagicMock())
        monkeypatch.setattr(ansible_instance_mgmt, "_prepare_instance_zmq", MagicMock())
        monkeypatch.setattr(
            ansible_instance_mgmt,
            "ensure_instance_cpu_affinity",
            MagicMock(return_value=1),
        )
        monkeypatch.setattr(
            ansible_instance_mgmt,
            "_build_qlds_args_string",
            MagicMock(return_value="mock_qlds_args"),
        )
        monkeypatch.setattr(
            ansible_instance_mgmt,
            "_run_ansible_playbook",
            MagicMock(return_value=(SimpleAnsibleResult(0, "ok", ""), None)),
        )
        return session

    return configure


def test_no_restart_save_stores_post_sync_invocation_id(
    monkeypatch, configured_apply, test_app
):
    """A deferred save records the runtime identity that existed after sync."""
    instance = _make_mock_instance()
    session = configured_apply(instance)
    commits = []
    session.commit.side_effect = lambda: commits.append(
        (instance.status, instance.runtime_invocation_id)
    )
    probe = MagicMock(return_value="b" * 32)
    monkeypatch.setattr(service_runtime, "probe_instance_invocation_id", probe)

    result = apply_instance_config(12, restart=False)

    assert result == "Instance 12 config application successful. Status: updated"
    assert instance.status == InstanceStatus.UPDATED
    assert instance.runtime_invocation_id == "b" * 32
    assert commits[-1] == (InstanceStatus.UPDATED, "b" * 32)
    probe.assert_called_once_with(instance)


def test_no_restart_save_clears_stale_baseline_when_probe_fails(
    monkeypatch, configured_apply, test_app
):
    """An unusable deferred-save probe clears a baseline from an older run."""
    instance = _make_mock_instance(runtime_invocation_id="a" * 32)
    session = configured_apply(instance)
    commits = []
    session.commit.side_effect = lambda: commits.append(
        (instance.status, instance.runtime_invocation_id)
    )
    probe = MagicMock(return_value=None)
    monkeypatch.setattr(service_runtime, "probe_instance_invocation_id", probe)

    result = apply_instance_config(12, restart=False)

    assert result == "Instance 12 config application successful. Status: updated"
    assert instance.status == InstanceStatus.UPDATED
    assert instance.runtime_invocation_id is None
    assert commits[-1] == (InstanceStatus.UPDATED, None)
    probe.assert_called_once_with(instance)


def test_no_restart_save_clears_baseline_and_succeeds_when_probe_raises(
    monkeypatch, configured_apply, test_app
):
    """A probe exception cannot turn a successful deferred save into an error."""
    instance = _make_mock_instance(runtime_invocation_id="a" * 32)
    session = configured_apply(instance)
    commits = []
    session.commit.side_effect = lambda: commits.append(
        (instance.status, instance.runtime_invocation_id)
    )
    probe = MagicMock(side_effect=OSError("runtime unavailable"))
    monkeypatch.setattr(service_runtime, "probe_instance_invocation_id", probe)
    app = MagicMock()
    monkeypatch.setattr(ansible_instance_mgmt, "current_app", app)

    result = apply_instance_config(12, restart=False)

    assert result == "Instance 12 config application successful. Status: updated"
    assert instance.status == InstanceStatus.UPDATED
    assert instance.runtime_invocation_id is None
    assert commits[-1] == (InstanceStatus.UPDATED, None)
    probe.assert_called_once_with(instance)
    app.logger.warning.assert_any_call(
        "Configuration synced, but runtime baseline capture failed for instance %s",
        12,
        exc_info=True,
    )


def test_restart_save_does_not_wait_for_baseline_probe(
    monkeypatch, configured_apply, test_app
):
    """Managed restarts preserve the fast, existing RUNNING completion path."""
    instance = _make_mock_instance()
    configured_apply(instance)
    probe = MagicMock(side_effect=AssertionError("restart path must not probe"))
    monkeypatch.setattr(service_runtime, "probe_instance_invocation_id", probe)

    result = apply_instance_config(12, restart=True)

    assert result == "Instance 12 config application successful. Status: running"
    assert instance.status == InstanceStatus.RUNNING
    probe.assert_not_called()


def test_stopped_no_restart_save_does_not_probe_runtime(
    monkeypatch, configured_apply, test_app
):
    """A deferred save that leaves a server stopped has no runtime baseline."""
    instance = _make_mock_instance(status=InstanceStatus.STOPPED)
    configured_apply(instance)
    probe = MagicMock(side_effect=AssertionError("stopped path must not probe"))
    monkeypatch.setattr(service_runtime, "probe_instance_invocation_id", probe)

    result = apply_instance_config(12, restart=False)

    assert result == "Instance 12 config application successful. Status: stopped"
    assert instance.status == InstanceStatus.STOPPED
    probe.assert_not_called()
