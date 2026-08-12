import yaml
from pathlib import Path

PLAYBOOKS = Path(__file__).resolve().parent.parent / "ansible" / "playbooks"


def _load_tasks(playbook_name):
    with open(PLAYBOOKS / playbook_name) as f:
        plays = yaml.safe_load(f)
    return plays[0]["tasks"]


def _find_task(tasks, name):
    for task in tasks:
        if task.get("name") == name:
            return task
    raise AssertionError(f"task not found: {name}")


def test_manage_service_disables_on_stop_enables_otherwise():
    tasks = _load_tasks("manage_qlds_service.yml")
    task = _find_task(tasks, "Ensure QLDS service state is managed (start/stop/restart)")
    systemd = task["ansible.builtin.systemd"]
    assert "enabled" in systemd, "manage task must set systemd 'enabled'"
    # Pin BOTH branches of the expression, not just a substring: a regressed
    # else-branch like "'no' if service_state == 'stopped' else 'no'" would wrongly
    # disable the unit on start yet still pass a substring check. Normalize internal
    # whitespace so formatting differences don't matter.
    normalized = " ".join(systemd["enabled"].split())
    assert normalized == "{{ 'no' if service_state == 'stopped' else 'yes' }}", (
        "enabled must disable on stop and enable on everything else; "
        f"got: {systemd['enabled']!r}"
    )


def test_sync_restart_enables_unit():
    tasks = _load_tasks("sync_instance_configs_and_restart.yml")
    task = _find_task(tasks, "Restart QLDS service")
    systemd = task["ansible.builtin.systemd"]
    assert systemd.get("enabled") is True, "restart task must re-enable the unit"


def test_hook_path_cleanup_runs_regardless_of_firewall_mode():
    """Standalone/self hosts run in 'helper' firewall mode (see
    uses_helper_firewall() in self_host_network.py), never 'full'. Gating
    legacy-NAT-rule cleanup on firewall_mode_effective == 'full' means it
    silently never runs for them, leaving a stale PREROUTING DNAT rule that
    black-holes all inbound game traffic once route_localnet isn't enabled
    on the real NIC (see: Slaughterhouse incident, 2026-08-12). This must
    stay mode-agnostic like update_instance_hooks.yml's equivalent cleanup.
    """
    tasks = _load_tasks("manage_qlds_service.yml")
    for name in (
        "Check if PREROUTING DNAT legacy rule exists (hook path cleanup)",
        "Remove PREROUTING DNAT legacy rule (hook path cleanup)",
        "Check if POSTROUTING SNAT legacy rule exists (hook path cleanup)",
        "Remove POSTROUTING SNAT legacy rule (hook path cleanup)",
        "Check if INPUT SNAT legacy rule exists (hook path cleanup)",
        "Remove INPUT SNAT legacy rule (hook path cleanup)",
    ):
        task = _find_task(tasks, name)
        when = task["when"]
        assert "firewall_mode_effective == 'full'" not in when, (
            f"{name!r} must not require full firewall mode: {when}"
        )
        assert any("lan_rate_uses_hook" in cond for cond in when), (
            f"{name!r} must still gate on lan_rate_uses_hook: {when}"
        )

    persist = _find_task(tasks, "Persist iptables after legacy rule cleanup (hook path)")
    assert "firewall_mode_effective == 'full'" not in persist["when"]
