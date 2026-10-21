# Fresh first-pass names.py review (review only)

## Scope and provenance

Loaded the original installed `minqlx-plugin-review` skill and `qlsm-python-plugin-delivery`, and read `/workspace/qlsm/CLAUDE.md`. This is a new source review, not an assessment of earlier findings or a patch review. No upstream freshness certification of the skill was requested or performed.

QLSM HEAD: `fc3c28d3e58bbae9c847da2139f5c8960e3d94fd`; origin/main: `1396e100d9439aee461fc4c6845163b44aece6e0`. QLSM `git status --porcelain=v1` was empty before and after the probes. All four requested names.py paths were confirmed tracked. No plugin source, server, credentials, remote repository, or live service was changed/contacted.

Exact reviewed source references below use these aliases (line numbers are identical within each byte-identical pair):

| Alias | Absolute path | SHA256 |
|---|---|---|
| M | `/workspace/qlsm/ql-assets/data/minqlx-plugins/names.py` | `662587a0649953c588b18e08eca598f903681ca51ce11c186de722fcb40a6412` |
| MP | `/workspace/qlsm/configs/presets/_builtin/default/scripts/names.py` | `662587a0649953c588b18e08eca598f903681ca51ce11c186de722fcb40a6412` |
| X | `/workspace/qlsm/ql-assets/data/minqlxtended-plugins/names.py` | `ed7713340354e6886872baa27419c7ae333d1e0749f8ad4904db90d6520a10ad` |
| XP | `/workspace/qlsm/configs/presets/_builtin/default-minqlxtended/scripts/names.py` | `ed7713340354e6886872baa27419c7ae333d1e0749f8ad4904db90d6520a10ad` |

Engine source commits inspected:
- `/workspace/minqlx`: `fbdd915185337791d8e209dc4b686a1ee60d3721`.
- `/workspace/minqlxtended`: `a3de9471ab5c4c5f712b47923cd6b964312bcefd`.

Rankcolors source located at `/workspace/qlsm-plugins-x76-notices/rankcolors/rankcolors.py`, SHA256 `a19a40822a646b1ed28510bd1942611d23525e398ab1b3c67659c9aa1ce9110e`. Its git metadata points to an unavailable original worktree path, so its revision could not be resolved; this file hash, not a claimed commit, identifies what was inspected. No rankcolors file was found in the QLSM tree searched, and no minqlxtended rankcolors port was found in this workspace. It is not asserted that this external copy is currently deployed.

## Findings

### F1 — Medium: global self-write flag silently swallows another player's rename (M, MP)

**Source:** M/MP:35–36, 41–47, 53–57, 95–98.

`name_set` means “skip the next userinfo event from anyone”, not “ignore this particular self-generated name write”. Assigning a name already present in userinfo generates no changed keys and therefore no userinfo event. The flag then survives and consumes the next unrelated event. It also survives the assigning player's disconnect because disconnect does not clear it.

**Realistic trigger:** Player A connects with exactly the already registered colored spelling. `handle_player_loaded(A)` sets the global flag and assigns the same spelling. Player B next changes their base nickname. B's event is skipped: B's old registration remains in Redis and B's client-name cache remains old. A later color change can then resurrect B's old name. An unrelated non-name userinfo update could consume the flag instead; the bug is event-order dependent, not every connect.

**Offline evidence:** For each minqlx copy, same-value A assignment followed by B's `NewB` update left B's registration `^3B`, cache `B`, and display `NewB`. The corresponding minqlxtended equality/per-player control deleted B's stale registration correctly.

**Minimal fix:** Remove skip-next state and make same-base/color-only events idempotent, with per-player comparison against actual intended values if self-write tracking is required. Merely changing the bool to a per-player flag still needs a no-event/rejected-write strategy. X/XP already fix this demonstrated cross-player/no-diff case and are not included in F1.

### F2 — Medium: a legitimate base-name change leaves the comparison cache stale, so re-registering the new name is undone (all four)

**Source:** M/MP:59–68, 81–98; X/XP:69–82, 98–117.

When a registered player changes from base name `Old` to `New`, the mismatch branch removes the registration but never updates `steam_names[sid]`. If the player immediately registers colors for `New`, the registration command succeeds using the current displayed clean name, but still does not refresh that stale baseline. The next ordinary color-only update for `New` is compared against `Old` and deletes the newly saved registration.

**Realistic trigger:** Change nickname, run `!name ^3New`, then let the client resend its new name with different colors, or let rankcolors perform a tier-color rewrite. No concurrent players or reload is needed. A further unregistered name event happening before the command can incidentally refresh the baseline, so not every rename sequence fails.

**Offline evidence:** All four source files reproduced `Old -> New -> !name ^3New -> ^4New`, resulting in no Redis registration and cache still `Old` despite displayed clean name `New`.

