# Runtime-Confirmed UPDATED Status Reconciliation Findings Assessment

Reviewed:
- `/home/rage/qlsm/docs/plans/2026-08-10-auto-restart-updated-status-design.md`
- `/home/rage/qlsm/docs/plans/2026-08-10-auto-restart-updated-status.md`
- `/home/rage/qlsm/docs/findings/2026-08-10-auto-restart-updated-status-findings.md`

## Assessment

### 1. A new invocation can be paired with the previous invocation's Redis payload
- **Finding says:** The planned probe can observe a new `InvocationID` while the prior process's Redis payload is still within its 15-second TTL, and it does not verify that the unit is active.
- **Assessment:** Accept
- **Edge-case validity:** Realistic. `serverchecker` publishes every 10 seconds with a 15-second expiry, so an isolated restart creates a normal window in which invocation B and invocation A's payload coexist. The same problem exists while a newly active process has not yet loaded `serverchecker`.
- **Pros of fixing:** Enforces the feature's central safety invariant, prevents false `UPDATED -> RUNNING` promotion, and makes inactive, failed, malformed, and stale observations unambiguously ineligible.
- **Cons of fixing:** Expands the observation shape and parser, requires another systemd time/state property or candidate-state persistence, and adds timestamp-boundary or multi-poll tests. A timestamp approach must account for `updated` being integer epoch seconds.
- **Action:** Amend plan
- **Reasoning:** A non-null payload is evidence that some recent invocation was healthy, not that the newly observed invocation is healthy. The design and Tasks 2-3 must bind usable live evidence to the active observed invocation before implementation. Comparing the existing payload `updated` value to a validated service start time is likely smaller than adding persistent candidate state, provided the comparison is conservatively defined.

### 2. The plan does not baseline every producer of `UPDATED`
- **Finding says:** The Workshop update task also writes `UPDATED` without capturing a post-update runtime baseline and changes stopped instances to `UPDATED`, but the plan covers only config saves.
- **Assessment:** Accept
- **Edge-case validity:** Realistic. `ansible_workshop_update.py` is the only other backend producer found, and its normal no-restart path marks every host instance `UPDATED`; it also explicitly marks originally stopped instances `UPDATED` in the guarded restart branch.
- **Pros of fixing:** Prevents an earlier unobserved restart from being credited to later Workshop files, gives all `UPDATED` transitions one coherent invariant, preserves the design's stopped-instance semantics, and avoids pointless 30-second polling for disabled services.
- **Cons of fixing:** Adds the Workshop task and its tests to scope, requires careful batching or reuse of the host probe, and changes an existing user-visible stopped-instance status behavior.
- **Action:** Amend plan
- **Reasoning:** Runtime reconciliation cannot be correct if only one status producer establishes its baseline. The plan should inventory both producers, capture the running instances' post-update identities with their `UPDATED` writes, and retain `STOPPED` for originally stopped instances. This is necessary scope, not an unrelated Workshop refactor.

### 3. Refresh-then-commit is still a time-of-check/time-of-use race
- **Finding says:** A task can change status or baseline after `refresh()` but before the poller's commit, allowing reconciliation to overwrite task-owned state.
- **Assessment:** Accept
- **Edge-case validity:** Realistic. The status poller and RQ workers are separate processes, and refresh provides no write precondition. The window is small but occurs precisely when an external restart and a user task overlap. Baseline-only writes also need guarding because a stale observation could replace a baseline captured by a just-completed save.
- **Pros of fixing:** Makes the stated ownership rule enforceable at the database, prevents transitional-status clobbering and stale-baseline corruption, and makes log creation accurately reflect a successful promotion.
- **Cons of fixing:** Replaces simple ORM mutation with conditional updates, makes host-level counting/logging slightly more involved, and requires deterministic concurrency tests.
- **Action:** Amend plan
- **Reasoning:** Re-reading before mutation reduces stale data but does not provide concurrency safety. Tasks 3-4 should use compare-and-set updates guarded by instance ID, eligible status, and expected baseline, with the log appended only when the guarded promotion succeeds. This correctness issue should block the current implementation sketch.

### 4. One slow per-port probe can still discard every observation for the host
- **Finding says:** Sequential five-second `systemctl` calls and unbounded Redis operations run behind a ten-second outer SSH timeout, so a few slow instances can erase otherwise valid host observations.
- **Assessment:** Accept
- **Edge-case validity:** Realistic under a degraded target. Local `systemctl show` is normally fast, but two timeouts exceed the outer deadline by construction, Redis clients have no planned connect/read timeout, and the remote script emits output only after the loop completes.
- **Pros of fixing:** Preserves per-instance fault isolation, bounds poll-cycle duration, prevents one degraded service or Redis DB from hiding healthy siblings, and makes timeout behavior testable.
- **Cons of fixing:** Requires a more deliberate remote probe design and timeout budget. A single multi-unit systemd query needs robust unit-to-result parsing; concurrency adds more remote-script complexity.
- **Action:** Amend plan
- **Reasoning:** The current timeouts contradict the design's explicit failure-isolation promise. Task 2 should specify one bounded multi-unit systemd query or bounded concurrent per-unit work, explicit Redis connect/read timeouts, and an outer deadline derived from that design. This should be settled before tests lock in the current sequential structure.

### 5. An unexpected baseline-probe exception turns a successful save into `ERROR`
- **Finding says:** The optional post-save identity probe is inside the config task's broad failure handler, so an exception can convert a successful Ansible sync into task failure instead of safe `UPDATED` fallback.
- **Assessment:** Accept
- **Edge-case validity:** Realistic enough to defend at this boundary. Ordinary SSH failures should be normalized by the helper, but validation, command construction, missing observation, OS, or regression errors can still escape unless the contract and caller both contain them.
- **Pros of fixing:** Preserves successful configuration saves, exactly implements the design's failure fallback, clears a potentially unsafe old baseline, and costs only a narrow exception boundary plus one test.
- **Cons of fixing:** Duplicates some protection expected in the probe helper and can conceal probe defects unless it emits a clear warning with exception context.
- **Action:** Amend plan
- **Reasoning:** This is justified defensive handling because runtime identity capture is explicitly optional and must never own the config-save outcome. Task 4 should guard the call, set the baseline to `NULL`, warn, and continue as `UPDATED`; the probe seam should also normalize its own expected failures.

### 6. The end-to-end UI timing is longer than the stated 30 seconds
- **Finding says:** Independent 15-second backend and 30-second frontend intervals yield roughly 45 seconds worst-case from restart to an open page update, not the plan's stated 30 seconds.
- **Assessment:** Acknowledge
- **Edge-case validity:** Realistic and deterministic worst-case timing, though it affects acceptance wording rather than reconciliation correctness.
- **Pros of fixing:** Gives users and tests an honest latency expectation and avoids treating a deliberate slow polling policy as a defect.
- **Cons of fixing:** Reducing either interval increases ongoing polling or couples independent loops merely to satisfy wording; that cost is not justified by any stated requirement for 30 seconds end to end.
- **Action:** Amend plan
- **Reasoning:** Keep the proposed intervals. Amend the acceptance scenario to say the page refreshes within 30 seconds after database reconciliation and document an approximately 45-second end-to-end worst case plus request/probe time. This does not otherwise block the implementation architecture.

## Bottom Line

6 of 6 findings need action before implementation. Amend the design and plan for invocation-bound live evidence, all `UPDATED` producers, guarded database writes, bounded multi-instance probing, and exception-safe baseline capture; also correct the UI latency acceptance wording. The first five are implementation-safety requirements, while the sixth is a low-cost specification clarification rather than a reason to shorten the intervals.
