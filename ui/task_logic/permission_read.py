"""Read the live minqlx admin levels out of an instance's Redis database.

The mirror image of access_permission_sync's write path: one bounded SSH
command running a small python script on the host. SCAN, not KEYS, so a large
database cannot block Redis. Only levels above 0 come back -- a key set to 0 is
a revoked admin, not an admin.
"""

import base64
import json
import logging
import subprocess

from ui.admin_permissions import STEAMID64_RE
from ui.constants import resolve_redis_db
from ui.task_logic.access_permission_sync import (
    SSH_CONNECT_TIMEOUT,
    build_ssh_python_command,
    redis_password_for_host,
)

logger = logging.getLogger(__name__)

READ_TIMEOUT = SSH_CONNECT_TIMEOUT + 5
UNREACHABLE_MESSAGE = "The server is unreachable, so admin levels could not be read."


def _remote_read_script(db, redis_password):
    password_b64 = (
        base64.b64encode(redis_password.encode()).decode() if redis_password is not None else None
    )
    return f'''import base64
import json
import redis

password_b64 = {password_b64!r}
password = base64.b64decode(password_b64).decode() if password_b64 is not None else None
client = redis.Redis(db={db}, password=password, socket_connect_timeout=3, socket_timeout=3)

levels = {{}}
for key in client.scan_iter(match="minqlx:players:*:permission", count=500):
    key_text = key.decode() if isinstance(key, bytes) else key
    parts = key_text.split(":")
    if len(parts) != 4:
        continue
    raw = client.get(key_text)
    if raw is None:
        continue
    raw_text = raw.decode() if isinstance(raw, bytes) else raw
    try:
        levels[parts[2]] = int(raw_text)
    except (TypeError, ValueError):
        continue

print(json.dumps({{"levels": levels}}))
'''


def build_read_command(host, db, redis_password=None):
    return build_ssh_python_command(host, _remote_read_script(db, redis_password))


def read_live_admins(instance):
    """(admins, error). admins is [{'steam_id64', 'level'}] sorted by SteamID,
    levels 1-5 only; (None, message) when the server could not be read and
    (None, None) when the instance has no host."""
    host = getattr(instance, "host", None)
    if host is None:
        return None, None

    command = build_read_command(
        host, resolve_redis_db(instance), redis_password=redis_password_for_host(host)
    )
    instance_id = getattr(instance, "id", "?")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=READ_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.warning("Timed out reading admin levels for instance %s", instance_id)
        return None, UNREACHABLE_MESSAGE
    except Exception:
        logger.exception("Failed to read admin levels for instance %s", instance_id)
        return None, UNREACHABLE_MESSAGE

    if result.returncode != 0:
        logger.warning("Admin level read failed for instance %s: %s",
                       instance_id, (result.stderr or "")[:200])
        return None, UNREACHABLE_MESSAGE

    try:
        levels = json.loads(result.stdout).get("levels") or {}
        # A key that is not a SteamID must never reach the client: it would
        # then fail validation and block the whole config save.
        admins = [
            {"steam_id64": str(steam_id), "level": int(level)}
            for steam_id, level in levels.items()
            if STEAMID64_RE.match(str(steam_id)) and 0 < int(level) <= 5
        ]
    except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Admin level read returned unparseable output for instance %s", instance_id)
        return None, UNREACHABLE_MESSAGE
    return sorted(admins, key=lambda a: a["steam_id64"]), None
