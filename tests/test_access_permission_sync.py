import json
import shlex
import subprocess
import sys
import types
from types import SimpleNamespace

MODULE = "ui.task_logic.access_permission_sync"
ADMIN_A = "76561197999064274"
ADMIN_B = "76561198257351377"


def _host(provider="standalone"):
    return SimpleNamespace(id=1, name="germany-1", provider=provider, ip_address="91.99.3.72",
                           ssh_key_path="/keys/germany.pem", ssh_port=22, ssh_user="root")


def _instance(host=None):
    return SimpleNamespace(id=99, port=27965, redis_db=2, host=host)


def _remote_script(command):
    return shlex.split(command[-1])[2]


class FakeRedis:
    """Just enough redis-py for the remote write script: string keys plus
    scan_iter/delete. store is {db: {key: value}}."""

    store = {}

    def __init__(self, **kwargs):
        self.db = kwargs["db"]
        self.store.setdefault(self.db, {})

    def set(self, key, value):
        self.store[self.db][key] = value

    def scan_iter(self, match, count=None):
        prefix = match.rstrip("*")
        return [k.encode() for k in list(self.store[self.db]) if k.startswith(prefix)]

    def delete(self, key):
        self.store[self.db].pop(key.decode() if isinstance(key, bytes) else key, None)


def _run_script(monkeypatch, changes, seed=None):
    FakeRedis.store = {2: dict(seed or {})}
    fake_module = types.ModuleType("redis")
    fake_module.Redis = FakeRedis
    monkeypatch.setitem(sys.modules, "redis", fake_module)
    from ui.task_logic.access_permission_sync import _remote_write_script

    printed = []
    exec(_remote_write_script(changes, db=2, redis_password=None), {"__name__": "w", "print": printed.append})
    return FakeRedis.store[2], json.loads(printed[0])


def test_build_write_command_shape():
    from ui.task_logic.access_permission_sync import build_write_command

    command = build_write_command(_host(), 2, {ADMIN_A: 5})
    assert command[:2] == ["ssh", "-i"]
    assert command.count("91.99.3.72") == 1
    assert "ConnectTimeout=5" in command
    assert "db=2" in _remote_script(command)


def test_writes_only_the_changed_keys(monkeypatch):
    """An admin set in-game with !setperm is not in the changes and must stay."""
    store, result = _run_script(
        monkeypatch, {ADMIN_A: 4, ADMIN_B: 0},
        seed={f"minqlx:players:{ADMIN_B}:permission": "3", "minqlx:players:76561198000000009:permission": "5"},
    )
    assert store[f"minqlx:players:{ADMIN_A}:permission"] == "4"
    assert store[f"minqlx:players:{ADMIN_B}:permission"] == "0"
    assert store["minqlx:players:76561198000000009:permission"] == "5"
    assert result == {"written": [ADMIN_A, ADMIN_B]}


def test_deletes_legacy_managed_admin_sets(monkeypatch):
    store, _ = _run_script(monkeypatch, {ADMIN_A: 5}, seed={
        "minqlx:qlsm:managed_admins": "x", "minqlx:qlsm:managed_admins:99": "x",
    })
    assert not any(key.startswith("minqlx:qlsm:managed_admins") for key in store)


def test_no_host_or_no_changes_is_a_noop(monkeypatch):
    from ui.task_logic import access_permission_sync as module

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    assert module.write_admin_levels(_instance(host=None), {ADMIN_A: 5}) is None
    assert module.write_admin_levels(_instance(host=_host()), {}) is None
    assert module.write_admin_levels(_instance(host=_host()), None) is None


def test_self_host_passes_the_redis_password_base64_encoded(monkeypatch):
    from ui.task_logic import access_permission_sync as module

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout=json.dumps({"written": [ADMIN_A]}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(module, "resolve_self_host_management_target", lambda: "10.0.0.5")
    monkeypatch.setenv("REDIS_PASSWORD", "secret-pw")

    assert module.write_admin_levels(_instance(host=_host("self")), {ADMIN_A: 5}) == {"written": [ADMIN_A]}
    script = _remote_script(captured["command"])
    assert "secret-pw" not in script
    assert "password_b64" in script


def test_failed_round_trip_returns_false(monkeypatch):
    from ui.task_logic import access_permission_sync as module

    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="refused"))
    assert module.write_admin_levels(_instance(host=_host()), {ADMIN_A: 5}) is False

    def raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ssh", timeout=10)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    assert module.write_admin_levels(_instance(host=_host()), {ADMIN_A: 5}) is False


def test_report_wrapper_never_raises_even_if_logging_fails(monkeypatch):
    import ui.task_logic.access_permission_sync as mod

    monkeypatch.setattr(mod, "write_admin_levels", lambda instance, changes: False)
    monkeypatch.setattr(mod, "append_log", lambda i, m: (_ for _ in ()).throw(RuntimeError("log")))
    rollbacks = []
    monkeypatch.setattr(mod.db.session, "rollback", lambda: rollbacks.append(True))

    assert mod.write_and_report_admin_levels(_instance(host=_host()), {ADMIN_A: 5}) is False
    assert rollbacks
