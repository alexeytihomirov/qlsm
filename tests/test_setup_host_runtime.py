"""Host setup rebuilds the host's own runtime on every run, forever."""
import json
from types import SimpleNamespace

import pytest
import yaml

from ui import db
from ui.models import Host, HostStatus
from ui.runtime import MINQLX, MINQLXTENDED


def _load_playbook(path):
    with open(path) as handle:
        return yaml.safe_load(handle)


def _flatten_tasks(tasks):
    """Recurse into `block:` tasks so a flat search sees everything a
    top-level task list search would if the file had no blocks at all."""
    flat = []
    for task in tasks:
        flat.append(task)
        if "block" in task:
            flat.extend(_flatten_tasks(task["block"]))
    return flat


def test_setup_playbook_defaults_to_minqlx():
    """A manual ansible-playbook run with no extra-vars must not silently
    switch an existing host's runtime."""
    play = _load_playbook("ansible/playbooks/setup_host.yml")[0]
    assert play["vars"]["runtime"] == "minqlx"


def test_setup_playbook_derives_paths_from_runtime():
    play = _load_playbook("ansible/playbooks/setup_host.yml")[0]
    text = json.dumps(play["vars"])
    assert "minqlxtended" in text
    assert "runtime_shared_dir" in play["vars"]
    assert "runtime_plugins_dirname" in play["vars"]


def test_setup_playbook_delegates_the_build_to_the_shared_engine_hook_task():
    """setup_host.yml and the manual rebuild_minqlx.yml both delegate the
    actual per-runtime build to tasks/build_engine_hook.yml (see
    test_setup_playbook_gates_both_build_paths below for the gating itself),
    so a re-run always picks the same shared logic up."""
    play = _load_playbook("ansible/playbooks/setup_host.yml")[0]
    includes = [t for t in play["tasks"] if t.get("include_tasks") == "tasks/build_engine_hook.yml"]
    assert includes, "expected setup_host.yml to include tasks/build_engine_hook.yml"


def test_setup_playbook_gates_both_build_paths():
    """Each of the three runtimes must set its own facts under a mutually
    exclusive `when`, or two flavors' `set_fact` could both fire (or none
    could) and the single shared clone task below would build the wrong
    engine, or the wrong version of it, on a re-run."""
    tasks = _flatten_tasks(_load_playbook("ansible/playbooks/tasks/build_engine_hook.yml"))
    fact_tasks = [t for t in tasks if t.get("set_fact", {}).get("_engine_repo")]
    assert len(fact_tasks) == 3, "expected one per-runtime fact-setting task"
    whens = " ".join(str(t.get("when", "")) for t in fact_tasks)
    assert "_engine_flavor == 'minqlx'" in whens
    assert "_engine_flavor == 'minqlxtended'" in whens
    assert "_engine_flavor == 'minqlxtended-patched'" in whens

    # The single shared clone task must be driven entirely by those facts, not
    # by a literal runtime name, or adding a 4th runtime here would silently
    # need a 4th clone task nobody remembered to add.
    clones = [t for t in tasks if "git" in t]
    assert len(clones) == 1, "expected exactly one runtime-agnostic clone task"
    assert clones[0]["git"]["repo"] == "{{ _engine_repo }}"
    assert clones[0]["git"]["version"] == "{{ _engine_git_version }}"


def test_minqlx_patches_never_apply_to_minqlxtended():
    """Both local C patches are obsolete on minqlxtended -- damage is a native
    event and reset_acc becomes pure Python. Neither variant of minqlxtended
    applies them; only the qlhub patch chain applies to minqlxtended-patched."""
    tasks = _flatten_tasks(_load_playbook("ansible/playbooks/tasks/build_engine_hook.yml"))
    patch_tasks = [t for t in tasks if "patch" in t.get("name", "").lower()
                   and "qlhub" not in t.get("name", "").lower()
                   and "set_fact" not in t]
    assert patch_tasks
    for task in patch_tasks:
        assert "_engine_apply_local_patches" in str(task.get("when", "")), task["name"]


@pytest.mark.parametrize("runtime,expected", [
    (MINQLX, "minqlx"),
    (MINQLXTENDED, "minqlxtended"),
    (None, "minqlx"),
])
def test_cloud_host_setup_passes_the_runtime(app, monkeypatch, runtime, expected):
    """Reaching the ansible-playbook Popen call also requires ssh_key_path,
    a "found" inventory snippet, and a mocked wait-for-SSH subprocess.run --
    see the equivalent _run_cloud_setup() helper in
    tests/test_host_setup_firewall_pool_flag.py for the same, already-working
    pattern."""
    import ui.task_logic.ansible_host_setup as mod

    with app.app_context():
        host = Host(name=f"setup-{expected}-{runtime}", provider="vultr",
                    ip_address="10.0.0.5", ssh_key_path="/key", ssh_user="ansible",
                    status=HostStatus.PROVISIONED_PENDING_SETUP)
        if runtime is not None:
            host.runtime = runtime
        db.session.add(host)
        db.session.commit()
        host_id = host.id

    captured = {}

    class FakeProcess:
        returncode = 0
        stdout = stderr = None

    def fake_popen(args, **kwargs):
        captured["args"] = args
        return FakeProcess()

    monkeypatch.setattr(mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(mod.subprocess, "run",
                         lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(mod.os.path, "exists", lambda path: True)
    monkeypatch.setattr("ui.task_logic.ansible_runner._stream_output", lambda p: ("", ""))
    monkeypatch.setattr(mod, "get_current_job", lambda: SimpleNamespace(id="job"))

    with app.app_context():
        try:
            mod.setup_host_ansible_logic(host_id)
        except Exception:
            pass

    joined = " ".join(captured.get("args", []))
    assert f'"runtime": "{expected}"' in joined or f"runtime={expected}" in joined


@pytest.mark.parametrize("runtime,expected", [
    (MINQLX, "minqlx"),
    (MINQLXTENDED, "minqlxtended"),
])
def test_standalone_setup_extra_vars_include_the_runtime(app, runtime, expected):
    from ui.task_logic.standalone_host_setup import _setup_playbook_extra_vars

    with app.app_context():
        host = Host(name=f"sa-{expected}", provider="standalone", ssh_port=22,
                    is_standalone=True, runtime=runtime)
        db.session.add(host)
        db.session.commit()
        assert _setup_playbook_extra_vars(host)["runtime"] == expected


def test_minqlxtended_requirements_pin_the_redis_floors():
    """Upstream needs redis>=5.1 and hiredis>=3.0; the bundled minqlx floor is
    a different, incompatible range."""
    with open("ql-assets/data/minqlxtended-plugins/requirements.txt") as handle:
        text = handle.read()
    assert "redis>=5.1" in text.replace(" ", "")
    assert "hiredis>=3.0" in text.replace(" ", "")
