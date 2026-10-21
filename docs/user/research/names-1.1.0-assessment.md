# Independent assessment of FIRST review findings F1–F5

## Decision / scope

**Accept F1, F2, F3, F4. Acknowledge F5; do not make session caching a mandatory fix. Four of five findings require action.** Fix those four narrowly, add bounded lifecycle regression tests, and keep the two tracked copies per runtime identical. This assessment does not authorize implementation, a commit, a PR, or deployment.

Loaded both requested installed skills: `assess-review` and the original `minqlx-plugin-review`. Applied the assessment principles directly to the supplied local review; no GitHub review polling or PR mutations were performed because no names PR exists.

Independently read the full actual source of all four tracked plugins:

| Alias | File |
|---|---|
| M | `/workspace/qlsm/ql-assets/data/minqlx-plugins/names.py` |
| MP | `/workspace/qlsm/configs/presets/_builtin/default/scripts/names.py` |
| X | `/workspace/qlsm/ql-assets/data/minqlxtended-plugins/names.py` |
| XP | `/workspace/qlsm/configs/presets/_builtin/default-minqlxtended/scripts/names.py` |

M/MP have identical line numbering and contents; likewise X/XP. Read `/workspace/qlsm/CLAUDE.md`, both engines' actual Player setters and userinfo handlers, their plugin load/reload paths, minqlx's Redis wrapper, the native synchronous client-command paths, minqlxtended's handler-signature validator, and the available external rankcolors userinfo/color application code. Relevant revisions read from git:

- QLSM `fc3c28d3e58bbae9c847da2139f5c8960e3d94fd`.
- minqlx `fbdd915185337791d8e209dc4b686a1ee60d3721`.
- minqlxtended `a3de9471ab5c4c5f712b47923cd6b964312bcefd`.

QLSM status was empty before and after assessment probes. No plugin source or repository file was modified. The unrelated autokick branch/PR was not altered. Only scratch assessment artifacts were created.

## 1. F1 — Global self-write flag can swallow another player's rename

- **Reviewer says:** A same-value assignment raises no userinfo event, leaving a global flag that consumes a later unrelated event (M/MP).
- **Assessment: Accept.**
- **Evidence:** M/MP lines 35–36, 41–47, 53–57, 95–98 implement exactly one global skip bit. The flag is checked even before testing whether `changed` contains `name`. Actual minqlx `_handlers.py:141–158` dispatches userinfo only when a diff exists. `_player.py:175–182` writes userinfo via `client_command`; `python_embed.c:375–386` and `hooks.c:80–88` execute that command synchronously. Thus a same-raw-value assignment does not consume the bit. The rerun reproduced Player A's no-diff load assignment leaving B's subsequent real rename unprocessed: B displays `NewB`, but Redis still has `^3B` and the baseline remains `B`. Both minqlxtended copies passed the corresponding control.
- **Minimal action: Fix M/MP only.** Replace the global bool with per-player self-assignment protection in one small helper called at both load and successful command assignment. Skip exact raw equality using `player.cvars.get("name")`, not `player.name` (the getter adds `^7`). Only ignore the relevant player's name event while this assignment is executing. Since the inspected engine executes synchronously, use a `try/finally` to discard the per-player marker after `player.name = value` returns or raises, as well as normal handler consumption. This avoids a pending token after a blocked/no-event write without inventing queues, workers, or timeouts. Disconnect should discard any marker. Retain baseline semantics; do not fix this by interpreting a server-created alias as a new client baseline.
- **Regression cases:** A no-diff load assignment followed by B's rename; no-diff `!name` assignment; genuine self-write event; intervening non-name userinfo; disconnect/reconnect; bounded transport double that blocks a self-write or raises and verifies no marker leaks. Use X/XP as cross-player controls, not as targets for an unrelated rewrite of their already-correct demonstrated behavior.

The first review's proposed removal of all self-write tracking is not necessary. A narrowly scoped per-player helper is easier to verify while preserving enforcement-off aliases.

## 2. F2 — Accepted base rename does not refresh baseline

