#!/usr/bin/env bash
# Report commits on the deploy branch that have not reached the remote yet.
#
# Why this exists: the deploy pipeline builds from origin/main. A commit that
# only exists locally produces no error anywhere - the build runs green on the
# previous code, and "qlsm was updated" silently means nothing changed.
#
# Why it asks the remote instead of trusting `git status`: the monorepo's
# ql-local/git-push.sh pushes to a tokenised URL (`git push https://<token>@...
# HEAD:main`) rather than to the named remote, and git only updates
# refs/remotes/origin/main when you push to the remote by name. So after a
# perfectly successful push, `git status` still claims "ahead of origin/main by
# N" until something happens to fetch. A check built on the local ref would cry
# wolf constantly - which is exactly how a genuine missed push stays invisible.
# So: ask the remote for the real head, and treat the local origin/main ref as
# a hint only.
#
# Usage:
#   scripts/check-unpushed.sh            # exit 1 if main is ahead of the remote
#   scripts/check-unpushed.sh --hook     # same report, but always exit 0
#   scripts/check-unpushed.sh --offline  # never touch the network (local ref)
set -uo pipefail

hook_mode=0
offline=0
for arg in "$@"; do
    case "$arg" in
        --hook) hook_mode=1 ;;
        --offline) offline=1 ;;
    esac
done

DEPLOY_BRANCH="${QLSM_DEPLOY_BRANCH:-main}"
REMOTE="${QLSM_DEPLOY_REMOTE:-origin}"
REMOTE_REF="$REMOTE/$DEPLOY_BRANCH"

say() { printf '[check-unpushed] %s\n' "$*" >&2; }

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

# Only the deploy branch matters. A worktree/feature branch is *supposed* to be
# local until it is merged, so warning about it would just be noise.
current="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
if [[ "$current" != "$DEPLOY_BRANCH" ]]; then
    if [[ "$hook_mode" -eq 0 ]]; then
        say "on '$current', not '$DEPLOY_BRANCH' - nothing to check."
        say "Merge into '$DEPLOY_BRANCH' first, then run this again."
    fi
    exit 0
fi

git rev-parse --verify --quiet HEAD >/dev/null || exit 0

# Real remote head, or empty if we could not ask (offline, no auth, no remote).
# ls-remote is read-only and needs no token for a public repo; the prompt guards
# make it fail fast instead of popping Git Credential Manager.
remote_head=""
if [[ "$offline" -eq 0 ]]; then
    ls_timeout=20
    [[ "$hook_mode" -eq 1 ]] && ls_timeout=8
    runner=()
    # Must be GNU timeout, not Windows' timeout.exe, which takes different args.
    [[ -x /usr/bin/timeout ]] && runner=(/usr/bin/timeout "$ls_timeout")
    raw="$(GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=echo GCM_INTERACTIVE=Never "${runner[@]}" git ls-remote --heads "$REMOTE" "$DEPLOY_BRANCH" 2>/dev/null || true)"
    remote_head="$(awk 'NR==1{print $1}' <<<"$raw")"
fi

source_label="the remote"
if [[ -z "$remote_head" ]]; then
    remote_head="$(git rev-parse --verify --quiet "$REMOTE_REF" || true)"
    source_label="the local $REMOTE_REF ref (remote unreachable - may be stale)"
fi

if [[ -z "$remote_head" ]]; then
    [[ "$hook_mode" -eq 0 ]] && say "no $REMOTE_REF and the remote is unreachable - skipped."
    exit 0
fi

if ! git cat-file -e "${remote_head}^{commit}" 2>/dev/null; then
    say "$REMOTE has $DEPLOY_BRANCH at ${remote_head:0:8}, which is not in this clone."
    say "Run 'git fetch $REMOTE' first - this clone is behind or has diverged."
    [[ "$hook_mode" -eq 1 ]] && exit 0
    exit 1
fi

ahead="$(git rev-list --count "${remote_head}..HEAD" 2>/dev/null || echo 0)"

if [[ "$ahead" -eq 0 ]]; then
    if [[ "$hook_mode" -eq 0 ]]; then
        say "OK: $DEPLOY_BRANCH is fully pushed (checked against $source_label)."
        stale="$(git rev-parse --verify --quiet "$REMOTE_REF" || true)"
        if [[ -n "$stale" && "$stale" != "$remote_head" ]]; then
            say "Note: the local $REMOTE_REF ref is stale (${stale:0:8}), so 'git status'"
            say "will keep claiming you are ahead. 'git fetch $REMOTE' clears that."
        fi
    fi
    exit 0
fi

{
    echo ""
    printf '[check-unpushed] !!! %s is %s commit(s) AHEAD of %s (checked against %s).\n' \
        "$DEPLOY_BRANCH" "$ahead" "$REMOTE_REF" "$source_label"
    echo "[check-unpushed] The deploy pipeline builds from $REMOTE_REF, so these commits"
    echo "[check-unpushed] are NOT deployed and a build would silently reuse the old code:"
    git --no-pager log --format='[check-unpushed]   %h %s' "${remote_head}..HEAD"
    echo "[check-unpushed] Push before calling the task done:"
    echo "[check-unpushed]     ./ql-local/git-push.sh qlsm     (from the QL Server monorepo root)"
    echo ""
} >&2

[[ "$hook_mode" -eq 1 ]] && exit 0
exit 1
