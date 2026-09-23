#!/bin/sh
# QLSM coordinated restart watcher.
#
# Why this exists: addons register their blueprints inside create_app(), and
# Flask cannot hot-add or drop a blueprint on a live app. An addon installed
# at runtime therefore stays inert until the process runs create_app() again.
#
# How it works: POST /api/system/restart touches /app/data/.restart-stamp.
# ./data is bind-mounted into every app container (docker-compose.yml, the
# x-app anchor), so a single touch reaches web, worker and poller at once --
# no extra control channel and no subscriber code in any of the services.
#
# entrypoint.sh starts this in the background and then execs the real
# command, so the app keeps PID 1 and `docker stop` behaves as usual. The
# signal sent on a stamp change is chosen by entrypoint.sh per service:
#
#   HUP  (web/gunicorn)  -- gunicorn gracefully replaces its worker, which
#                           re-runs create_app(); the container itself keeps
#                           running, so this watcher must keep watching.
#   TERM (worker/poller) -- warm shutdown (RQ finishes its current job), the
#                           container exits and `restart: unless-stopped`
#                           brings it back on the same image.
#
# Not started for rcon (python -m rcon_service never calls create_app(), so
# addons do not live there) nor for one-off commands.

set -eu

STAMP_FILE="${QLSM_RESTART_STAMP:-/app/data/.restart-stamp}"
SIGNAL="${QLSM_RESTART_SIGNAL:-TERM}"
INTERVAL="${QLSM_RESTART_POLL_INTERVAL:-2}"

stamp_mtime() {
    stat -c %Y "$STAMP_FILE" 2>/dev/null || echo 0
}

seen="$(stamp_mtime)"
echo "[restart-watcher] watching $STAMP_FILE (signal=SIG$SIGNAL, interval=${INTERVAL}s)"

while sleep "$INTERVAL"; do
    now="$(stamp_mtime)"
    [ "$now" = "$seen" ] && continue

    echo "[restart-watcher] restart requested -- sending SIG$SIGNAL to PID 1"
    if ! kill -"$SIGNAL" 1; then
        echo "[restart-watcher] ERROR: failed to signal PID 1, will retry next poll" >&2
        continue
    fi
    seen="$now"

    # SIGTERM takes the whole container down; nothing left to watch. SIGHUP
    # leaves it running, so keep going and stay ready for the next request.
    [ "$SIGNAL" = "HUP" ] || exit 0
done
