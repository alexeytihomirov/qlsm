"""Redis-based locking for entity tasks and backup maintenance.

Prevents conflicting operations on the same host or instance, and keeps a
backup export or import mutually exclusive with every entity task. Each
acquisition runs as a Lua script so it observes and mutates lock state in one
atomic step, rather than checking and then acting.
"""
from contextlib import contextmanager
import logging

log = logging.getLogger(__name__)

# Held for the whole of a backup export or import. Entity tasks refuse to start
# while it exists, and it refuses to be taken while any entity lock is live, so
# a restore can never overlap a Terraform apply or an Ansible run.
MAINTENANCE_LOCK_KEY = 'maintenance_lock:backup'

# A crash backstop, not a deadline. Nothing refreshes this lock, so it has to
# outlast any plausible export or import; a worker killed mid-restore leaves the
# key behind and backups recover on their own once it expires.
MAINTENANCE_LOCK_TTL = 1800

# Index of the entity locks acquire_lock currently has outstanding. Maintenance
# acquisition walks this set rather than scanning for 'task_lock:*': Redis is
# shared with RQ, so a MATCH scan reads every job, result and registry key, and
# inside a Lua script that sweep blocks the server for its whole duration. An
# entry outlives its lock whenever a TTL expires without a release, so the
# maintenance script drops the entries whose key is gone as it walks them.
TASK_LOCK_INDEX_KEY = 'task_lock:index'

# KEYS: entity lock, maintenance lock, index. ARGV: owner token, TTL.
_ACQUIRE_ENTITY_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 1 then
    return 0
end
local acquired = redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2])
if acquired then
    redis.call('SADD', KEYS[3], KEYS[1])
    return 1
end
return 0
"""

# KEYS: maintenance lock, index. ARGV: owner token, TTL.
_ACQUIRE_MAINTENANCE_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 1 then
    return 0
end
local tracked = redis.call('SMEMBERS', KEYS[2])
for i = 1, #tracked do
    if redis.call('EXISTS', tracked[i]) == 1 then
        return 0
    end
    redis.call('SREM', KEYS[2], tracked[i])
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
return 1
"""

# Delete the key only if the value matches, so a task cannot release a lock
# that already expired and was re-acquired by someone else.
_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

_RELEASE_ENTITY_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('SREM', KEYS[2], KEYS[1])
    return redis.call('DEL', KEYS[1])
