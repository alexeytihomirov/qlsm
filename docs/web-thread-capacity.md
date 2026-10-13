# WebSocket request-thread capacity

## Cause

QLSM runs Flask-SocketIO in `threading` mode under one Gunicorn gthread worker.
Each persistent Engine.IO WebSocket holds one request-pool thread, even while
idle and before Socket.IO namespace authentication. A 12-thread pool can be
exhausted by browser tabs, especially with separate job-events and RCON sockets.
Once exhausted, `/servers`, API requests, and Docker health checks queue behind
WebSockets. Raising Gunicorn's worker timeout does not restore request capacity.

A production Python stack dump confirmed all 12 `ThreadPoolExecutor` threads
inside `engineio.socket._websocket_handler` / `simple_websocket.receive`, not
waiting on SQLite, SSH, or a server-status query.

## Configuration

Compose defaults to `--workers=1 --threads=${WEB_THREADS:-48}`. Override
`WEB_THREADS` in the deployment `.env` if necessary. Plan for peak persistent
WebSockets plus concurrent HTTP requests and health-check headroom. This is a
finite-capacity mitigation, not protection against unlimited connections.

Keep one worker unless Socket.IO transport/session routing is deliberately
redesigned. Do not blindly migrate to eventlet/gevent or add workers: polling
session affinity and blocking integrations need separate verification.

For a larger deployment, isolate Socket.IO from HTTP in separate processes and
route `/socket.io/*` to its dedicated backend, retaining Redis messaging.

## Regression tests

```sh
python -m pytest tests/test_web_thread_capacity.py -q -s
```

The real Gunicorn/Flask-SocketIO fixture reproduces HTTP starvation with 12
WebSockets / 12 threads, then verifies 32 HTTP requests with 24 persistent
WebSockets / 48 threads, and verifies recovery after socket closure. It starts
only short-lived isolated fixture processes, never the development stack.

The fixture and helpers live entirely in `tests/test_web_thread_capacity.py`;
no standalone diagnostic probe is shipped.

## x76 validation

- Exact deployed image: `sha256:1a22dcd12dc2a574e899a5f4e4ffa51dd29b7bef3a7a3804af22c1435dd4a2df`.
- Versions: Gunicorn 26.2.0, Flask-SocketIO 5.7.0, Engine.IO 4.14.0,
  simple-websocket 1.1.0.
- Isolated image: 12/12 reproduced a one-second HTTP timeout; 48/24 completed
  32 HTTP requests, slowest about 11 ms.
- Live bounded test after the Compose hotfix: held 24 additional Engine.IO
  WebSockets and made 36 requests at concurrency 8, slowest about 101 ms.
  `/servers` and `/api/instances/ping` returned 200; `/api/auth/status` correctly
  returned 401 without an authentication cookie. No RCON events were sent.
- External `/servers`: HTTP 200 in about 0.37 s; public ping about 0.42 s.
- Web health changed from `unhealthy` to `healthy`.

Only the web container was recreated, retaining the same image. Workers, Redis,
poller, RCON service, and game instances were not restarted. No management jobs
or transitional instance states were present at preflight. The x76 deployment
has local Compose differences, so its change replaced only the thread argument;
copying the repository's whole Compose file would overwrite unrelated settings.

## Rollback

For x76, the original Compose file is saved at
`/root/.cache/qlsm-web-diagnostics/docker-compose.before.yml`. Restore that file
and recreate only `web` with the already-running image, `--no-deps --no-build
--pull never`, after checking management jobs. Note that restoring 12 threads
also restores the demonstrated starvation threshold.
