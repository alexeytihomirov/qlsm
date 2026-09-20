#!/usr/bin/env bash
# Point this clone's git hooks at scripts/git-hooks (shared by every worktree,
# because core.hooksPath lives in the common config and the path is resolved
# relative to each worktree's top level). Idempotent.
set -euo pipefail
top="$(git rev-parse --show-toplevel)"
cd "$top"
current="$(git config --get core.hooksPath || true)"
if [[ "$current" == "scripts/git-hooks" ]]; then
    echo "[git-hooks] already installed (core.hooksPath=scripts/git-hooks)."
    exit 0
fi
if [[ -n "$current" ]]; then
    echo "[git-hooks] core.hooksPath is already set to '$current' - leaving it alone." >&2
    exit 0
fi
git config core.hooksPath scripts/git-hooks
echo "[git-hooks] installed: core.hooksPath=scripts/git-hooks"