end
return 0
"""

_FORCE_RELEASE_ENTITY_SCRIPT = """
redis.call('SREM', KEYS[2], KEYS[1])
return redis.call('DEL', KEYS[1])
"""


def _get_redis():
    """Get the shared Redis client from the Flask app."""
    from flask import current_app
    return current_app.extensions['redis']


def acquire_lock(entity_type, entity_id, token, ttl):
    """Attempt to acquire a per-entity lock.

    Refuses while a backup holds the maintenance lock, and records the lock in
    the index so maintenance acquisition can see it.

    Args:
        entity_type: 'host' or 'instance'
        entity_id: numeric entity ID
        token: unique lock token (UUID) for owner validation
        ttl: lock TTL in seconds

    Returns:
        True if lock acquired, False if already held or a backup is running.
    """
    redis_client = _get_redis()
    key = f"task_lock:{entity_type}:{entity_id}"
    result = redis_client.execute_command(
        'EVAL',
        _ACQUIRE_ENTITY_SCRIPT,
        3,
        key,
        MAINTENANCE_LOCK_KEY,
        TASK_LOCK_INDEX_KEY,
        token,
        ttl,
    )
    if result:
        log.info(f"Lock acquired: {key} (token={token}, ttl={ttl}s)")
    else:
        log.warning(f"Lock denied: {key} is held or a backup is running")
    return bool(result)


def acquire_locks(entity_type, entity_ids, token, ttl):
    """Acquire a de-duplicated entity set in stable order or acquire none."""
    acquired_ids = []
    try:
        for entity_id in sorted(set(entity_ids)):
            if not acquire_lock(entity_type, entity_id, token, ttl):
                release_locks(entity_type, acquired_ids, token)
                return False
            acquired_ids.append(entity_id)
    except Exception:
        release_locks(entity_type, acquired_ids, token)
        raise
    return True


def acquire_maintenance_lock(redis_client, token):
    """Take backup maintenance when no maintenance or entity lock is held."""
    result = redis_client.execute_command(
        'EVAL',
        _ACQUIRE_MAINTENANCE_SCRIPT,
        2,
        MAINTENANCE_LOCK_KEY,
        TASK_LOCK_INDEX_KEY,
        token,
        MAINTENANCE_LOCK_TTL,
    )
    if result:
        log.info("Backup maintenance lock acquired")
    else:
        log.warning("Backup maintenance lock denied by an active lock")
    return bool(result)


def release_maintenance_lock(redis_client, token):
    """Release backup maintenance only while ``token`` still owns it."""
    result = redis_client.execute_command(
        'EVAL', _RELEASE_SCRIPT, 1, MAINTENANCE_LOCK_KEY, token
    )
    if result:
        log.info("Backup maintenance lock released")
    else:
        log.debug("Backup maintenance lock not released (not owner or expired)")
    return bool(result)


@contextmanager
def backup_maintenance_lock(token):
    """Hold backup maintenance for the body, yielding whether it was acquired.

    The lock is not refreshed: MAINTENANCE_LOCK_TTL is set long enough to
    outlast a backup, so the only job left is releasing it on the way out.
    """
    redis_client = _get_redis()
    if not acquire_maintenance_lock(redis_client, token):
        yield False
        return
    try:
        yield True
    finally:
        try:
            release_maintenance_lock(redis_client, token)
        except Exception:
            log.exception("Failed to release backup maintenance lock")


def release_lock(entity_type, entity_id, token):
    """Release a per-entity lock, only if we own it.

    Args:
        entity_type: 'host' or 'instance'
        entity_id: numeric entity ID
        token: the token used when acquiring

    Returns:
        True if lock was released, False if not owned or not found.
    """
    redis_client = _get_redis()
    key = f"task_lock:{entity_type}:{entity_id}"
    result = redis_client.execute_command(
        'EVAL', _RELEASE_ENTITY_SCRIPT, 2, key, TASK_LOCK_INDEX_KEY, token
    )
    if result:
        log.info(f"Lock released: {key} (token={token})")
    else:
        log.debug(f"Lock not released (not owner or expired): {key}")
    return bool(result)


def lock_superseded(entity_type, entity_id, token):
    """True when another operation now holds this entity's lock.

    A missing key (expired or already released) is not superseded: nothing
    newer owns the entity, so recovery of an interrupted job may proceed.
    """
    if not token:
        return False
    owner = _get_redis().get(f"task_lock:{entity_type}:{entity_id}")
    if owner is None:
        return False
    if isinstance(owner, bytes):
        owner = owner.decode()
    return owner != token


def release_locks(entity_type, entity_ids, token):
    """Best-effort release for every unique entity ID."""
    for entity_id in sorted(set(entity_ids)):
        try:
            release_lock(entity_type, entity_id, token)
        except Exception:
            log.exception(
                "Failed to release lock: task_lock:%s:%s",
                entity_type,
                entity_id,
            )


def force_release_lock(entity_type, entity_id):
    """Unconditionally delete a stale lock regardless of owner.

    Only call this when the lock is known to be stale (e.g. the task that
    held it crashed without releasing it and its TTL has long since expired).
    Returns True if a key was deleted, False if there was nothing to delete.
    """
    redis_client = _get_redis()
    key = f"task_lock:{entity_type}:{entity_id}"
    result = redis_client.execute_command(
        'EVAL', _FORCE_RELEASE_ENTITY_SCRIPT, 2, key, TASK_LOCK_INDEX_KEY
    )
    if result:
        log.warning(f"Stale lock force-released: {key}")
    return bool(result)
