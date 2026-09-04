"""Push access.txt admin entries into the target instance's minqlx permission DB.

The Owner & Admins editor (frontend-react/src/components/operators/OwnerAdminEditor.jsx)
writes qlx_owner into server.cfg -- picked up for free on the next server.cfg exec,
no extra step needed -- and "steamid|level" lines into access.txt. No shipped
minqlx-plugin actually reads access.txt, though: permission.py / chat_rcon.py only
ever consult minqlx's own Redis permission keys, normally set one at a time via the
in-game "!setperm <id> <level>" chat command. Without this module, an admin added
through the UI still has permission level 0 in the running instance and chat_rcon's
!rcon silently denies them ("permission denied"), even though access.txt looks right.

Call sync_instance_access_permissions(instance) from apply_instance_config_logic
after every successful config apply, mirroring telemetry_relay_instance.py's
sync_instance_server_id_from_config -- same "config on disk is the source of truth,
reconcile the running instance's external state after every apply" shape.

Removed entries are reset to permission 0 rather than left stale, tracked via a
"minqlx:qlsm:managed_admins" Redis SET scoped to the same per-instance DB: only
steamids this sync itself previously wrote get reset, so a permission granted
by hand via !setperm outside the UI is never touched.

Caveat: minqlxtended caches permission reads for qlx_permissionCacheTime seconds
(default 30, see minqlxtended/database.py Redis._permission_ttl) inside its own
process. A write made here from outside that process cannot invalidate that
cache, so a permission change can take up to ~30s to take effect in-game. There
is no remote way to poke the cache sooner: '!'-prefixed minqlx commands (which
is how a live admin would normally trigger cache eviction by re-running a
command) are not reachable over zmq_rcon on this build -- confirmed live against
91.99.3.72:27965, where "!rcon status" sent over zmq_rcon produced no reply and
no chat-rcon log line at all.
"""

import base64
import json
import logging
import os
import re
import shlex
import subprocess

from ui.constants import resolve_redis_db
from ui.task_logic.self_host_network import resolve_self_host_management_target

logger = logging.getLogger(__name__)

STEAMID64_RE = re.compile(r"^7656119\d{10}$")
SSH_CONNECT_TIMEOUT = 5
SYNC_TIMEOUT = SSH_CONNECT_TIMEOUT + 5
MANAGED_SET_KEY = "minqlx:qlsm:managed_admins"


def parse_access_entries(access_text):
    """Parse "steamid|level" lines the same way operatorConfigSync.js's
    parseAdminEntries does on the frontend.

    Blank lines and lines starting with '#' are skipped, matching the UI. A
    line whose first token is not a SteamID64 is skipped too. Levels are
    clamped to 0-5; a missing or non-numeric level defaults to 5 (the UI's own
    default when adding an admin without touching the level dropdown).

    Returns a {steam_id: level} dict -- last line for a given ID wins, same as
    upsertAdminLine's in-place update.
    """
    entries = {}
    for line in (access_text or "").split("\n"):
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        id_part, _, rest = trimmed.partition("|")
        steam_id = id_part.strip()
        if not STEAMID64_RE.match(steam_id):
            continue
        level_part = rest.split("#", 1)[0].strip()
        try:
            level = int(level_part)
        except ValueError:
            level = 5
        entries[steam_id] = max(0, min(5, level))
    return entries


def _ssh_target_for_host(host):
    if getattr(host, "provider", None) == "self":
        return resolve_self_host_management_target()
    return host.ip_address


def _remote_sync_script(entries, db, redis_password):
    entries_b64 = base64.b64encode(json.dumps(entries).encode()).decode()
    password_b64 = (
        base64.b64encode(redis_password.encode()).decode() if redis_password is not None else None
    )
    return f'''import base64
import json
import redis

entries = json.loads(base64.b64decode({entries_b64!r}).decode())
password_b64 = {password_b64!r}
password = base64.b64decode(password_b64).decode() if password_b64 is not None else None

client = redis.Redis(db={db}, password=password, socket_connect_timeout=3, socket_timeout=3)

managed_key = {MANAGED_SET_KEY!r}
previously_managed = {{
    m.decode() if isinstance(m, bytes) else m for m in client.smembers(managed_key)
}}
new_ids = set(entries.keys())

for steam_id, level in entries.items():
    client.set(f"minqlx:players:{{steam_id}}:permission", str(level))

removed = previously_managed - new_ids
for steam_id in removed:
    client.set(f"minqlx:players:{{steam_id}}:permission", "0")

if previously_managed:
    client.srem(managed_key, *previously_managed)
if new_ids:
    client.sadd(managed_key, *new_ids)

print(json.dumps({{"synced": sorted(new_ids), "reset": sorted(removed)}}))
'''


def build_sync_command(host, db, entries, redis_password=None):
    """One bounded SSH command that reconciles a single instance's permission
    keys, mirroring service_runtime.py's build_runtime_probe_command shape."""
    script = _remote_sync_script(entries, db, redis_password)
    return [
        "ssh",
        "-i", os.path.abspath(host.ssh_key_path),
        "-p", str(host.ssh_port),
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
        "-l", host.ssh_user,
        _ssh_target_for_host(host),
        f"python3 -c {shlex.quote(script)}",
    ]


def sync_access_permissions(instance, access_text):
    """Best-effort push of access.txt entries into the instance's minqlx
    permission DB. Returns {"synced": [...], "reset": [...]} on success, or
    None if the host is missing or the SSH round-trip failed -- callers
    should log a warning on None and never fail the config apply for this."""
    host = getattr(instance, "host", None)
    if host is None:
        return None

    entries = parse_access_entries(access_text)
    db = resolve_redis_db(instance)
    redis_password = (
        os.environ.get("REDIS_PASSWORD") if getattr(host, "provider", None) == "self" else None
    )

    command = build_sync_command(host, db, entries, redis_password=redis_password)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=SYNC_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.warning(
            "Timed out syncing access.txt permissions for instance %s", getattr(instance, "id", "?")
        )
        return None
    except Exception:
        logger.exception(
            "Failed to sync access.txt permissions for instance %s", getattr(instance, "id", "?")
        )
        return None

    if result.returncode != 0:
        logger.warning(
            "access.txt permission sync failed for instance %s: %s",
            getattr(instance, "id", "?"), (result.stderr or "")[:200],
        )
        return None

    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "access.txt permission sync returned unparseable output for instance %s",
            getattr(instance, "id", "?"),
        )
        return None

    return payload


def sync_instance_access_permissions(instance):
    """Read the instance's on-disk access.txt and reconcile it into Redis.

    No-op (returns None) if the instance has no host or no access.txt on disk
    yet -- matches sync_instance_server_id_from_config's "nothing written yet"
    handling in telemetry_relay_instance.py.
    """
    if not instance.host:
        return None
    config_path = os.path.join("configs", instance.host.name, str(instance.id), "access.txt")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return None

    return sync_access_permissions(instance, text)
