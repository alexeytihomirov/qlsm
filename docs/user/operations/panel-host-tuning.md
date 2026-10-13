# Sizing and Tuning the QLSM Host

This page covers the machine running the **QLSM panel and Docker stack**, not
remote Quake Live game servers. Panel tuning does not change game-server tick
rates, networking, or player latency.

## Choose resources for the whole machine

For a small, panel-only deployment, **2 GB RAM is a practical starting point**,
not a hard minimum or a guarantee. A 1 GB machine can run QLSM, but leaves less
headroom for management jobs, additional services, and updates.

Allow additional CPU, RAM, and disk space if the same machine also runs:

- Quake Live instances through the self-host provider;
- a GitHub Actions runner, especially one building images;
- the optional Loki/Grafana logging stack;
- unrelated web applications or APIs.

Swap can absorb short memory spikes, but sustained swapping makes the panel
slow. More request threads cannot fix insufficient RAM or a busy disk.

Check the host and containers before changing settings:

```bash
free -h
vmstat 1 5
df -h /
docker stats --no-stream
docker system df
```

Look at available memory, repeated swap-in/swap-out activity (`si` / `so` in
`vmstat`, especially after the first row), container memory use, and free disk
space. Allocated swap alone does not prove active memory pressure. Leave room
for the old and new image during updates; do not delete QLSM data volumes to
reclaim disk space.

## Why open browser tabs can slow the panel

QLSM uses a threaded web worker. Each persistent Socket.IO WebSocket occupies
one request thread. Browser tabs may have separate job-notification and RCON
connections, so a tab is not necessarily one connection.

If those connections fill the pool, normal page/API requests and health checks
have to wait—even when CPU usage is low. Closing unnecessary tabs can provide
immediate relief, but the pool also needs capacity for ordinary HTTP traffic.

The shipped Compose configuration defaults to **48 threads** and supports
`WEB_THREADS` in `.env`:

```dotenv
WEB_THREADS=48
```

Start with the default. Size the pool above peak persistent connections, with
headroom for simultaneous HTTP requests and health checks. Raise it only when
measurements show request-capacity pressure, then check latency and memory
again. There is no universal safe maximum: increasing it also permits more
concurrent work and can increase memory consumption.

Keep the shipped single-worker setting. Adding Gunicorn workers or switching
async frameworks is not an interchangeable tuning knob; Socket.IO connection
routing and application integrations need separate verification.

## Apply a thread setting safely

Run these commands from **your deployment directory**, where the active
`docker-compose.yml` and `.env` live. Installation paths vary; `~/qlsm`,
`/opt/qlsm`, and custom paths are all possible.

1. Wait for provisioning, configuration, backup/restore, and restart jobs to
   finish. Avoid overlapping an automated deployment.
2. Edit `.env` and set `WEB_THREADS=48` (or the measured value you need).
3. Check the resolved web command without printing the rest of your configuration:

    ```bash
    docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["web"]["command"])'
    ```

    The output should contain `--threads=48` when that is your selected value.

    **Older Compose files may hard-code `--threads=12`.** Setting `.env` alone
    does not change such a command. Update the web command entry to:

    ```yaml
    - --threads=${WEB_THREADS:-48}
    ```

    Preserve your deployment's custom ports, volumes, and proxy configuration;
    do not blindly replace the entire Compose file.

4. Recreate only the web service, retaining the locally available image:

    ```bash
    docker compose up -d --no-deps --no-build --pull never --wait web
    ```

    This briefly interrupts panel requests and browser WebSockets. It does not
    restart the worker, poller, Redis, RCON service, or Quake Live instances.
    `docker compose restart web` is **not** sufficient to apply a changed command.

5. Check health and the actual running command:

    ```bash
    docker compose ps web
    WEB_CONTAINER=$(docker compose ps -q web)
    docker inspect "$WEB_CONTAINER" --format 'command={{json .Config.Cmd}} health={{.State.Health.Status}}'
    docker compose logs --since=5m web
    ```

## Verify responsiveness

Check your actual panel URL; replace the example domain:

```bash
curl -sS --max-time 10 -o /dev/null \
  -w 'HTTP %{http_code}; first byte %{time_starttransfer}s; total %{time_total}s\n' \
  https://qlsm.example.com/servers
```

Repeat with your usual browser tabs open, and check that the Servers page loads
its data and RCON still connects. A fast HTML response alone does not prove that
all authenticated API requests are healthy. A protected API returning `401`
without a login cookie is expected, not an availability failure.

If the panel remains slow, distinguish the causes:

- **Web unhealthy, requests wait, CPU low:** inspect request/WebSocket capacity.
- **Sustained swapping or high disk wait:** reduce other workloads or resize the host.
- **Only one API is slow:** investigate that endpoint and its dependencies.
- **Only the public URL is slow:** compare against your local reverse proxy;
  DNS, TLS, or an upstream proxy may be responsible.

Do not restart game instances or re-run game-host setup just because the panel
is slow.

## Updates and larger deployments

The thread setting is supplied by the host's Compose file. Pulling a new image
and recreating containers preserves it **as long as the updater uses that same
file and does not overwrite it**. Replacing it with an older file can restore
the old hard-coded limit. Check the resolved command after changing your update
workflow or replacing deployment configuration.

A larger thread pool adds finite headroom; it does not remove the architectural
limit. If normal usage regularly approaches that limit, consider separating
HTTP/API and Socket.IO into dedicated processes with appropriate proxy routing,
rather than increasing thread counts indefinitely.

## Related pages

- [Installation and configuration](../getting-started/installation.md)
- [Deployment troubleshooting](../help/deployment-troubleshooting.md)
- [RCON console](rcon-console.md)
- [Global RCON](global-rcon.md)
