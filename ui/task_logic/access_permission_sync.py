"""Write admin level changes into an instance's minqlx permission DB.

Redis is the only source of truth for who is an admin. QLSM stores no admin
list of its own: the Owner & Admins tab reads Redis (permission_read.py), and
this module writes back only what the operator actually changed there -- an
added or re-levelled admin gets its level, a removed one gets 0. Every other
key is left alone, so a level set in-game with !setperm is never overwritten by
a save, a restart or a deploy.

The two callers:
- apply_instance_config_logic, with the changes from Save Configuration;
- deploy_instance_logic, once, with the admin list from the Add Instance form
  (or the preset it was created from).

Caveat: minqlx caches permission reads for qlx_permissionCacheTime seconds
(default 30) inside its own process, and a write from outside cannot
invalidate that cache, so a change can take up to ~30s to apply in-game.
"""

import base64
import json
import logging
import os
import shlex
import subprocess

from ui import db
from ui.constants import resolve_redis_db
from ui.task_logic.common import append_log
from ui.task_logic.self_host_network import resolve_self_host_management_target

logger = logging.getLogger(__name__)

SSH_CONNECT_TIMEOUT = 5
SYNC_TIMEOUT = SSH_CONNECT_TIMEOUT + 5
# Older QLSM versions tracked the admins they pushed in these sets. Nothing
# reads them any more; the write script deletes them so they do not linger.
LEGACY_MANAGED_KEY_PATTERN = "minqlx:qlsm:managed_admins*"


def _ssh_target_for_host(host):
    if getattr(host, "provider", None) == "self":
        return resolve_self_host_management_target()
    return host.ip_address


def redis_password_for_host(host):
    return os.environ.get("REDIS_PASSWORD") if getattr(host, "provider", None) == "self" else None


def build_ssh_python_command(host, script):
    """One bounded SSH command running `script` with the host's python3."""
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


def _remote_write_script(changes, db, redis_password):
    changes_b64 = base64.b64encode(json.dumps(changes).encode()).decode()
    password_b64 = (
        base64.b64encode(redis_password.encode()).decode() if redis_password is not None else None
    )
    return f'''import base64
import json
import redis

changes = json.loads(base64.b64decode({changes_b64!r}).decode())
password_b64 = {password_b64!r}
password = base64.b64decode(password_b64).decode() if password_b64 is not None else None
client = redis.Redis(db={db}, password=password, socket_connect_timeout=3, socket_timeout=3)

for steam_id, level in changes.items():
    client.set("minqlx:players:%s:permission" % steam_id, str(level))
for key in client.scan_iter(match={LEGACY_MANAGED_KEY_PATTERN!r}, count=100):
    client.delete(key)

print(json.dumps({{"written": sorted(changes)}}))
'''


def build_write_command(host, db, changes, redis_password=None):
    return build_ssh_python_command(host, _remote_write_script(changes, db, redis_password))


def write_admin_levels(instance, changes):
    """Write {steam_id: level} into the instance's Redis DB.

    Returns {"written": [...]} on success, False if the round trip failed
    (SSH/Redis unreachable, bad output), or None when there is nothing to do
    (no host, or no changes).
    """
    host = getattr(instance, "host", None)
    if host is None or not changes:
        return None

    command = build_write_command(
        host, resolve_redis_db(instance), changes, redis_password=redis_password_for_host(host)
    )
    instance_id = getattr(instance, "id", "?")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=SYNC_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.warning("Timed out writing admin levels for instance %s", instance_id)
        return False
    except Exception:
        logger.exception("Failed to write admin levels for instance %s", instance_id)
        return False

    if result.returncode != 0:
        logger.warning("Admin level write failed for instance %s: %s",
                       instance_id, (result.stderr or "")[:200])
        return False
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Admin level write returned unparseable output for instance %s", instance_id)
        return False


WRITE_FAILED_LOG_MESSAGE = (
    "Warning: admin level changes could not be written to the server "
    "(SSH/Redis unreachable). In-game admin levels were not changed."
)


def write_and_report_admin_levels(instance, changes):
    """Write admin level changes after a successful deploy or config apply.

    Never raises and never fails the calling task; a failure appends a warning
    to the instance log so the operator can see the change did not land."""
    try:
        result = write_admin_levels(instance, changes)
    except Exception:
        logger.warning("Admin level write raised for instance %s",
                       getattr(instance, "id", "?"), exc_info=True)
        result = False
    if result is False:
        try:
            append_log(instance, WRITE_FAILED_LOG_MESSAGE)
            db.session.commit()
        except Exception:
            logger.warning("Could not log admin level write failure for instance %s",
                           getattr(instance, "id", "?"), exc_info=True)
            db.session.rollback()
    return result
