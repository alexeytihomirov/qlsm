"""Cross-process "a background job finished" push notifications.

Core and addon background tasks run in an RQ worker process, separate from
the Flask web process(es) that hold browser SocketIO connections. Publishing
straight to Redis here and re-emitting from a listener running inside the web
process (job_events_listener.py) is the same split ui/redis_listener.py
already uses for RCON output -- a worker process cannot call socketio.emit()
itself and have it reach a browser connected to a different process.

Single flat channel, no per-host/per-instance room: qlsm is an operator's own
tool with one browser tab worth of interested parties at a time, so there is
no multi-tenant reason to scope delivery narrower than "every connected
browser sees every job's outcome."
"""
import json
import logging

from ui.rcon_transport import get_redis_client

log = logging.getLogger(__name__)

JOB_EVENTS_CHANNEL = 'qlsm:job_events'


def publish_job_event(source, status, message, **extra):
    """Publish one job-completion event.

    `source` identifies what finished (e.g. "<addon-id>.<job-name>"),
    `status` is "success" or "error", `message` is the human-readable text a
    toast should show. Extra keyword args (e.g. instance_id, filename) ride
    along for a listener that wants to filter/label further; the frontend
    today only reads status/message.

    Never raises -- a job whose Redis publish fails should not lose its own
    result because the notification could not be delivered.
    """
    payload = {'source': source, 'status': status, 'message': message, **extra}
    try:
        get_redis_client().publish(JOB_EVENTS_CHANNEL, json.dumps(payload))
    except Exception as e:
        log.warning('Failed to publish job event (%s): %s', source, e)