**Minimal fix:** On every accepted base-name change, refresh the per-player client-name baseline as part of the same transition that clears stale registration. Keep successful command-created aliases consistent with that baseline when enforcement is off. Do not use a one-event global skip. Preserve an intentional enforcement-off alias policy rather than accidentally treating a server-set alias as a Steam persona.

### F3 — Medium: a stale registered base name can be reapplied even with Steam-name enforcement enabled (all four)

**Source:** M/MP:41–47 versus 60–65; X/XP:47–54 versus 69–78.

The load handler checks that the stored clean name matches the current clean name, but leaves an incompatible registration available. The userinfo handler later only checks incoming name against the cached current baseline, then unconditionally returns the stored name. Thus the load-time enforcement decision is not maintained on the rewrite path.

**Realistic trigger:** Redis contains `^2Old` from a previous session. Player reconnects as `New`. Load correctly declines to apply `Old` with enforcement enabled. A subsequent color-only update such as `^4New` matches the cached `New` baseline and restores `^2Old`. Rankcolors color writes are one practical source of such an update.

**Offline evidence:** Every reviewed source changed display from `New` back to clean name `Old` while enforcement was true. Executing the actual external rankcolors userinfo handler in both hook orders also resurrected `Old`: final raw names were `^4Old` (names first) and `^2Old` (rankcolors first).

**Minimal fix:** Before restoring any registration, enforce that its clean base matches the accepted client base under the same case-insensitive policy as load/command validation. Clear or mark stale registrations unusable on the mismatch load path. When enforcement is disabled, preserve the deliberate alias behavior. Centralize validation so load and userinfo do not diverge.

### F4 — Medium: mid-session reload does not initialize existing players' registration state (all four; different symptoms)

**Source:** M/MP:35–39, 60–64; X/XP:34–45, 47–51, 69–75.

Both constructors start with empty state and populate it on future connect/loaded events. Already-connected players do not reconnect simply because this plugin was reloaded.

- **M/MP:** A name userinfo change with an existing Redis registration reaches `self.steam_names[player.steam_id]` and raises `KeyError`. The real low-level client-command handler catches/logs the exception and lets the command proceed; it does not establish the missing cache, so later changes repeat the failure.
- **X/XP:** Missing `registered_names` is treated the same as “Redis has no registration”. The first and following name events never hydrate it, so persisted colors are silently ignored for an already-online player until another loaded event or registration command establishes state. This is not the same exception as the minqlx issue.

**Realistic trigger:** Reload `names` while a player with a saved registration remains connected, then send a fresh `name` userinfo/color update.

**Offline evidence:** Direct handler invocation raised `KeyError(76561198000000001)` for each minqlx copy. Each minqlxtended copy retained Redis `^2Same` while accepting raw `^4Same` and never populating the registration cache.

**Minimal fix:** Provide explicit bounded hydration for online players at load or a missing-versus-negative-cache sentinel with one-time lazy initialization. Use `.get` for missing baselines, not subscripting. Do not replace this with a Redis lookup on every hot event. Establish the current baseline from fresh client userinfo when available; a plugin reload alone cannot discover a newly changed Steam persona remotely. Test reload followed by fresh client name input, not merely reload followed by unchanged cached display.

### F5 — Medium (performance): synchronous Redis reads in the minqlx userinfo hot hook (M, MP)

**Source:** M/MP:59–64. Redis wrapper contract: `/workspace/minqlx/python/minqlx/database.py`:126–134.

Every incoming name change performs `EXISTS`; preserving a registered spelling also performs `GET`, synchronously on the game thread. Repeated alternating color spellings cause this work repeatedly even though the effective registered display does not need to change. The wrapper implements membership with Redis `exists`, not an in-memory test.

**Realistic trigger:** A registered client repeatedly changes color spelling, or another plugin repeatedly applies name colors. The exact accepted client rate is engine/deployment dependent; no claim is made that an arbitrary rate reaches the hook on a production server.

**Offline evidence:** 100 accepted name-change callbacks produced exactly 100 membership checks plus 100 reads for each minqlx file. Both minqlxtended files produced zero DB operations in the same hot-hook sequence after hydration. This establishes round-trip count, not a measured frame-latency or denial-of-service threshold.

**Minimal fix:** Cache registration values with a distinct negative-cache state; hydrate at a bounded lifecycle boundary, update on commands/reset, and clear on disconnect. Preserve a safe missing-cache reload path (F4). External Redis edits require an explicit refresh/invalidation policy if they are intended to be noticed immediately.

## Engine contracts and non-findings

