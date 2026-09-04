import json
import os
import shlex
import subprocess
import sys
import types
from types import SimpleNamespace

import pytest


MODULE = "ui.task_logic.access_permission_sync"


def _host(provider="standalone", name="germany-1"):
    return SimpleNamespace(
        id=1,
        name=name,
        provider=provider,
        ip_address="91.99.3.72",
        ssh_key_path="/keys/germany.pem",
        ssh_port=22,
        ssh_user="root",
    )


def _instance(port=27965, redis_db=2, host=None):
    return SimpleNamespace(id=99, port=port, redis_db=redis_db, host=host)


def _remote_script(command):
    return shlex.split(command[-1])[2]


class FakeRedis:
    """In-memory stand-in with just enough of the redis-py surface the
    remote sync script uses: get/set strings, and a SET via smembers/srem/sadd."""

    store = {}
    sets = {}

    def __init__(self, **kwargs):
        self.db = kwargs["db"]
        FakeRedis.last_kwargs = kwargs
        self.store.setdefault(self.db, {})
        self.sets.setdefault(self.db, set())

    def set(self, key, value):
        self.store[self.db][key] = value

    def smembers(self, key):
        return {v.encode() for v in self.sets[self.db]}

    def srem(self, key, *values):
        for v in values:
            self.sets[self.db].discard(v)

    def sadd(self, key, *values):
        self.sets[self.db].update(values)


def _install_fake_redis(monkeypatch):
    FakeRedis.store = {}
    FakeRedis.sets = {}
    fake_module = types.ModuleType("redis")
    fake_module.Redis = FakeRedis
    monkeypatch.setitem(sys.modules, "redis", fake_module)
    return FakeRedis


# --- parse_access_entries -------------------------------------------------

def test_parse_access_entries_matches_frontend_shape():
    from ui.task_logic.access_permission_sync import parse_access_entries

    text = "\n".join([
        "# comment line",
        "",
        "76561197999064274|5",
        "76561198257351377|3",
        "not-a-steamid|5",
        "76561197999064274|4  # last line for a dupe wins",
    ])
    entries = parse_access_entries(text)

    assert entries == {"76561197999064274": 4, "76561198257351377": 3}


def test_parse_access_entries_defaults_and_clamps_level():
    from ui.task_logic.access_permission_sync import parse_access_entries

    entries = parse_access_entries("76561197999064274|\n76561198257351377|99\n")

    assert entries["76561197999064274"] == 5  # missing level -> UI default
    assert entries["76561198257351377"] == 5  # clamped to max


def test_parse_access_entries_empty_input():
    from ui.task_logic.access_permission_sync import parse_access_entries

    assert parse_access_entries("") == {}
    assert parse_access_entries(None) == {}


# --- build_sync_command ----------------------------------------------------

def test_build_sync_command_shape():
    from ui.task_logic.access_permission_sync import build_sync_command

    command = build_sync_command(_host(), 2, {"76561197999064274": 5})
    script = _remote_script(command)

    assert command[:2] == ["ssh", "-i"]
    assert command.count("91.99.3.72") == 1
    assert "ConnectTimeout=5" in command
    assert "db=2" in script
    assert "minqlx:qlsm:managed_admins" in script


# --- remote script behaviour (executed against FakeRedis) -----------------

def test_remote_script_upserts_then_resets_removed_admin(monkeypatch):
    from ui.task_logic.access_permission_sync import _remote_sync_script

    fake_redis = _install_fake_redis(monkeypatch)

    printed = []
    script_v1 = _remote_sync_script(
        {"76561197999064274": 5, "76561198257351377": 3}, db=2, redis_password=None
    )
    exec(script_v1, {"__name__": "sync", "print": printed.append})

    assert fake_redis.store[2]["minqlx:players:76561197999064274:permission"] == "5"
    assert fake_redis.store[2]["minqlx:players:76561198257351377:permission"] == "3"
    assert fake_redis.sets[2] == {"76561197999064274", "76561198257351377"}
    result_v1 = json.loads(printed[0])
    assert sorted(result_v1["synced"]) == ["76561197999064274", "76561198257351377"]
    assert result_v1["reset"] == []

    # Second sync: one admin removed from access.txt -> must reset to 0,
    # the other's grant (potentially changed by hand via !setperm) untouched
    # except for the upsert this sync itself performs.
    printed.clear()
    script_v2 = _remote_sync_script({"76561197999064274": 5}, db=2, redis_password=None)
    exec(script_v2, {"__name__": "sync", "print": printed.append})

    assert fake_redis.store[2]["minqlx:players:76561197999064274:permission"] == "5"
    assert fake_redis.store[2]["minqlx:players:76561198257351377:permission"] == "0"
    assert fake_redis.sets[2] == {"76561197999064274"}
    result_v2 = json.loads(printed[0])
    assert result_v2["synced"] == ["76561197999064274"]
    assert result_v2["reset"] == ["76561198257351377"]


