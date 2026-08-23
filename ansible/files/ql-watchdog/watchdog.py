#!/usr/bin/env python3
"""ql-watchdog — detect a hung QLDS main-thread and auto-restart the instance.

Background
----------
QLDS can deadlock its main game-loop (observed root cause on ql-server-core:
the built-in ZeroMQ stats/rcon publisher). The process stays alive but the
game frame-loop stops: the UDP game port is no longer drained, so the kernel
Recv-Q for the port climbs without bound. Plain process supervision (systemd
Restart=on-failure) cannot detect this because the process never exits. This
watchdog turns that infinite hang into an automatic restart of just the
affected instance.

qlsm runs each QLDS instance as its own systemd unit `qlds@<port>.service`
(the game port doubles as the systemd instance name — see
ansible/templates/qlds@.service.j2), unlike ql-server-core's supervisord
`quakelive:ql_N` groups. Discovery/restart here go through systemctl instead
of supervisorctl, and the game port is read directly off the unit name.

Detection (per instance, every INTERVAL):
  kernel Recv-Q for the UDP game port (read from /proc/net/udp) stays above
  RECVQ_THRESHOLD for STRIKES consecutive checks -> restart. A healthy server
  drains its socket every frame (Recv-Q ~0), so a sustained high Recv-Q only
  happens when the main loop is frozen. The strike count + GRACE window
  prevent restarting during boot/map-load or on a one-off burst.

Stdlib only. Runs as root (systemctl restart on a system unit + gdb attach to
another user's process both require it).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, "")).strip() or default)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


DRYRUN = _env_bool("QL_WATCHDOG_DRYRUN", False)
INTERVAL = max(2, _env_int("QL_WATCHDOG_INTERVAL", 10))
# Sustained Recv-Q (bytes) above this for STRIKES checks => hung. Healthy idle
# server sits at 0-960B even under polling; a real hang reaches 100KB+.
RECVQ_THRESHOLD = max(0, _env_int("QL_WATCHDOG_RECVQ_THRESHOLD", 8192))
STRIKES = max(1, _env_int("QL_WATCHDOG_STRIKES", 3))
# Skip an instance that has been active for less than GRACE seconds: covers
# systemd startup + map load + post-restart settle (no strikes during boot).
GRACE = max(30, _env_int("QL_WATCHDOG_GRACE", 90))
# Restart loop guard: at most RATE_MAX restarts per RATE_WINDOW per instance.
RATE_MAX = max(1, _env_int("QL_WATCHDOG_RATE_MAX", 3))
RATE_WINDOW = max(60, _env_int("QL_WATCHDOG_RATE_WINDOW", 900))
# qlds@<port>.service - the systemd template unit prefix qlsm uses for QLDS
# instances (ansible/templates/qlds@.service.j2). The game port is read
# directly from the unit's instance name (the part after '@').
UNIT_PREFIX = os.environ.get("QL_WATCHDOG_UNIT_PREFIX", "qlds").strip() or "qlds"
EVENTS_PATH = os.environ.get(
    "QL_WATCHDOG_EVENTS", "/var/lib/qlsm/watchdog/events.jsonl"
).strip()

# Forensics: on a detected hang, snapshot all-thread native backtraces with gdb
# (+ py-spy if present) BEFORE restarting, so a freeze is symbolized even
# though it produces no core. Best-effort, never blocks a restart.
FORENSICS = _env_bool("QL_WATCHDOG_FORENSICS", True)
GDB = os.environ.get("QL_WATCHDOG_GDB", "gdb").strip() or "gdb"
PYSPY = os.environ.get("QL_WATCHDOG_PYSPY", "py-spy").strip() or "py-spy"
FORENSICS_DIR = os.environ.get(
    "QL_WATCHDOG_FORENSICS_DIR", "/var/lib/qlsm/watchdog/forensics"
).strip()
GDB_TIMEOUT = max(10, _env_int("QL_WATCHDOG_GDB_TIMEOUT", 60))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(event: str, **fields: object) -> None:
    rec = {"ts": _utc_now(), "event": event}
    rec.update(fields)
    line = json.dumps(rec, ensure_ascii=False)
    print(line, flush=True)
    if EVENTS_PATH:
        try:
            os.makedirs(os.path.dirname(EVENTS_PATH), exist_ok=True)
            with open(EVENTS_PATH, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def _run(cmd: list[str], timeout: int) -> str:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return ((res.stdout or "") + (res.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"<run failed: {str(exc)[:200]}>"


def _which(prog: str) -> str:
    if os.path.isabs(prog):
        return prog if os.access(prog, os.X_OK) else ""
    for d in os.environ.get("PATH", "").split(os.pathsep):
        cand = os.path.join(d, prog)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return ""


def _unit_name(port: int) -> str:
    return f"{UNIT_PREFIX}@{port}.service"


def discover_instances() -> dict[int, dict[str, object]]:
    """Return {port: {state, uptime_sec}} for every qlds@<port>.service unit.

    The game port is the systemd instance name itself (see
    ansible/templates/qlds@.service.j2 - ExecStart is keyed on %i == port),
    so no separate index->port mapping is needed here.
    """
    try:
        res = subprocess.run(
            [
                "systemctl", "list-units", "--all", "--type=service",
                "--no-legend", "--plain", "--full", f"{UNIT_PREFIX}@*.service",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log_event("systemctl_error", action="list-units", error=str(exc)[:200])
        return {}

    units: list[str] = []
    prefix = f"{UNIT_PREFIX}@"
    for line in (res.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        name = line.split()[0]
        if name.startswith(prefix) and name.endswith(".service"):
            units.append(name)
    if not units:
        return {}

    try:
        res2 = subprocess.run(
            [
                "systemctl", "show", *units,
                "--property=Id,ActiveState,ActiveEnterTimestampMonotonic",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log_event("systemctl_error", action="show", error=str(exc)[:200])
        return {}

    now_mono = time.clock_gettime(time.CLOCK_MONOTONIC)
    instances: dict[int, dict[str, object]] = {}
    for block in (res2.stdout or "").split("\n\n"):
        props: dict[str, str] = {}
        for line in block.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                props[k] = v
        unit_id = props.get("Id", "")
        if not (unit_id.startswith(prefix) and unit_id.endswith(".service")):
            continue
        port_str = unit_id[len(prefix):-len(".service")]
        try:
            port = int(port_str)
        except ValueError:
            continue
        enter_us = props.get("ActiveEnterTimestampMonotonic", "0")
        try:
            enter_mono = int(enter_us) / 1_000_000.0
        except ValueError:
            enter_mono = 0.0
        uptime_sec = max(0, int(now_mono - enter_mono)) if enter_mono > 0 else 0
        instances[port] = {
            "state": props.get("ActiveState", ""),
            "uptime_sec": uptime_sec,
        }
    return instances


def _recv_q_from(path: str, port: int) -> int:
    total = 0
    try:
        with open(path, encoding="ascii") as fh:
            next(fh, None)  # header
            for line in fh:
                f = line.split()
                if len(f) < 5:
                    continue
                local = f[1]
                if ":" not in local:
                    continue
                try:
                    lport = int(local.rsplit(":", 1)[1], 16)
                except ValueError:
                    continue
                if lport != port:
                    continue
                queues = f[4].split(":")
                if len(queues) != 2:
                    continue
                try:
                    total += int(queues[1], 16)  # rx_queue (Recv-Q)
                except ValueError:
                    continue
    except OSError:
        return 0
    return total


def recv_q(port: int) -> int:
    return max(_recv_q_from("/proc/net/udp", port), _recv_q_from("/proc/net/udp6", port))


def restart_instance(port: int) -> tuple[bool, str]:
    unit = _unit_name(port)
    try:
        res = subprocess.run(
            ["systemctl", "restart", unit],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)[:200]
    out = ((res.stdout or "") + (res.stderr or "")).strip()
    return res.returncode == 0, out[:300]


def instance_pid(port: int) -> str:
    out = _run(["systemctl", "show", _unit_name(port), "--property=MainPID", "--value"], 15).strip()
    return out if out.isdigit() and out != "0" else ""


def capture_hang_forensics(port: int, rq: int) -> str:
    """Snapshot all-thread native backtraces (gdb) + py-spy of a hung instance.

    Returns the forensics file path, or "" if it could not be captured. Runs
    as root, so gdb can attach regardless of ptrace_scope. Best-effort only.
    """
    if not FORENSICS:
        return ""
    pid = instance_pid(port)
    if not pid:
        return ""
    try:
        os.makedirs(FORENSICS_DIR, exist_ok=True)
    except OSError:
        return ""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(FORENSICS_DIR, f"hang-{UNIT_PREFIX}-{port}-{ts}.txt")
    parts = [
        f"# ql-watchdog hang forensics\n"
        f"port={port} pid={pid} recv_q={rq} ts={ts}\n"
    ]
    try:
        with open(f"/proc/{pid}/wchan", encoding="ascii") as fh:
            parts.append(f"wchan={fh.read().strip()}\n")
    except OSError:
        pass
    gdb = _which(GDB)
    if gdb:
        parts.append("\n=== gdb: thread apply all bt ===\n")
        parts.append(
            _run(
                [
                    gdb, "-p", pid, "-batch", "-nx",
                    "-ex", "set pagination off",
                    "-ex", "thread apply all bt",
                    "-ex", "detach", "-ex", "quit",
                ],
                GDB_TIMEOUT,
            )
        )
    else:
        parts.append("\n=== gdb not found; skipped native backtrace ===\n")
    pyspy = _which(PYSPY)
    if pyspy:
        parts.append("\n\n=== py-spy dump (python threads) ===\n")
        parts.append(_run([pyspy, "dump", "--pid", pid, "--nonblocking"], 30))
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("".join(parts))
    except OSError:
        return ""
    return path


def main() -> int:
    log_event(
        "start",
        dryrun=DRYRUN,
        interval=INTERVAL,
        recvq_threshold=RECVQ_THRESHOLD,
        strikes=STRIKES,
        grace=GRACE,
        unit_prefix=UNIT_PREFIX,
        forensics=FORENSICS,
        gdb=bool(_which(GDB)),
    )
    strikes: dict[int, int] = {}
    restarts: dict[int, deque[float]] = {}

    while True:
        try:
            instances = discover_instances()
            for port, info in instances.items():
                if info["state"] != "active" or int(info["uptime_sec"]) < GRACE:  # type: ignore[arg-type]
                    strikes[port] = 0
                    continue
                rq = recv_q(port)
                hung = rq >= RECVQ_THRESHOLD
                if not hung:
                    if strikes.get(port):
                        log_event("recovered", port=port, recv_q=rq)
                    strikes[port] = 0
                    continue
                strikes[port] = strikes.get(port, 0) + 1
                log_event(
                    "hang_suspected",
                    port=port,
                    recv_q=rq,
                    strike=strikes[port],
                    need=STRIKES,
                )
                if strikes[port] < STRIKES:
                    continue

                hist = restarts.setdefault(port, deque())
                now = time.monotonic()
                while hist and now - hist[0] > RATE_WINDOW:
                    hist.popleft()
                if len(hist) >= RATE_MAX:
                    log_event(
                        "restart_giveup",
                        port=port,
                        recv_q=rq,
                        restarts_in_window=len(hist),
                        window_sec=RATE_WINDOW,
                        note="rate limit hit; alert only, not restarting",
                    )
                    strikes[port] = 0
                    continue

                # Capture native+python backtraces of the frozen process BEFORE
                # touching it - a hang yields no core, so this is the only
                # record of WHERE the main thread is stuck.
                forensics = capture_hang_forensics(port, rq)
                if forensics:
                    log_event("hang_forensics", port=port, recv_q=rq, file=forensics)

                if DRYRUN:
                    log_event("would_restart", port=port, recv_q=rq, forensics=forensics)
                    strikes[port] = 0
                    continue

                ok, out = restart_instance(port)
                hist.append(now)
                log_event(
                    "restart" if ok else "restart_failed",
                    port=port,
                    recv_q=rq,
                    ok=ok,
                    output=out,
                    forensics=forensics,
                )
                strikes[port] = 0
        except Exception as exc:  # never let the watchdog die on a transient error
            log_event("loop_error", error=str(exc)[:300])
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
