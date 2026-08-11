import json
import io
import os
import shlex
import subprocess
import sys
import time
import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest


MODULE = "ui.task_logic.service_runtime"


def _host(provider="standalone", ip_address="203.0.113.10"):
    return SimpleNamespace(
        id=1,
        name="runtime-host",
        provider=provider,
        ip_address=ip_address,
        ssh_key_path="/keys/runtime.pem",
        ssh_port=22,
        ssh_user="ql",
    )


def _instance(port=27960, redis_db=None, host=None):
    return SimpleNamespace(id=port, port=port, redis_db=redis_db, host=host)


def _remote_script(command):
    return shlex.split(command[-1])[2]


def _observation_payload(**overrides):
    payload = {
        "status": {"map": "campgrounds", "updated": 1_786_320_010},
        "active_state": "active",
        "invocation_id": "A" * 32,
        "service_started_at": 1_786_320_000,
    }
    payload.update(overrides)
    return payload


def test_build_probe_covers_all_port_db_pairs_with_one_bounded_ssh_command():
    """Dropping a port, DB, timeout, or unit from one host probe is a bug."""
    from ui.task_logic.service_runtime import build_runtime_probe_command

    command = build_runtime_probe_command(
        _host(), [_instance(27960), _instance(27961, redis_db=7)]
    )
    script = _remote_script(command)

    assert command[:2] == ["ssh", "-i"]
    assert command.count("203.0.113.10") == 1
    assert "ConnectTimeout=3" in command
    assert "ports_dbs = [(27960, 1), (27961, 7)]" in script
    assert script.count("subprocess.run(") == 1
    assert "systemctl" in script and "show" in script
    assert "qlds@{port}.service" in script
    assert "socket_connect_timeout=1" in script
    assert "socket_timeout=1" in script
    assert "ThreadPoolExecutor(max_workers=min(8, len(ports_dbs)))" in script
    assert "multiprocessing.Process" in script
    assert "worker.kill()" in script
    assert "timeout=5" in script


def test_remote_probe_bounds_redis_and_preserves_partial_systemd_sibling(monkeypatch):
    """A Redis timeout and missing unit must not hide a partial active sibling."""
    from ui.task_logic.service_runtime import (
        build_runtime_probe_command,
        parse_runtime_probe_output,
    )

    redis_calls, systemctl_calls, printed = [], [], []
    fake_redis = types.ModuleType("redis")

    class FakeRedis:
        def __init__(self, **kwargs):
            self.db = kwargs["db"]
            redis_calls.append(kwargs)

        def get(self, key):
            if self.db == 2:
                raise TimeoutError("read deadline")
            return b'{"map":"campgrounds","updated":1786320010}'

    def fake_systemctl(command, **kwargs):
        systemctl_calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=1,
            stdout=(
                "Id=qlds@27960.service\nActiveState=active\n"
                f"InvocationID={'A' * 32}\nActiveEnterTimestampMonotonic=1000000\n"
            ),
            stderr="qlds@27961.service not found",
        )

    fake_redis.Redis = FakeRedis
    monkeypatch.setitem(sys.modules, "redis", fake_redis)
    monkeypatch.setattr(subprocess, "run", fake_systemctl)
    command = build_runtime_probe_command(_host(), [_instance(27960), _instance(27961)])

    exec(
        _remote_script(command),
        {"__name__": "runtime_probe", "open": lambda *_args, **_kwargs: io.StringIO("10.0 0.0"), "print": printed.append},
    )

    observations = parse_runtime_probe_output(printed[0])
    assert observations["27960"].status["map"] == "campgrounds"
    assert observations["27960"].invocation_id == "a" * 32
    assert observations["27961"].status is None
    assert observations["27961"].invocation_id is None
    assert len(systemctl_calls) == 1
    assert systemctl_calls[0][0][2:4] == ["qlds@27960.service", "qlds@27961.service"]
    assert systemctl_calls[0][1]["timeout"] == 5
    assert all(call["socket_connect_timeout"] == call["socket_timeout"] == 1 for call in redis_calls)