def test_remote_script_never_resets_ids_it_did_not_previously_manage(monkeypatch):
    """A permission granted by hand via !setperm, outside access.txt entirely,
    must never be reset just because it's not in the managed set."""
    from ui.task_logic.access_permission_sync import _remote_sync_script

    fake_redis = _install_fake_redis(monkeypatch)
    fake_redis.store[2] = {"minqlx:players:76561199000000000:permission": "5"}
    fake_redis.sets[2] = set()  # never synced via this mechanism

    printed = []
    script = _remote_sync_script({"76561197999064274": 5}, db=2, redis_password=None)
    exec(script, {"__name__": "sync", "print": printed.append})

    assert fake_redis.store[2]["minqlx:players:76561199000000000:permission"] == "5"
    assert json.loads(printed[0])["reset"] == []


# --- sync_access_permissions (subprocess boundary) --------------------------

def test_sync_access_permissions_returns_none_without_host():
    from ui.task_logic.access_permission_sync import sync_access_permissions

    assert sync_access_permissions(_instance(host=None), "76561197999064274|5") is None


def test_sync_access_permissions_uses_self_host_redis_password(monkeypatch):
    from ui.task_logic import access_permission_sync as module

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout=json.dumps({"synced": [], "reset": []}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(module, "resolve_self_host_management_target", lambda: "10.0.0.5")
    monkeypatch.setenv("REDIS_PASSWORD", "secret-pw")

    instance = _instance(host=_host(provider="self"))
    result = module.sync_access_permissions(instance, "76561197999064274|5")

    assert result == {"synced": [], "reset": []}
    script = _remote_script(captured["command"])
    assert "secret-pw" not in script  # only present base64-encoded
    assert "password_b64" in script


def test_sync_access_permissions_returns_none_on_nonzero_exit(monkeypatch):
    from ui.task_logic import access_permission_sync as module

    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="connection refused"),
    )
    result = module.sync_access_permissions(_instance(host=_host()), "76561197999064274|5")
    assert result is None


def test_sync_access_permissions_returns_none_on_timeout(monkeypatch):
    from ui.task_logic import access_permission_sync as module

    def raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ssh", timeout=10)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    result = module.sync_access_permissions(_instance(host=_host()), "76561197999064274|5")
    assert result is None


# --- sync_instance_access_permissions (disk read wrapper) -------------------

def test_sync_instance_access_permissions_reads_configured_access_txt(tmp_path, monkeypatch):
    from ui.task_logic import access_permission_sync as module

    monkeypatch.chdir(tmp_path)
    host = _host(name="germany-1")
    instance = _instance(host=host)
    config_dir = tmp_path / "configs" / host.name / str(instance.id)
    config_dir.mkdir(parents=True)
    (config_dir / "access.txt").write_text("76561197999064274|5\n")

    captured = {}

    def fake_sync(inst, text):
        captured["instance"] = inst
        captured["text"] = text
        return {"synced": ["76561197999064274"], "reset": []}

    monkeypatch.setattr(module, "sync_access_permissions", fake_sync)

    result = module.sync_instance_access_permissions(instance)

    assert result == {"synced": ["76561197999064274"], "reset": []}
    assert captured["text"] == "76561197999064274|5\n"


def test_sync_instance_access_permissions_no_op_without_file(tmp_path, monkeypatch):
    from ui.task_logic import access_permission_sync as module

    monkeypatch.chdir(tmp_path)
    instance = _instance(host=_host())

    assert module.sync_instance_access_permissions(instance) is None


def test_sync_instance_access_permissions_no_op_without_host():
    from ui.task_logic.access_permission_sync import sync_instance_access_permissions

    instance = _instance(host=None)
    assert sync_instance_access_permissions(instance) is None
