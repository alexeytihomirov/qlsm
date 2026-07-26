"""`Host.firewall_pool_v2` records that a host's firewall was rendered with the
current game/RCON port pool from ui/constants.py.

The UI drives its "re-run host setup" advisory off this flag, so a run that
failed part-way must leave it alone -- otherwise a host with a stale, narrower
allow-list would silently stop advertising that it needs the re-run.
"""

from unittest.mock import MagicMock, patch

import pytest

from ui import db
from ui.models import Host, HostStatus

CLOUD_MODULE = "ui.task_logic.ansible_host_setup"
STANDALONE_MODULE = "ui.task_logic.standalone_host_setup"
COMMON_HELPER = "ui.task_logic.common._reconcile_host_instances_after_setup"


def _build_host(app, *, provider, status):
    with app.app_context():
        host = Host(
            name=f"{provider}-firewall-pool-host",
            provider=provider,
            os_type="debian",
            ip_address="1.2.3.4",
            ssh_key_path="/key",
            ssh_user="ansible",
            status=status,
            is_standalone=provider in ("standalone", "self"),
        )
        db.session.add(host)
        db.session.commit()
        assert host.firewall_pool_v2 is False
        return host.id


def _run_cloud_setup(app, host_id, *, rerun=False, returncode=0):
    process = MagicMock(returncode=returncode)
    with patch(f"{CLOUD_MODULE}.get_current_job", return_value=MagicMock(id="job")), \
         patch(f"{CLOUD_MODULE}.os.path.exists", return_value=True), \
         patch(f"{CLOUD_MODULE}.subprocess.run"), \
         patch(f"{CLOUD_MODULE}.subprocess.Popen", return_value=process), \
         patch(
             "ui.task_logic.ansible_runner._stream_output",
             return_value=("stdout ok", ""),
         ):
        with app.app_context():
            from ui.task_logic.ansible_host_setup import setup_host_ansible_logic
            return setup_host_ansible_logic(host_id, rerun=rerun)


def _run_standalone_setup(app, host_id, *, rerun=False, playbook_ok=True):
    with patch(f"{STANDALONE_MODULE}.get_current_job", return_value=MagicMock(id="job")), \
         patch(
             f"{STANDALONE_MODULE}._generate_standalone_inventory",
             return_value=("/tmp/inventory.yml", "1.2.3.4"),
         ), \
         patch(f"{STANDALONE_MODULE}._wait_for_ssh", return_value=True), \
         patch(f"{STANDALONE_MODULE}._run_setup_playbook", return_value=playbook_ok):
        with app.app_context():
            from ui.task_logic.standalone_host_setup import setup_standalone_host_logic
            return setup_standalone_host_logic(host_id, rerun=rerun)


def _flag(app, host_id):
    with app.app_context():
        return db.session.get(Host, host_id).firewall_pool_v2


def test_new_host_starts_on_the_legacy_firewall_pool(app):
    """Existing rows genuinely have the older, narrower allow-list."""
    host_id = _build_host(app, provider="vultr", status=HostStatus.PROVISIONED_PENDING_SETUP)

    assert _flag(app, host_id) is False


def test_initial_cloud_setup_marks_the_firewall_pool_current(app):
    host_id = _build_host(app, provider="vultr", status=HostStatus.PROVISIONED_PENDING_SETUP)

    result = _run_cloud_setup(app, host_id)

    assert "Status: ACTIVE" in result
    assert _flag(app, host_id) is True


def test_rerun_cloud_setup_marks_the_firewall_pool_current(app):
    """The re-run is the documented migration for hosts set up before the pool
    widened, so it is the path that most needs to clear the advisory."""
    host_id = _build_host(app, provider="vultr", status=HostStatus.CONFIGURING)

    with patch(COMMON_HELPER, return_value=(0, 0)):
        result = _run_cloud_setup(app, host_id, rerun=True)

    assert "Status: ACTIVE" in result
    assert _flag(app, host_id) is True


def test_failed_cloud_setup_leaves_the_firewall_pool_flag_unset(app):
    host_id = _build_host(app, provider="vultr", status=HostStatus.PROVISIONED_PENDING_SETUP)

    result = _run_cloud_setup(app, host_id, returncode=2)

    assert "Error during Ansible host setup" in result
    with app.app_context():
        host = db.session.get(Host, host_id)
        assert host.status == HostStatus.ERROR
        assert host.firewall_pool_v2 is False


@pytest.mark.parametrize("provider", ["standalone", "self"])
def test_helper_host_setup_marks_the_firewall_pool_current(app, provider):
    host_id = _build_host(app, provider=provider, status=HostStatus.PROVISIONED_PENDING_SETUP)

    result = _run_standalone_setup(app, host_id)

    assert "Status: ACTIVE" in result
    assert _flag(app, host_id) is True


def test_failed_helper_host_setup_leaves_the_firewall_pool_flag_unset(app):
    host_id = _build_host(app, provider="standalone", status=HostStatus.PROVISIONED_PENDING_SETUP)

    result = _run_standalone_setup(app, host_id, playbook_ok=False)

    assert "Error during Ansible host setup" in result
    assert _flag(app, host_id) is False
