# Docker-Safe Backup Import Review Findings

Reviewed:
- `docs/plans/2026-08-07-backup-import-cross-filesystem-design.md`
- `docs/plans/2026-08-07-backup-import-cross-filesystem.md`

## Critical

### A failure inside `_swap_tree` can strand or delete the current data

`restore_backup_archive` adds a tree to `swapped` only after `_swap_tree` returns. If any rename fails after an earlier child has already been moved to its rollback path, the caller has no record of that partially swapped tree. The outer rollback therefore skips it, while `finally` removes the staged directory. This can leave live children missing and their only copies hidden under `.qlsm-restore-old-*`, directly contradicting the promised rollback guarantee. The planned `EXDEV` tests fail on the first old rename and do not exercise a later, partial-swap failure.

Required fix: Add an implementation step that makes `_swap_tree` exception-safe, either by recording the tree before its first mutation and updating shared rollback state after every successful rename, or by rolling back its own partial work before re-raising. Add fault-injection tests for failures after at least one current child has been displaced and after at least one staged child has been installed.

### Backup requests are not serialized, so one restore can move another restore's staging directory

The route's `any_lock_held()` call is only a point-in-time check for host/instance task locks; it neither acquires a restore lock nor prevents a second import or export from starting. Under the proposed layout, restore A's staging directory is a direct child of each managed root. Restore B excludes only its own staging basename, so it can treat A's staging directory as current user data and rename it away while A is extracting or swapping. Two imports, or a background operation beginning immediately after the check, can consequently corrupt the restore and its rollback state.

Required fix: Add a plan/spec step for an atomic, restore-wide maintenance lock that serializes import/export and prevents task-lock acquisition for the entire snapshot/extract/swap/database/cleanup window. Do not rely on `any_lock_held()` as the lock. Add a route-level contention test and a restore test proving foreign active staging paths cannot be consumed.

## Important

### The stated preflight validation order is not implemented by the plan

The design says the archive is fully validated before filesystem work. The existing parser validates ZIP integrity and parses the two JSON files, but unsafe member paths are detected only during `_extract_tree`, after the safety snapshot and managed roots/staging directories have been created. Database envelope and row validation occurs even later in `replace_database`, after file trees have been swapped. Task 2 does not add a preflight pass, so the plan cannot deliver Restore Flow step 1 as written.

Required fix: Either add a non-mutating preflight step that validates every archive member path and all database data needed by `replace_database` before `_write_safety_snapshot`, or narrow the design guarantee to say that extraction and applicable validation finish before destructive swaps. Add assertions for what a rejected unsafe or malformed archive is allowed to leave on disk.

### Post-commit cleanup can report failure after the restore has already succeeded

Rollback-path deletion occurs after the database commit and outside the guarded `try`. An `os.remove` or directory cleanup error will make the API return HTTP 500 even though the new database and files are already committed. With rollback paths moved inside managed roots, a leftover contains displaced user data inside a tree that later backup exports walk, so obsolete keys/configs can be silently included in a future archive. Staging cleanup also uses `ignore_errors=True`, despite the design's unconditional statement that no temporary paths remain.

Required fix: Define cleanup semantics in the spec and plan. Treat post-commit cleanup as best-effort and logged without misreporting the committed restore, reserve/exclude restore-temporary names from backup export, and specify how stale paths are detected and safely recovered or removed. Add cleanup-failure coverage rather than asserting only the normal cleanup path.

## Minor

### The focused-suite expected count is stale

The two named files currently collect 21 tests. Task 1 adds one new test and only modifies an existing rollback test, so Task 2 should produce 22 tests, not the stated 23. A hard-coded count will create a false plan failure.

Suggested fix: Change the expectation to "all collected tests pass" or update the count after the final test list is settled.

### One simulated mount does not verify the per-tree invariant

The boundary guard models only `terraform/ssh-keys`. It proves the reported production failure is fixed, but it does not verify the design's broader claim that every rename for all six managed trees stays within that tree, especially the nested `configs` and `configs/presets` roots.

Suggested fix: Record rename endpoints and assert each swap/rollback rename stays within its corresponding managed root, or parameterize the boundary test across representative flat and nested roots.

## Open Questions

- Does "interruption safety" cover only caught Python exceptions, or also worker/container termination between child renames? The per-child rename design has no journal or startup recovery for rollback paths left by process death.
- Are `.qlsm-restore-*` names a reserved internal namespace that backup export and restore should always exclude? The design currently reserves only the active staging basename.

## Tests To Add

- Inject a rename failure after the first existing child is moved; assert every original child is restored and no staging or rollback path remains.
- Inject a rename failure after the first staged child is installed; assert archive-only children are removed and displaced originals are restored.
- Start a second import while one import holds the restore-wide lock; assert the second request receives a conflict response without touching disk.
- Attempt export/background task-lock acquisition during restore; assert it is blocked for the entire destructive window.
- Reject an unsafe archive member and malformed database payload while asserting the exact preflight no-mutation guarantee chosen by the spec.
- Simulate rollback-path and staging cleanup failures; assert committed restore response semantics, logging, and exclusion of stale temporary data from future exports.
- Exercise a nested `configs/presets` boundary and verify `_builtin` remains untouched through both success and rollback.
