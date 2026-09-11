"""Unit tests for the ql-watchdog detection primitives.

The watchdog is a standalone stdlib-only script that runs on the game host
under the host's own python3, so it is loaded by path rather than imported as
a package. These cover the two parsers that decide whether a live game server
gets SIGKILLed: the /proc/net/udp Recv-Q reader and the /proc/<pid>/stat CPU
reader that corroborates it.
"""
import importlib.util
import os
import sys

import pytest

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ansible", "files", "ql-watchdog", "watchdog.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("ql_watchdog_script", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ql_watchdog_script"] = mod
    spec.loader.exec_module(mod)
    return mod


watchdog = _load()


# /proc/net/udp layout: sl local_address rem_address st tx_queue:rx_queue ...
# 27960 == 0x6D38. rx_queue is the second half of field 4.
_UDP_TABLE = """  sl  local_address rem_address   st tx_queue:rx_queue tr tm->when retrnsmt   uid  timeout inode
  123: 00000000:6D38 00000000:0000 07 00000000:00002000 00:00000000 00000000     0        0 12345 2 0000000000000000 0
  124: 00000000:6D39 00000000:0000 07 00000000:00000000 00:00000000 00000000     0        0 12346 2 0000000000000000 0
"""


def test_recv_q_reads_rx_queue_for_the_matching_port(tmp_path):
    f = tmp_path / "udp"
    f.write_text(_UDP_TABLE)
    # 0x2000 == 8192, the default RECVQ_THRESHOLD.
    assert watchdog._recv_q_from(str(f), 27960) == 8192
    # 27961 (0x6D39) is idle.
    assert watchdog._recv_q_from(str(f), 27961) == 0
    # A port with no socket at all reads as 0, not an error.
    assert watchdog._recv_q_from(str(f), 29000) == 0


def test_recv_q_missing_file_is_zero_not_an_exception(tmp_path):
    assert watchdog._recv_q_from(str(tmp_path / "nope"), 27960) == 0


def test_recv_q_skips_malformed_lines(tmp_path):
    f = tmp_path / "udp"
    f.write_text(
        "header\n"
        "garbage\n"
        "  1: NOCOLON 00000000:0000 07 00000000:00001000\n"
        "  2: 00000000:ZZZZ 00000000:0000 07 00000000:00001000\n"
        "  3: 00000000:6D38 00000000:0000 07 badqueue\n"
        "  4: 00000000:6D38 00000000:0000 07 00000000:00000100 x\n"
    )
    # Only the last line is well-formed for 27960: 0x100 == 256.
    assert watchdog._recv_q_from(str(f), 27960) == 256


def test_recv_q_threshold_floor_is_one():
    """0 would make 'rq >= threshold' true on every check for every instance."""
    assert watchdog.RECVQ_THRESHOLD >= 1


@pytest.mark.parametrize(
    "comm", ["qzeroded.x64", "name with spaces", "weird)paren", "((nested))"]
)
def test_cpu_ticks_sums_utime_and_stime_despite_comm_content(tmp_path, monkeypatch, comm):
    # /proc/<pid>/stat: pid (comm) state ppid ... utime(14) stime(15) ...
    # After the closing paren, state is index 0, so utime/stime are 11 and 12.
    after = ["S"] + [str(i) for i in range(1, 11)] + ["400", "50"] + ["0"] * 30
    proc = tmp_path / "1234"
    proc.mkdir()
    (proc / "stat").write_text(f"1234 ({comm}) " + " ".join(after) + "\n")
    monkeypatch.setattr(watchdog, "cpu_ticks", watchdog.cpu_ticks)
    # Point the reader at our fixture tree.
    orig_open = open

    def fake_open(path, *a, **kw):
        if str(path) == "/proc/1234/stat":
            return orig_open(str(proc / "stat"), *a, **kw)
        return orig_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", fake_open)
    assert watchdog.cpu_ticks("1234") == 450


def test_cpu_ticks_returns_none_for_a_dead_process():
    assert watchdog.cpu_ticks("0") is None
    assert watchdog.cpu_ticks("nonexistent-pid") is None


def test_cpu_ticks_returns_none_on_unparseable_stat(tmp_path, monkeypatch):
    proc = tmp_path / "stat"
    proc.write_text("no closing paren here\n")
    orig_open = open

    def fake_open(path, *a, **kw):
        if str(path) == "/proc/9/stat":
            return orig_open(str(proc), *a, **kw)
        return orig_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", fake_open)
    assert watchdog.cpu_ticks("9") is None