def test_remote_probe_process_exits_after_redis_deadline_with_blocking_worker(tmp_path):
    """A blocking Redis worker cannot keep the completed remote probe interpreter alive."""
    from ui.task_logic.service_runtime import build_runtime_probe_command

    (tmp_path / "redis.py").write_text(
        "import time\n"
        "class Redis:\n"
        "    def __init__(self, **kwargs): self.db = kwargs['db']\n"
        "    def get(self, key):\n"
        "        if self.db == 2: time.sleep(5)\n"
        "        return b'{\"map\": \"campgrounds\"}'\n"
    )
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(
        "#!/bin/sh\n"
        "printf 'Id=qlds@27960.service\\nActiveState=active\\n'\n"
        "printf 'InvocationID=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n'\n"
        "printf 'ActiveEnterTimestampMonotonic=1000000\\n'\n"
        "exit 1\n"
    )
    systemctl.chmod(0o755)
    command = build_runtime_probe_command(_host(), [_instance(27960), _instance(27961)])
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "PYTHONPATH": str(tmp_path),
    }
    started_at = time.monotonic()
    process = subprocess.Popen(
        [sys.executable, "-c", _remote_script(command)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )

    try:
        stdout, stderr = process.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        pytest.fail("blocking Redis worker kept the remote probe alive past its deadline")

    assert time.monotonic() - started_at < 2.5
    assert process.returncode == 0, stderr
    assert json.loads(stdout)["27960"]["status"] == {"map": "campgrounds"}


def test_remote_probe_rejects_status_stale_after_suspend_offset(monkeypatch):
    """Suspend-inclusive uptime must not make an old Redis payload look fresh."""
    from ui.task_logic.service_runtime import (
        build_runtime_probe_command,
        observation_has_fresh_status,
        parse_runtime_probe_output,
    )

    printed = []
    fake_redis = types.ModuleType("redis")
    fake_time = types.ModuleType("time")
    fake_time.monotonic = lambda: 200
    fake_time.time = lambda: 1000

    class FakeRedis:
        def __init__(self, **kwargs):
            pass

        def get(self, key):
            return b'{"updated": 900}'

    def fake_systemctl(command, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "Id=qlds@27960.service\nActiveState=active\n"
                f"InvocationID={'a' * 32}\nActiveEnterTimestampMonotonic=150000000\n"
            ),
            stderr="",
        )

    fake_redis.Redis = FakeRedis
    monkeypatch.setitem(sys.modules, "redis", fake_redis)
    monkeypatch.setitem(sys.modules, "time", fake_time)
    monkeypatch.setattr(subprocess, "run", fake_systemctl)
    command = build_runtime_probe_command(_host(), [_instance(27960)])

    exec(
        _remote_script(command),
        {"__name__": "runtime_probe", "open": lambda *_args, **_kwargs: io.StringIO("300.0 0.0"), "print": printed.append},
    )

    observation = parse_runtime_probe_output(printed[0])["27960"]

    assert observation.service_started_at == 950
    assert observation_has_fresh_status(observation) is False


def test_build_probe_uses_self_host_target_and_never_exposes_plaintext_password(monkeypatch):
    """A self-host probe must reach its management target without leaking secrets."""
    from ui.task_logic import service_runtime

    monkeypatch.setattr(
        service_runtime, "resolve_self_host_management_target", lambda: "host.docker.internal"
    )
    command = service_runtime.build_runtime_probe_command(
        _host(provider="self"), [_instance()], redis_password='p@$$"word'
    )

    assert "host.docker.internal" in command
    assert "203.0.113.10" not in command
    assert 'p@$$"word' not in " ".join(command)
    assert "base64.b64decode" in _remote_script(command)


@pytest.mark.parametrize(
    "port, redis_db",
    [(True, None), ("27960", None), (27960.5, None), ("not-a-port", None), (27960, 2.5), (27960, 0)],
)
def test_build_probe_rejects_non_integer_ports_and_invalid_redis_databases(port, redis_db):
    """Unvalidated identifiers could create unsafe systemd unit names."""
    from ui.task_logic.service_runtime import build_runtime_probe_command

    with pytest.raises(ValueError):
        build_runtime_probe_command(_host(), [_instance(port, redis_db)])


def test_parse_runtime_probe_output_returns_active_identity_and_whole_second_start():
    """A good remote observation must retain both the live status and usable identity."""
    from ui.task_logic.service_runtime import parse_runtime_probe_output

    observations = parse_runtime_probe_output(
        json.dumps({"27960": _observation_payload()})
    )
    observation = observations["27960"]

    assert observation.status == {"map": "campgrounds", "updated": 1_786_320_010}
    assert observation.active is True
    assert observation.invocation_id == "a" * 32
    assert observation.service_started_at == 1_786_320_000


@pytest.mark.parametrize(
    "payload",
    [
        _observation_payload(active_state="inactive"),
        _observation_payload(service_started_at=None),
        _observation_payload(invocation_id="not-an-invocation-id"),
        _observation_payload(active_state="active", invocation_id=None),
    ],
)
def test_parse_runtime_probe_output_keeps_status_when_unit_identity_is_unusable(payload):
    """A missing or inactive unit must not hide its independently-read Redis status."""
    from ui.task_logic.service_runtime import parse_runtime_probe_output

    observation = parse_runtime_probe_output(json.dumps({"27960": payload}))["27960"]

    assert observation.status == {"map": "campgrounds", "updated": 1_786_320_010}
    assert observation.invocation_id is None


def test_parse_runtime_probe_output_keeps_valid_sibling_when_another_unit_is_missing():
    """One failing Redis DB or systemd unit must not discard sibling observations."""
    from ui.task_logic.service_runtime import parse_runtime_probe_output

    observations = parse_runtime_probe_output(json.dumps({
        "27960": _observation_payload(),
        "27961": _observation_payload(status=None, active_state="inactive", invocation_id=None),
    }))

    assert observations["27960"].invocation_id == "a" * 32
    assert observations["27961"].status is None
    assert observations["27961"].active is False


