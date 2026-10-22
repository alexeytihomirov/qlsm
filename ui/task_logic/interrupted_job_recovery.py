"""Recovery for instance jobs whose worker died before writing a final status.

A killed or replaced worker leaves the instance in a transitional status. This
module probes the real service over SSH and records what it finds, instead of
guessing. It never starts, stops or restarts anything, and a running service is
never reported as successfully configured: the log says the config is unconfirmed.
"""
import logging
import os
from datetime import datetime, timezone

from rq.exceptions import NoSuchJobError
from rq.job import Job

from ui import db, rq
from ui.models import InstanceStatus, QLInstance
from ui.task_logic.common import append_log
from ui.task_logic.service_runtime import probe_host_runtime

log = logging.getLogger(__name__)

STALE_HEARTBEAT_SECONDS = 120

CONFIG_UNCONFIRMED_LOG = "Configuration not confirmed after interrupted job, re-apply to be sure."

# Statuses where "is the service running?" tells the truth about the outcome.
PROBE_STATUSES = frozenset({
    InstanceStatus.CONFIGURING,
    InstanceStatus.RESTARTING,
    InstanceStatus.STARTING,
    InstanceStatus.STOPPING,
})

# A half-built or half-removed instance cannot be judged by its service state.
TRANSITIONAL_STATUSES = PROBE_STATUSES | {InstanceStatus.DEPLOYING, InstanceStatus.DELETING}


def probe_service_state(instance):
    """Return 'active', 'inactive' or 'unknown' for the instance's QLDS unit."""
    host = getattr(instance, 'host', None)
    if host is None:
        return 'unknown'
    password = os.environ.get("REDIS_PASSWORD") if getattr(host, "provider", None) == "self" else None
    try:
        observations = probe_host_runtime(host, [instance], redis_password=password)
    except Exception:
        log.exception("Service probe failed for instance %s", getattr(instance, 'id', '?'))
        return 'unknown'
    if observations is None:
        return 'unknown'
    observation = observations.get(str(instance.port))
    if observation is None:
        return 'unknown'
    return 'active' if observation.active else 'inactive'


def recover_interrupted_instance(instance_id, job_id, lock_token, reason):
    """Move an instance out of a transitional status after its job was interrupted.

    Needs an app context. Returns True if the status changed. Does nothing when
    the instance is gone, already settled, or a newer operation holds the lock.
    """
    from ui.task_lock import lock_superseded, release_lock

    instance = db.session.get(QLInstance, instance_id)
    if instance is None or instance.status not in TRANSITIONAL_STATUSES:
        return False
    if lock_superseded('instance', instance_id, lock_token):
        log.info("Instance %s: lock held by a newer operation, skipping recovery of job %s",
                 instance_id, job_id)
        return False

    previous = instance.status
    if previous in PROBE_STATUSES:
        state = probe_service_state(instance)
        if state == 'active':
            new_status = InstanceStatus.RUNNING
        elif state == 'inactive':
            new_status = InstanceStatus.STOPPED
        else:
            new_status = InstanceStatus.ERROR
    else:
        state = 'not probed'
        new_status = InstanceStatus.ERROR

    append_log(instance, f"Job {job_id} interrupted ({reason}) while {previous.value}; "
                         f"service is {state}. Status: {new_status.value}.")
    if state == 'active':
        append_log(instance, CONFIG_UNCONFIRMED_LOG)
    instance.status = new_status
    db.session.commit()
    log.info("Instance %s recovered from %s to %s (service %s)",
             instance_id, previous.value, new_status.value, state)

    if lock_token:
        release_lock('instance', instance_id, lock_token)
    return True


def _started_jobs():
    """Yield every job in the default queue's started registry."""
    queue = rq.get_queue()
    for job_id in queue.started_job_registry.get_job_ids():
        try:
            yield Job.fetch(job_id, connection=queue.connection)
        except NoSuchJobError:
            continue


def _as_utc(moment):
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def reconcile_stale_instance_jobs(now=None):
    """Recover instance jobs whose worker heartbeat stopped.

    RQ only declares a dead worker's job abandoned after several minutes. A job
    whose heartbeat is older than STALE_HEARTBEAT_SECONDS is handed to
    recover_interrupted_instance now; recovery is idempotent, so RQ's later
    failure callback for the same job is a no-op. Returns how many jobs were
    handed over.
    """
    from ui.task_logic.job_failure_handlers import instance_job_failure_handler

    now = now or datetime.now(timezone.utc)
    handed_over = 0
    for job in _started_jobs():
        if job.failure_callback != instance_job_failure_handler or not job.args:
            continue
        last_seen = job.last_heartbeat or job.started_at
        if last_seen is None or (now - _as_utc(last_seen)).total_seconds() <= STALE_HEARTBEAT_SECONDS:
            continue
        handed_over += 1
        recover_interrupted_instance(
            job.args[0], job.id, (job.meta or {}).get('lock_token'), "worker heartbeat lost"
        )
    return handed_over
