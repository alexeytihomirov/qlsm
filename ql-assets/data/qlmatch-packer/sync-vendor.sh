#!/usr/bin/env bash
# Refreshes vendor/qldemo from the production parser in ql-stream-tools.
#
# vendor/qldemo must stay a VERBATIM copy of
#   ql-stream-tools/live-overlay/lib/qldemo/
# (the monorepo sibling checkout) — the exact drift this guards against is
# how the old _tmp/overkilldemos/qldemo-nquery snapshot went stale and
# missed the leftoverPlayerNames/parseUntilLiveIdentity identity fixes.
# ql-stream-tools is a separate git repo, so qlsm's own CI can't diff
# against it; re-run this script (from anywhere inside the monorepo
# workspace) whenever lib/qldemo changes, and commit the result.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src=""
for candidate in \
    "$here/../../../../ql-stream-tools/live-overlay/lib/qldemo" \
    "$here/../../../../../ql-stream-tools/live-overlay/lib/qldemo" \
    "$here/../../../../../../ql-stream-tools/live-overlay/lib/qldemo"; do
  if [ -d "$candidate" ]; then
    src="$candidate"
    break
  fi
done
if [ -z "$src" ]; then
  echo "sync-vendor: ql-stream-tools/live-overlay/lib/qldemo not found near $here" >&2
  echo "sync-vendor: run from a monorepo workspace that has ql-stream-tools checked out" >&2
  exit 1
fi

# rm+cp instead of rsync --delete: this also runs on the operator's Windows
# Git Bash, which ships no rsync.
dest="$here/vendor/qldemo"
rm -rf "$dest"
mkdir -p "$dest"
cp -a "$src/." "$dest/"
{
  echo "source: ql-stream-tools/live-overlay/lib/qldemo (production parser)"
  echo "synced: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "refresh: bash sync-vendor.sh (see header comment)"
} > "$here/vendor/VENDOR-INFO.txt"
echo "sync-vendor: vendor/qldemo refreshed from $src"
