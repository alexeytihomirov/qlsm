#!/bin/sh
# Recreate the qlsm Portainer stack on home-docker after a fresh `docker build`.
# Run from a Woodpecker pipeline step (docker:cli image) — see ../.woodpecker.yml.
#
# All secrets come from Woodpecker's own secret store (from_secret env vars),
# not host files. This script runs via DooD (docker.sock), so sibling
# `docker run -v ...` calls resolve paths on the *host*, not this step's own
# filesystem — that's why QLSM_STACK_ENV gets written into the bind-mounted
# /hostdeploy dir (host path /home/home/qlsm/deploy) instead of a plain tmpfile.
set -eu

apk add --no-cache curl >/dev/null 2>&1

URL="http://192.168.100.100:9001"
ENDPOINT_ID=1
JQ=ghcr.io/jqlang/jq:1.7
NAME=qlsm
HOST_DEPLOY_DIR=/home/home/qlsm/deploy
STEP_DEPLOY_DIR=/hostdeploy
CI_ENV_FILE="$STEP_DEPLOY_DIR/.ci-stack.env"

[ -n "${PORTAINER_PASSWORD:-}" ] || { echo "PORTAINER_PASSWORD missing (set as Woodpecker secret)"; exit 1; }
[ -n "${QLSM_STACK_ENV:-}" ] || { echo "QLSM_STACK_ENV missing (set as Woodpecker secret)"; exit 1; }

printf '%s\n' "$QLSM_STACK_ENV" > "$CI_ENV_FILE"
trap 'rm -f "$CI_ENV_FILE"' EXIT

# deploy/portainer-stack.home.yml only exists in this step's fresh checkout;
# the jq sibling container (DooD) can only see host paths, so copy it into the
# bind-mounted host-visible dir alongside .ci-stack.env.
cp deploy/portainer-stack.home.yml "$STEP_DEPLOY_DIR/portainer-stack.home.yml"

TOKEN=$(curl -sk -X POST "$URL/api/auth" -H 'Content-Type: application/json' \
  -d "{\"Username\":\"${PORTAINER_USER:-admin}\",\"Password\":\"$PORTAINER_PASSWORD\"}" \
  | docker run --rm -i "$JQ" -r '.jwt // empty')
[ -n "$TOKEN" ] || { echo "Portainer auth failed"; exit 1; }

api() { curl -sk -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' "$@"; }

ID=$(api "$URL/api/stacks" | docker run --rm -i "$JQ" -r --arg n "$NAME" '.[]? | select(.Name==$n) | .Id' | head -1)
[ -n "$ID" ] || { echo "Stack $NAME not found in Portainer — bootstrap it once (home-infra/scripts/qlsm-bootstrap.sh + qlsm-portainer-deploy.sh)"; exit 1; }

payload=$(docker run --rm \
  -v "$HOST_DEPLOY_DIR":/b:ro \
  "$JQ" -n \
  --rawfile compose /b/portainer-stack.home.yml \
  --rawfile envf /b/.ci-stack.env \
  '($envf | split("\n") | map(select(length > 0)) | map(select(startswith("#")|not)) |
    map(select(test("^[A-Za-z_][A-Za-z0-9_]*="))) |
    map(capture("^(?<name>[^=]+)=(?<value>.*)$")) | map({name,value})) as $env |
    {stackFileContent: $compose, env: $env, prune: true}')

resp=$(api -X PUT -d "$payload" "$URL/api/stacks/${ID}?endpointId=${ENDPOINT_ID}")
msg=$(printf '%s' "$resp" | docker run --rm -i "$JQ" -r '.message // empty')
if [ -n "$msg" ]; then echo "UPDATE FAILED: $msg"; exit 1; fi
echo "stack config updated"

i=1
while [ "$i" -le 15 ]; do
  if curl -sf http://192.168.100.100:8090/api/instances/ping; then
    echo
    echo "deploy OK"
    exit 0
  fi
  i=$((i + 1))
  sleep 3
done

echo "health check failed after retries"
exit 1
