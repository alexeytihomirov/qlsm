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
# Optional argument: explicit path to the ql-stream-tools checkout — needed
# when this script runs from a git worktree of qlsm, where the relative
# monorepo-sibling walk below cannot reach ql-stream-tools.
overlay=""
if [ $# -ge 1 ]; then
  overlay="$1/live-overlay"
  if [ ! -d "$overlay/lib/qldemo" ]; then
    echo "sync-vendor: $1 is not a ql-stream-tools checkout (no live-overlay/lib/qldemo)" >&2
    exit 1
  fi
else
  for candidate in \
      "$here/../../../../ql-stream-tools/live-overlay" \
      "$here/../../../../../ql-stream-tools/live-overlay" \
      "$here/../../../../../../ql-stream-tools/live-overlay"; do
    if [ -d "$candidate/lib/qldemo" ]; then
      overlay="$candidate"
      break
    fi
  done
fi
if [ -z "$overlay" ]; then
  echo "sync-vendor: ql-stream-tools/live-overlay/lib/qldemo not found near $here" >&2
  echo "sync-vendor: run from a monorepo workspace that has ql-stream-tools checked out," >&2
  echo "sync-vendor: or pass the ql-stream-tools path: bash sync-vendor.sh /path/to/ql-stream-tools" >&2
  exit 1
fi
src="$overlay/lib/qldemo"

# rm+cp instead of rsync --delete: this also runs on the operator's Windows
# Git Bash, which ships no rsync.
dest="$here/vendor/qldemo"
rm -rf "$dest"
mkdir -p "$dest"
cp -a "$src/." "$dest/"

# Map pickup-entity tables: vendored at $here/maps/entities so the vendored
# map-item-resolve.node.js (which walks three dirs up from itself, i.e. to
# this packer dir, then joins maps/entities/{map}.json) finds them on the
# game host — the replay sidecar's pickup events need them to resolve item
# classnames, which !restorecp qlmatch matches against map spawns.
entities_src="$overlay/maps/entities"
if [ -d "$entities_src" ]; then
  rm -rf "$here/maps/entities"
  mkdir -p "$here/maps/entities"
  cp -a "$entities_src/." "$here/maps/entities/"
fi

{
  echo "source: ql-stream-tools/live-overlay/lib/qldemo (production parser)"
  echo "       + ql-stream-tools/live-overlay/maps/entities (pickup tables, vendored to ../maps/entities)"
  echo "synced: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "refresh: bash sync-vendor.sh (see header comment)"
} > "$here/vendor/VENDOR-INFO.txt"
echo "sync-vendor: vendor/qldemo + maps/entities refreshed from $overlay"
