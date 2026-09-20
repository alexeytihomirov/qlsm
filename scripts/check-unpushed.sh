#!/usr/bin/env bash
# Report commits on the deploy branch that have not reached `origin` yet.
#
# Why this exists: the deploy pipeline builds from `origin/main`. A commit that
# is only local is invisible to it - the build succeeds on the old code and
# "qlsm was updated" silently means nothing changed. There is no error to
# notice, so the only way to catch it is to look.
#
# Usage:
#   scripts/check-unpushed.sh            # exit 1 if main is ahead of origin/main
#   scripts/check-unpushed.sh --hook     # same report, but always exit 0
#
# The plain form is meant to be run before calling a qlsm task done/ready to
# deploy; --hook is what the post-commit / post-merge hooks use, so a commit is
# never blocked - it only gets a loud reminder.
set -uo pipefail

hook_mode=0
[[ "${1:-}" == "--hook" ]] && hook_mode=1

DEPLOY_BRANCH="${QLSM_DEPLOY_BRANCH:-main}"
REMOTE="${QLSM_DEPLOY_REMOTE:-origin}"
REMOTE_BRANCH="$REMOTE/$DEPLOY_BRANCH"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

# Only the deploy branch matters. A worktree/feature branch is *supposed* to be
# local until it is merged, so warning about it would just be noise.
current="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
if [[ "$current" != "$DEPLOY_BRANCH" ]]; then
    if [[ "$hook_mode" -eq 0 ]]; then
        echo "[check-unpushed] on '$current', not '$DEPLOY_BRANCH' - nothing to check."
        echo "[check-unpushed] Merge into '$DEPLOY_BRANCH' first, then run this again."
    fi
    exit 0
fi

if ! git rev-parse --verify --quiet "$REMOTE_BRANCH" >/dev/null; then
    [[ "$hook_mode" -eq 0 ]] && echo "[check-unpushed] no local ref for $REMOTE_BRANCH - skipped."
    exit 0
fi

ahead="$(git rev-list --count "$REMOTE_BRANCH..$DEPLOY_BRANCH" 2>/dev/null || echo 0)"

if [[ "$ahead" -eq 0 ]]; then
    [[ "$hook_mode" -eq 0 ]] && echo "[check-unpushed] OK: $DEPLOY_BRANCH == $REMOTE_BRANCH, nothing unpushed."
    exit 0
fi

{
    echo ""
    echo "[check-unpushed] !!! $DEPLOY_BRANCH is $ahead commit(s) AHEAD of $REMOTE_BRANCH."
    echo "[check-unpushed] The deploy pipeline builds from $REMOTE_BRANCH, so these commits"
    echo "[check-unpushed] are NOT deployed and the build would silently reuse the old code:"
    git --no-pager log --format='[check-unpushed]   %h %s' "$REMOTE_BRANCH..$DEPLOY_BRANCH"
    echo "[check-unpushed] Push before calling the task done:"
    echo "[check-unpushed]     ./ql-local/git-push.sh qlsm     (from the QL Server monorepo root)"
    echo ""
} >&2

[[ "$hook_mode" -eq 1 ]] && exit 0
exit 1
