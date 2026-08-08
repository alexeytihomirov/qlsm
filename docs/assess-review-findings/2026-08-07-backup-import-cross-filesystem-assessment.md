# Docker-Safe Backup Import Findings Assessment

Reviewed:
- `docs/plans/2026-08-07-backup-import-cross-filesystem-design.md`
- `docs/plans/2026-08-07-backup-import-cross-filesystem.md`
- `docs/findings/2026-08-07-backup-import-cross-filesystem-findings.md`

## Assessment

### 1. A failure inside `_swap_tree` can strand or delete the current data
- **Finding says:** A rename failure after `_swap_tree` has begun mutating a tree leaves the caller without enough bookkeeping to roll that partial swap back.
- **Assessment:** Accept
- **Edge-case validity:** Realistic. Rename can fail for permissions, I/O, a disappearing path, or fault injection after one or more earlier renames have succeeded; the caller currently records the tree only after `_swap_tree` returns.
- **Pros of fixing:** Preserves the restore's core all-old-or-all-new guarantee, prevents stranded user data, and makes later rollback behavior testable rather than assumed.
- **Cons of fixing:** Adds careful local rollback/bookkeeping logic, and rollback failures must not obscure the original exception. The proposed two fault-injection tests add modest complexity.
- **Action:** Fix before implementation
- **Reasoning:** This is a direct data-loss risk in the exact swap path being changed. Making `_swap_tree` exception-safe is focused work, not speculative hardening, and the plan should explicitly cover failures during both displacement and staged installation.

### 2. Backup requests are not serialized, so one restore can move another restore's staging directory
- **Finding says:** `any_lock_held()` is a non-atomic observation, so concurrent imports, exports, or newly starting background tasks can overlap a restore and corrupt its in-root staging or managed data.
- **Assessment:** Accept
- **Edge-case validity:** Realistic. Production runs one Gunicorn worker with multiple threads, so two authenticated requests can execute concurrently. The proposed staging paths are direct managed-root children and only the current restore's staging basename would be excluded.
- **Pros of fixing:** Prevents concurrent destructive restores, keeps exports consistent, and closes the existing check-then-act race with entity task locks.
- **Cons of fixing:** An atomic maintenance-lock protocol is cross-cutting: task-lock acquisition must honor it, ownership and release need defined semantics, and a bounded TTL/recovery policy is required. This is appreciably larger than the filesystem-only patch.
- **Action:** Amend plan
- **Reasoning:** The scope cost is justified because the proposed layout makes foreign active staging paths directly consumable and overlapping restores can lose data. Keep the solution narrow: one Redis-backed maintenance lock coordinated atomically with task-lock acquisition, route contention coverage, and reserved restore-temporary names. A broader lock framework is unnecessary.

### 3. The stated preflight validation order is not implemented by the plan
- **Finding says:** The design promises full validation before filesystem work, while unsafe paths are checked during extraction and detailed database validation happens only after file swaps.
- **Assessment:** Accept
- **Edge-case validity:** Realistic. Backups are user-supplied, and the current code can create a safety snapshot and staging directories before rejecting an unsafe member, or begin the reversible swap before rejecting malformed database rows.
- **Pros of fixing:** Aligns the source-of-truth documents with observable behavior and gives tests a precise no-mutation boundary for rejected input.
- **Cons of fixing:** A complete duplicate database validator would add maintenance burden and could drift from `replace_database`; validating every row by performing a second ORM import would also add needless complexity.
- **Action:** Amend plan
- **Reasoning:** Narrow the guarantee instead of building a second import engine: parse and integrity-check the archive first, complete extraction and path validation before destructive swaps, and rely on transaction plus filesystem rollback for detailed database-import failures. Tests should distinguish harmless safety-snapshot/staging artifacts from mutation of managed data.

### 4. Post-commit cleanup can report failure after the restore has already succeeded
- **Finding says:** Cleanup after the database commit can raise a 500 despite a committed restore, while silently retained in-root temporary paths may be captured by a later export.
- **Assessment:** Accept
- **Edge-case validity:** Realistic. Permission and I/O cleanup failures are uncommon but possible, and `walk_tree()` currently has no general exclusion for `.qlsm-restore-*` children.
- **Pros of fixing:** Makes the API response reflect committed state, prevents displaced secrets and obsolete configuration from leaking into later backups, and defines honest cleanup guarantees.
- **Cons of fixing:** Automatic stale-path recovery is risky because the application must distinguish abandoned paths from an active restore; a full startup recovery mechanism would materially expand scope.
- **Action:** Amend plan
- **Reasoning:** Handle post-commit cleanup as best-effort with explicit logging, reserve and exclude restore-temporary names from restore scans and exports, and add cleanup-failure tests now. Automatic discovery or recovery of abandoned paths can remain a separate follow-up; it is not required to fix the response and export correctness bugs.

### 5. The focused-suite expected count is stale
- **Finding says:** The two focused test files collect 21 tests today, so adding one test yields 22 rather than the planned 23.
- **Assessment:** Accept
- **Edge-case validity:** Realistic and confirmed by test collection; the hard-coded expectation would be false after the planned single addition.
- **Pros of fixing:** Avoids a false execution failure and keeps the plan resilient if test collection changes during implementation.
- **Cons of fixing:** None beyond a one-line documentation edit.
- **Action:** Amend plan
- **Reasoning:** Replace the count with “all collected tests pass.” This is non-blocking housekeeping, but it is cheaper and clearer to correct while the plan is being revised.

### 6. One simulated mount does not verify the per-tree invariant
- **Finding says:** Guarding only `terraform/ssh-keys` does not directly prove same-filesystem renames for all six managed trees, particularly nested `configs/presets`.
- **Assessment:** Acknowledge
- **Edge-case validity:** Already covered sufficiently for this fix. The SSH-key guard reproduces the reported Docker boundary through the same generic tree-swap path used by every entry, while existing tests exercise nested preset exclusion on success and rollback.
- **Pros of fixing:** Parameterized or endpoint-recording coverage would make the architectural invariant more explicit and could catch a future tree-specific special case.
- **Cons of fixing:** Repeating the same synthetic boundary across every declarative tree adds test volume without exercising materially different implementation logic; a comprehensive rename recorder may also couple tests tightly to internal sequencing.
- **Action:** Optional follow-up
- **Reasoning:** Representative boundary coverage plus the existing nested-tree behavior tests are proportionate to this bug. Add a nested boundary case only if implementation introduces tree-specific branching; it should not block the focused fix.

## Bottom Line

5 of 6 findings need action before implementation. Revise the design and plan for exception-safe partial swaps, atomic backup/task serialization, a precise validation boundary, and post-commit cleanup semantics; also remove the stale test count. The broader all-tree boundary-test expansion is optional.