- Actual minqlx `Player.name` setter (`_player.py`:175–187) sets userinfo through the cvars setter (`126–138`), not a Steam profile API. Minqlxtended equivalents are `_player.py`:212–230 and 304–315. `clean_name` is color-stripped in-game state; “Steam name enforcement” here is only a local-name comparison. No new authenticated Steam-persona guarantee is proposed.
- Minqlx `_handlers.py`:141–163 and minqlxtended `_handlers.py`:683–717 only dispatch userinfo if the submitted info differs. This supports the absent-self-event trigger in F1. The inspected native APIs execute `client_command` synchronously: minqlx `python_embed.c`:375–385 / `hooks.c`:80–88, minqlxtended `src/python/python_embed.c`:787–803 / `src/server/hooks.c`:251–302.
- Hook contracts match the requested files: minqlx connect(player), userinfo(player, changed); minqlxtended connect(player, is_bot), userinfo(player, changed, infostring). Actual minqlxtended `_check_handler_signature` was executed against bound handlers, and all reviewed handler arities passed. Decorator/setting/Return APIs used by X/XP exist in the inspected engine. This is not a full native plugin-loader integration run.
- No background workers, delayed callbacks, recurring timers, or saved Player objects exist in these names.py copies. No concrete wrong-thread game mutation, deferred slot-reuse mutation, or worker-unload leak was found. Disconnect clears existing caches; F1 remains the concrete stale global-state lifecycle issue. Same-SteamID duplicate simultaneous connections were not assumed.
- X/XP `_assign_name` uses a per-SteamID flag and checks exact cvars equality; the demonstrated minqlx F1 does not carry over. A different plugin blocking/rewriting the underlying client command could theoretically leave the per-SteamID flag pending; that is a conditional concern, not an additional confirmed finding in the inspected names/rankcolors path.
- Neither version calls `console_command` or interpolates into a server console command. Do not classify a semicolon in `player.name` as arbitrary server-console execution: the sink here is a client command. X/XP reject backslash/semicolon/quote and their serializer rejects these characters. M/MP only reject backslash; quotes can reach an unescaped userinfo client-command string. This is a validation/serialization concern, but no native command-injection exploit was reproduced and no separate security finding is asserted. Validate serialized userinfo safely in any eventual patch; do not invent a `; quit` server exploit.
- Rankcolors intentionally rewrites name colors (`rankcolors.py`:180–192 and 387–401). It may win or lose the final color depending on hook order when combined with registered custom colors. Choosing which plugin owns colors is a policy decision, not an invented independent names bug. The stale-base resurrection in F3 occurs in both tested orders regardless of that color policy.

## Test evidence and limitations

Reproducer: `/opt/data/cache/scratch/names-review-offline.py` (SHA256 `c7e7e26e891f2f01b0a5ab35553863f2d85a2a6a0be748d5423398ddc5fc01fe`).

Executed successfully (exit 0):

```text
python3 -B /opt/data/cache/scratch/names-review-offline.py
PASS signature checks: all four files; defect/control probes=20
PASS real rankcolors handler / names_first: stale registration resurrected as '^4Old'
PASS real rankcolors handler / rankcolors_first: stale registration resurrected as '^2Old'
PASS existing preset/pool drift test bodies: 2 pairs and empty allowlist; direct execution, not pytest
```

The 20 individual probes exercise the five scenarios/controls on each of the four actual plugin files. They assert the observed broken behavior, not that the code is fixed. Engine Player name/cvars setters and the minqlxtended signature validator are extracted from actual checked-out engine sources and executed. The player backing state, synchronous userinfo diff/merge transport, cvars/settings, decorators/base Plugin, and Redis storage are explicitly offline doubles. Rankcolors real handler/styling code is loaded without constructing the plugin, so no timer, HTTP worker, or live connection runs. This is not a real Redis-client or QLDS integration test.

Relevant existing repository tests inspected:
- `tests/test_minqlxtended_plugin_baseline.py`: manifest integrity/import/dependency-floor checks, not nickname lifecycle behavioral tests.
- `tests/test_builtin_preset_plugin_drift.py`: preset/pool equality; its real test bodies were directly executed with only the pytest parametrization decorator stubbed and passed for both runtime pairs.
- Searches for names/colored_name in the QLSM tests found no existing lifecycle behavioral suite for this plugin. Names in `test_preset_update_names.py` are preset-name behavior, not plugin nickname tests. No rankcolors-specific tests were found in the external rankcolors workspace searched.

The available `python3` is 3.14.7 and has no pytest (`ModuleNotFoundError: No module named 'pytest'`). A pytest suite was not run or claimed; no packages were installed. The standalone offline assertions and direct drift-test execution above are the actual executed evidence. Live reload, native engine tokenization, Steam profile lookup, real Redis latency, and server frame timing were not tested.

## Artifacts / handoff

Created only scratch artifacts:
- `/opt/data/cache/scratch/names-review-offline.py`
- `/opt/data/cache/scratch/names-review-first.md`

No tracked or untracked repository file was changed; final QLSM git status remained empty. No commit, push, PR, deployment, reload, or live server action occurred. Findings are for the separately requested second independent assessment before any fix is accepted.
