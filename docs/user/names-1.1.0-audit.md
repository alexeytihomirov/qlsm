# names.py 1.1.0 audit decisions

Scope: independently assessed findings F1–F4 only, plus the explicitly compatible
single-GET reduction from F5. No deployment or application-version bump.

| Finding | Independent decision | Delivered behavior |
|---|---|---|
| F1: global self-write flag (minqlx) | Accept | Per-SteamID guard, raw cvars equality skip, ignore only own name event, synchronous try/finally cleanup and disconnect cleanup. |
| F2: stale accepted-client baseline (both) | Accept | Refresh baseline on genuine client base rename while invalidating registration. Never replace an existing original baseline with a command-created alias. |
| F3: stale registration restored despite enforcement (both) | Accept | Recheck enforcement-aware base eligibility before rewriting incoming name; retain ineligible history on load. |
| F4: online clients after reload (both) | Accept | Seed absent baseline from fresh incoming name. Extended distinguishes absent cache from known-negative None and hydrates once; commands initialize absent baseline before own assignment. |
| F5: synchronous Redis hot-hook work (minqlx) | Acknowledge | One GET per relevant name event, not EXISTS + GET. No session cache, TTL or new refresh policy; external add/edit/delete visibility retained. |

The existing minqlxtended per-player helper uses the same synchronous cleanup
boundary, including blocked/error writes and non-name reentry. This is bounded
self-assignment lifecycle handling, not a new alias, freshness or ownership policy.
Public commands, runtime handler signatures, Redis keys/APIs, validation ordering,
case comparisons and rankcolors ownership are preserved.

## Evidence and test boundaries

Original independent research is preserved separately, unedited (its historical
source references point to the original checkout, not this patch):
- [First review](research/names-1.1.0-first-review.md)
- [Independent assessment](research/names-1.1.0-assessment.md)

`tests/names_offline.py` supplies explicitly **OFFLINE** Redis/engine doubles.
It runs the actual four plugin files and creates fresh pre-write Player snapshots
for events/commands; old objects retain their cached display/userinfo snapshots.
Transport models synchronous userinfo diff/merge, no-diff, blocked and error paths.
No native server, Steam endpoint or Redis connection is used. Color-hook order
controls use an explicitly labeled rankcolors-like double, not deployed code.

For stronger local source-contract checks, set `NAMES_ENGINE_ROOT=/workspace`:
the harness AST-extracts actual Player name/cvars getters and setters, clean_name,
and extended helper methods from the inspected engine checkouts (minqlx
`fbdd915185337791d8e209dc4b686a1ee60d3721`, minqlxtended
`a3de9471ab5c4c5f712b47923cd6b964312bcefd`). Transport/backing storage are still
offline doubles, not native integration. The ordinary run needs no engine checkout.

```sh
NAMES_ENGINE_ROOT=/workspace .venv/bin/python -m pytest \
  tests/test_names_lifecycle.py tests/test_names_storage.py -q
.venv/bin/python -m pytest tests/test_names_lifecycle.py tests/test_names_storage.py \
  tests/test_builtin_preset_plugin_drift.py \
  tests/test_minqlxtended_plugin_baseline.py tests/test_plugin_manifests.py -q
```

Tests cover accepted findings, both runtime signatures and all four copies,
re-register/reset, commands immediately after reload, baseline-versus-alias
semantics, mixed-case policy, positive/negative/absent caches, external Redis
add/edit/delete, no-name/no-diff/reentrant events, guard cleanup, stale snapshots,
validation compatibility and both tier-color hook orders. Both pool manifests
refresh only the names.py digest; origins and upstream pins are unchanged.

Verified results: **140 lifecycle/storage tests passed** with actual engine
getter/setter extraction and 100% statement/branch coverage of all four plugin
copies (offline transport). The ordinary scoped lifecycle/storage + drift +
both-runtime manifest/baseline run passed **156 tests**. Each run reports one
pre-existing flask_rq2/pkg_resources deprecation warning. `git diff --check`
passes; all modified/new Python sources are below 300 nonblank/noncomment lines.

Worktree setup is not claimed complete: its own Python environment has backend
dependencies plus pytest/pytest-cov. The full setup script previously stopped at
missing pnpm. No migrations, preset synchronization, shared DB operations or dev
servers were run for this patch. A pnpm installation attempt required approval
because package threat-intelligence lookup was incomplete. GitHub CLI is unavailable;
no commit, push, PR, merge or deployment was attempted.
