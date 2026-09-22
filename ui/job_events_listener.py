"""Background thread relaying ui.job_events publications to browsers.

Mirrors ui/redis_listener.py's RCON listener (same subscribe-loop/reconnect
shape), but far simpler: one channel, no room routing -- every message is
re-emitted to every connected browser as-is. Started next to RedisListener in
ui/__init__.py, under the same "only where SocketIO has a message queue"
gate, since without message_queue an emit here would never leave this worker
process anyway.
"""
import json
import logging
import threading

import redis

from ui.job_events import JOB_EVENTS_CHANNEL

log = logging.getLogger(__name__)


class JobEventsListener:
    """Background listener bridging Redis job-event publications to SocketIO."""

    def __init__(self, socketio, redis_url):
        self.socketio = socketio
        self.redis_url = redis_url
        self._thread = None
        self._running = False
        self._stop_event = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            log.warning('Job events listener already running')
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()
        log.info('Job events listener started')

    def stop(self):
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        log.info('Job events listener stopped')

    def _listen(self):
        import os
        redis_password = os.environ.get('REDIS_PASSWORD')

        while self._running and not self._stop_event.is_set():
            r = None
            pubsub = None
            try:
                kwargs = {'decode_responses': True}
                if redis_password:
                    kwargs['password'] = redis_password
                r = redis.from_url(self.redis_url, **kwargs)
                pubsub = r.pubsub()
                pubsub.subscribe(JOB_EVENTS_CHANNEL)
                log.info('Subscribed to %s', JOB_EVENTS_CHANNEL)

                while not self._stop_event.is_set():
                    message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if not message:
                        continue
                    if message['type'] != 'message':
                        continue
                    try:
                        payload = json.loads(message['data'])
                    except (TypeError, ValueError):
                        log.error('Invalid JSON on %s: %r', JOB_EVENTS_CHANNEL, message['data'])
                        continue
                    self.socketio.emit('job:completed', payload)

            except Exception as e:
                log.error('Job events listener error: %s', e)
                if not self._stop_event.is_set():
                    log.info('Attempting to reconnect in 5 seconds...')
                    self._stop_event.wait(timeout=5.0)
            finally:
                if pubsub:
                    try:
                        pubsub.close()
                    except Exception:
                        pass
                if r:
                    try:
                        r.close()
                    except Exception:
                        pass

        log.info('Job events listener exiting')