- **Reviewer says:** `Old -> New -> !name ^3New -> ^4New` deletes the newly registered name because the comparison baseline stays `Old`.
- **Assessment: Accept.**
- **Evidence:** M/MP lines 59–68 and X/XP lines 69–82 delete the registration on a baseline mismatch but never assign the accepted new baseline on that branch. Commands at M/MP 95–98 and X/XP 114–117 do not repair it. Reproduced on all four actual files: after the sequence, registration is absent, baseline is `Old`, display is `New`. This is deterministic with the stated ordering, not a speculative performance concern.
- **Minimal action: Fix all four.** On a real incoming base-name mismatch, capture the new clean client name and refresh `steam_names[sid]` in the same transition that invalidates the old registration (and X/XP's `registered_names[sid]`). Keep the existing no-registration path updating the baseline. Initialize a genuinely missing baseline safely for reload/command paths (F4), but do not unconditionally replace the baseline with every server-set/command-set name. No new architecture is needed.
- **Critical alias constraint:** With enforcement disabled, the baseline tracks the client's original accepted spelling, while Redis may intentionally contain a different server-set alias. My added probes establish the existing contract in all four files: connect as `Original`, `!name ^3Alias`, then client resends `^4Original`; display and registration remain `Alias`, baseline remains `Original`. Setting `steam_names[sid] = clean_text(registered_alias)` on every successful command would break this contract. In particular, do not apply the first review's broad command-baseline wording as unconditional assignment. Refresh on an actual accepted client rename, not on the plugin's own write. Repeated alias commands must also keep the original baseline.
- **Regression cases:** Original F2 sequence on all four; real rename without a registration; repeated registration; no-name updates do nothing; enforcement-off alias followed by original-client color resend; subsequent genuine client rename clears the alias and updates baseline; command rejection must leave baseline/storage unchanged.

## 3. F3 — Enforcement rejects stale registration at load but later restores it

- **Reviewer says:** Reconnect as `New` with stored `^2Old`; a color update can resurrect `Old` despite enforcement being enabled.
- **Assessment: Accept.**
- **Evidence:** Load eligibility checks at M/MP 41–47 and X/XP 47–54 compare stored and current clean names case-insensitively. Userinfo rewrite paths at M/MP 63–65 and X/XP 76–78 do not validate the stored base. All four rerun scenarios produced `Old` from `New` with enforcement on. The original probe's actual rankcolors handler additionally reproduced the wrong base in both hook orders (`^4Old` / `^2Old`). This is an internal enforcement inconsistency, not a claim of authenticated Steam-persona verification.
- **Minimal action: Fix all four.** Before substituting a registration into `changed["name"]`, apply the same enforcement eligibility rule as load: when enforcement is enabled, its clean base must equal the accepted incoming client clean base under the existing lower-case comparison. If incompatible, do not return the stored name. The least destructive variant can retain the Redis value but treat it as ineligible for that rewrite; X/XP may retain the cached value provided the guard is applied every time. Do not delete historical Redis data merely because load found a mismatch; no deletion is required to close this bug. A tiny shared eligibility predicate within each file is optional, not a demand for refactoring. Existing real-client-base-change invalidation/reset behavior remains governed by F2.
- **Regression cases:** Stored `Old`, reconnect `New`, then color-only `New` stays `New` with enforcement on; no stale base under either rankcolors hook order; matching mixed-case registration remains accepted (e.g. stored `sAmE`, incoming `Same`); enforcement off still restores an intentional `Alias` from the original client spelling; normal registration/reset unaffected.
- **Ownership constraint:** Do not make names claim rankcolors' tier colors, strip tier colors, reorder priorities, or add calls into rankcolors. This fix decides base-name eligibility only. The existing final-color ordering conflict is not an additional accepted bug. Check base and storage invariants in both hook orders rather than imposing identical final raw colors.

A blanket unconditional `clean(stored) == clean(incoming)` guard would incorrectly disable enforcement-off aliases. The enforcement condition must remain explicit.

## 4. F4 — Reload leaves online players without initialized state

- **Reviewer says:** After a reload M/MP can repeatedly raise `KeyError`; X/XP silently ignore persisted registrations.
- **Assessment: Accept.**
- **Evidence:** Both constructors begin with empty maps. Actual loader/reloader source (`minqlx/_core.py:342–407`; `minqlxtended/_core.py:1055–1148`) replaces the plugin instance but does not replay connect/loaded events for already-online clients. M/MP then subscript `steam_names[sid]` at line 63. X/XP use `.get` at line 73 and conflate absent registration cache with a known negative value, never reading Redis on that path. Rerun direct invocation exposes M/MP's missing-SteamID `KeyError`; X/XP keep Redis `^2Same` but accept `^4Same` without hydrating. Minqlx `_handlers.py:160–163` catches/logs the exception and allows the command; it does not repair state.
- **Minimal action: Fix all four with lazy initialization, not an unconditional online-player rewrite.** On the first relevant fresh name event when baseline is missing, establish it from incoming clean name safely (no direct missing-key subscript). M/MP already read Redis per name event, so no new registration cache is necessary. For X/XP only, distinguish `sid not in registered_names` from `registered_names[sid] is None`; perform one `db.get` for the former, store even a negative result, and then run normal eligible-registration logic (including F3). Do not return early in a way that permanently loses registration enforcement. Successful commands must populate/update registration state as today; initialize a missing baseline before their own assignment only when needed. Disconnect clears all session maps.
- **Regression cases:** Construct a fresh instance with an already-online persisted player, without calling connect/loaded, then send fresh `^4Same`: no exception, matching registration honored. Test stale-base registration with enforcement on; intentional alias with enforcement off and fresh original-client input; no registration with repeated events performs just one lazy X/XP read; normal connect then loaded; disconnect/reconnect; non-name input should not cause hydration or mutation; commands immediately after reload.
- **Limit / unavoidable ambiguity:** A reload cannot reconstruct the original client baseline from an already server-recolored/aliased snapshot or recover an earlier Steam persona. Fresh incoming client spelling is a defensible baseline. On that first event, a plugin with no historical baseline cannot distinguish a genuinely new client base from the old original name of an intentional alias. Do not claim to preserve unavailable history. No Steam API call, persistent extra history, global scan, or eager player-name rewrite is warranted. This does not block the bounded reload fix; tests should model fresh client input explicitly.

Using only `.get` to avoid an exception is not enough for X/XP: the distinct not-looked-up state must actually be hydrated.

## 5. F5 — Synchronous Redis reads on each minqlx name update

- **Reviewer says:** Every name update does EXISTS and preserving a registration additionally does GET; recommends session caching with negative entries.
- **Assessment: Acknowledge. No mandatory cache conversion in this correctness PR.**
- **Evidence:** Actual minqlx `database.py:126–134` confirms membership invokes Redis EXISTS and indexing invokes GET. The bounded rerun measured exactly 100 EXISTS + 100 GET operations for 100 callbacks on each minqlx copy, zero hot-hook operations after hydration on X/XP. This proves avoidable synchronous round trips, not actual frame latency, production callback frequency, denial-of-service, or a new regression. No real Redis or server frame measurement was performed. The skill correctly flags hot-hook I/O; that warrants attention, not pretending an unmeasured performance threshold is established.
- **Minimal compatible optional improvement:** If touching this read path anyway, fetch once with `registered = self.db.get(name_key)` for each M/MP name event and branch on absence; use that value instead of EXISTS followed by GET. The wrapper delegates `get` through `__getattr__` to redis-py, and X/XP already use `db.get`. This removes the redundant round trip and the exists/get deletion window without introducing a session cache, timers, refresh commands, asynchronous writes, or new user-facing policy. Preserve the existing meaning of a missing value (do not accidentally broaden to falsey values unless deliberately handling corrupt data). This remains one synchronous GET per relevant event, not a claim to have removed all hot-hook I/O.
- **External Redis trade-off (independently exercised):** After normal hydration, change Redis from `^2Same` to `^3Same`, then send `^4Same`: M/MP immediately use `^3Same`; X/XP continue using cached `^2Same`. Delete the Redis key, then send `^5Same`: M/MP let `^5Same` through; X/XP still apply cached `^2Same`. Porting X/XP's session cache into M/MP therefore removes existing immediate observation of external edits/deletions. Negative caching likewise hides an externally added registration until refresh. A local-only cache can also preserve stale values written by another server sharing the same key namespace. These are actual semantic differences, not just theoretical cache-invalidation rhetoric.
- **User decision needed?** Not for the recommended F1–F4 fixes or the optional one-GET reduction: preserve M/MP's current per-event observation and X/XP's existing session-cache policy. **Yes before adopting session caching in minqlx** unless the user explicitly agrees that external edits become visible only after a specified refresh/reconnect/reload boundary. Do not silently assume commands/reconnect are an acceptable invalidation policy. A TTL or refresh command is not automatically the minimal answer; both add policy/scope and need a deliberate decision. Existing X/XP lazy reload hydration (F4) is a bounded lifecycle correction, not permission to add a new minqlx session cache.
- **Regression cases if optional one-GET is implemented:** 100 registered name callbacks yield 100 GET and zero EXISTS; no-registration callbacks use one GET each; external add, edit, and delete are observed on the next name event; commands/reset still work; F1–F4 remain covered. If the user elects caching later, test the chosen refresh boundary and positive/negative invalidation explicitly and document the changed observation behavior.

Reject the implication that a new cache subsystem or a performance emergency has been established. Acknowledge the concrete I/O count and prefer the compatible small reduction over an unapproved behavior change.

## Execution evidence and probe audit

Executed successfully, exit 0:

```text
python3 -B /opt/data/cache/scratch/names-review-offline.py
PASS signature checks: all four files; defect/control probes=20
PASS real rankcolors handler / names_first: stale registration resurrected as '^4Old'
PASS real rankcolors handler / rankcolors_first: stale registration resurrected as '^2Old'
PASS existing preset/pool drift test bodies: 2 pairs and empty allowlist; direct execution, not pytest

python3 -B /opt/data/cache/scratch/names-assessment-probes.py
PASS independent assessment extensions: 12 scenarios
```

The added assessment probes run three explicitly asserted scenarios per actual file: enforcement-off alias/original-baseline preservation, out-of-band Redis edit/delete observation, and mixed-case registration compatibility. The script loads/reruns the original bounded harness internally with its stdout captured; the original harness was also separately run above with visible results. Counts come from executable assertions/loop counters, not inferred totals.

I read the original reproducer before executing it. It executes real plugin sources, AST-extracted actual engine setters and the minqlxtended signature validator. Its transport, engine/player backing storage, settings/decorators, base Plugin and Redis are doubles. The name getter double returns current backing state rather than reproducing the engine's full per-object snapshot cache. Accordingly these are lifecycle/logic reproductions, not native integration tests; fresh event/command Player snapshots in the real engine remain a test-design consideration. Rankcolors code is instantiated without its constructor/workers/HTTP. The external file does not establish deployed rankcolors revision or minqlxtended-port behavior. The first review's direct drift-test-body execution is not a pytest session. Neither probe proves a fix: they intentionally assert current defects/control behavior.

No native engine, actual Redis connection, live server, Steam endpoint, package installation, commit, push, PR operation, or server reload was performed. No blocker prevented this assessment. Parent implementation will need actual post-patch regression assertions (invert defect expectations), not simply a successful rerun of the defect-confirming script.

## Concrete handoff / user-visible forks

1. **Mandatory:** F1 in M/MP; F2, F3, F4 in all four, with narrow per-player self-write scope, accepted-client-baseline maintenance, enforcement-aware restore eligibility, and safe lazy reload state.
2. **Not mandatory:** F5 session caching. Keep minqlx's external-edit observation. Optional single-GET simplification is compatible but should not become a fifth mandatory finding or a larger refactor.
3. **No user decision blocks mandatory work.** Ask only if opting into new minqlx cache freshness semantics or a new rankcolors-vs-names color-ownership policy. Neither change is required here. Avoid destructive stale-registration cleanup by retaining but refusing ineligible stored values.
4. Preserve public Redis keys, command names/validation contracts, runtime-specific signatures/return APIs, enforcement-off alias behavior and existing rankcolors ownership. No Steam API calls or unrelated autokick changes. Version bump and separate branch/PR logistics belong to the parent's later task, not this read-only assessment.

**Bottom line: 4 of 5 findings need action. Fix F1–F4, verify their regressions and compatibility controls, then proceed with the separately authorized delivery workflow; acknowledge F5 without silently changing cache policy.**
