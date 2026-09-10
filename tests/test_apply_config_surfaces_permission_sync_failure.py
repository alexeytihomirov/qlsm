"""apply_instance_config_logic must surface a failed access.txt permission
sync to the operator instead of silently reporting the config apply as fully
successful -- see access_permission_sync.sync_access_permissions, which
returns False (not None) when the SSH/Redis round-trip actually failed."""
from types import SimpleNamespace

import pytest

from ui import db
from ui.models import Host, InstanceStatus, QLInstance
from ui.task_logic import ansible_instance_mgmt as mod


@pytest.fixture
def instance_in_db(app, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CONFIGS_BASE", str(tmp_path / "configs"), raising=False)
    with app.app_context():
        host = Host(name="test-host", provider="vultr", ip_address="10.0.0.1")
        db.session.add(host)
        db.session.flush()
        inst = QLInstance(
            name="ti", port=27960, hostname="hn", host_id=host.id, qlx_plugins="",
            status=InstanceStatus.RUNNING,
            zmq_rcon_port=28888, zmq_rcon_password="x",
            zmq_stats_port=29999, zmq_stats_password="y",
        )
        db.session.add(inst)
        db.session.commit()
        yield inst


def _mock_successful_run(instance, playbook, extravars=None):
    return SimpleNamespace(rc=0, status="successful", stdout=lambda: "", _stdout="", _stderr=""), None


@pytest.fixture(autouse=True)
def _stub_ansible(monkeypatch):
    monkeypatch.setattr(mod, "_run_ansible_playbook", _mock_successful_run)
    monkeypatch.setattr(mod, "_prepare_instance_zmq", lambda inst: None)
    monkeypatch.setattr(mod, "ensure_instance_cpu_affinity", lambda inst: None)
    monkeypatch.setattr(mod, "with_self_host_network_extravars", lambda inst, e: e)
    monkeypatch.setattr(mod, "get_current_job", lambda: SimpleNamespace(id="test-job"))


def test_apply_config_warns_operator_when_permission_sync_fails(app, instance_in_db, monkeypatch):
    from ui.task_logic import access_permission_sync

    monkeypatch.setattr(access_permission_sync, "sync_instance_access_permissions", lambda inst: False)

    with app.app_context():
        mod.apply_instance_config_logic(instance_in_db.id)
        refreshed = db.session.get(QLInstance, instance_in_db.id)
        assert "could not be synced" in refreshed.logs


def test_apply_config_stays_quiet_when_nothing_to_sync(app, instance_in_db, monkeypatch):
    from ui.task_logic import access_permission_sync

    # No access.txt on disk at all -- a legitimate no-op, not a failure.
    monkeypatch.setattr(access_permission_sync, "sync_instance_access_permissions", lambda inst: None)

    with app.app_context():
        mod.apply_instance_config_logic(instance_in_db.id)
        refreshed = db.session.get(QLInstance, instance_in_db.id)
        assert "could not be synced" not in refreshed.logs