@pytest.mark.parametrize(
    "payload, expected",
    [
        (_observation_payload(), True),
        (_observation_payload(status={"updated": True}), False),
        (_observation_payload(status={}), False),
        (_observation_payload(status=[]), False),
        (_observation_payload(status={"updated": "1786320010"}), False),
        (_observation_payload(status={"updated": 1_786_320_000}), False),
        (_observation_payload(status={"updated": 1_786_319_999}), False),
        (_observation_payload(active_state="inactive"), False),
    ],
)
def test_fresh_status_requires_valid_active_identity_and_post_start_integer_update(payload, expected):
    """Only a post-start live timestamp is evidence for later reconciliation."""
    from ui.task_logic.service_runtime import observation_has_fresh_status, parse_runtime_probe_output

    observation = parse_runtime_probe_output(json.dumps({"27960": payload}))["27960"]

    assert observation_has_fresh_status(observation) is expected


@patch(f"{MODULE}.subprocess.run")
def test_probe_host_runtime_uses_composed_budget_with_cleanup_headroom(mock_run):
    """The host deadline must leave two seconds beyond its three inner phases."""
    from ui.task_logic.service_runtime import (
        REDIS_PHASE_TIMEOUT,
        RUNTIME_PROBE_HEADROOM,
        RUNTIME_PROBE_TIMEOUT,
        SSH_CONNECT_TIMEOUT,
        SYSTEMD_TIMEOUT,
        probe_host_runtime,
    )

    mock_run.return_value = SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"27960": _observation_payload()}),
        stderr="",
    )

    observations = probe_host_runtime(_host(), [_instance()])

    assert observations["27960"].invocation_id == "a" * 32
    assert (SSH_CONNECT_TIMEOUT, REDIS_PHASE_TIMEOUT, SYSTEMD_TIMEOUT) == (3, 2, 5)
    assert RUNTIME_PROBE_HEADROOM == 2
    assert RUNTIME_PROBE_TIMEOUT == 12
    assert RUNTIME_PROBE_TIMEOUT == (
        SSH_CONNECT_TIMEOUT + REDIS_PHASE_TIMEOUT + SYSTEMD_TIMEOUT + RUNTIME_PROBE_HEADROOM
    )
    assert mock_run.call_args.kwargs["timeout"] == RUNTIME_PROBE_TIMEOUT


@pytest.mark.parametrize(
    "result, expected",
    [
        (SimpleNamespace(returncode=1, stdout="", stderr="denied"), None),
        (SimpleNamespace(returncode=0, stdout="not-json", stderr=""), None),
    ],
)
@patch(f"{MODULE}.subprocess.run")
def test_probe_host_runtime_returns_none_for_failed_or_invalid_ssh_round_trips(mock_run, result, expected):
    """Host-level SSH failures must not look like per-instance empty status."""
    from ui.task_logic.service_runtime import probe_host_runtime

    mock_run.return_value = result

    assert probe_host_runtime(_host(), [_instance()]) is expected


@patch(f"{MODULE}.subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 10))
def test_probe_host_runtime_returns_none_after_ssh_timeout(mock_run):
    """An expired outer SSH deadline must be normalized for poll callers."""
    from ui.task_logic.service_runtime import probe_host_runtime

    assert probe_host_runtime(_host(), [_instance()]) is None


@patch(f"{MODULE}.probe_host_runtime")
def test_invocation_helpers_filter_unusable_identity_and_scope_self_password(mock_probe, monkeypatch):
    """Update tasks receive only usable IDs and never a non-self Redis secret."""
    from ui.task_logic.service_runtime import RuntimeObservation, probe_host_invocation_ids, probe_instance_invocation_id

    host = _host(provider="self")
    first, second = _instance(27960, host=host), _instance(27961, host=host)
    mock_probe.return_value = {
        "27960": RuntimeObservation(None, "a" * 32, True, 1_786_320_000),
        "27961": RuntimeObservation(None, None, False, None),
    }
    monkeypatch.setenv("REDIS_PASSWORD", "self-only")

    assert probe_instance_invocation_id(first) == "a" * 32
    assert probe_host_invocation_ids(host, [first, second]) == {
        "27960": "a" * 32,
        "27961": None,
    }
    assert mock_probe.call_args.kwargs["redis_password"] == "self-only"


@patch(f"{MODULE}.probe_host_runtime", side_effect=RuntimeError("probe broke"))
def test_invocation_helpers_never_raise_when_runtime_probe_fails(mock_probe):
    """An update task must survive command, parse, and observation failures."""
    from ui.task_logic.service_runtime import probe_host_invocation_ids, probe_instance_invocation_id

    host = _host()
    instance = _instance(host=host)

    assert probe_instance_invocation_id(instance) is None
    assert probe_host_invocation_ids(host, [instance]) == {"27960": None}
