# Docker-Safe Backup Import Design

## Problem

Global backup import creates one staging directory under `/app` and uses
`os.rename()` to replace every managed file tree. Production Docker deployments
bind-mount SSH keys, Terraform state, inventory, and configs separately from
`/app`. Linux rejects a rename across those filesystem boundaries with `EXDEV`,
so a valid backup cannot be restored.

The existing unit tests put the application root and every managed tree on one
temporary filesystem, so they do not reproduce the Docker layout.

## Chosen Approach

Each managed tree will own its temporary restore state. The importer will create
a hidden staging directory inside the target root, extract that tree there, and
reserve hidden rollback paths inside the same root. All renames for that tree
therefore remain on one filesystem and retain the existing atomic replacement
and rollback guarantees.

`_swap_tree` will record each successful displacement and staged installation as
it happens. If a later rename in that same tree fails, it will remove installed
archive children and restore displaced children in reverse order before
re-raising the original exception. The outer restore continues to roll back
trees whose swaps completed earlier.

The `.qlsm-restore-*` prefix is a reserved internal namespace. Restore scans and
backup exports will exclude every direct child with that prefix, not only the
current restore's staging directory. Existing exclusions still apply, including
`configs/presets` while the outer `configs` tree is restored and the shipped
`_builtin` preset directory while custom presets are restored.

Import and export will run under one Redis-backed backup maintenance lock. Its
atomic acquisition succeeds only when no maintenance or entity task lock is
held, and entity task-lock acquisition atomically refuses while maintenance is
active. The lock carries an owner token, has a bounded TTL renewed by an
owner-checked keepalive for the duration of the request, and is released by its
owner in `finally`. This serializes backup requests and prevents a new host or
instance task from entering during snapshot, extraction, swap, database, or
cleanup work; an expired TTL recovers the lock after a terminated worker.

## Restore Flow

1. Acquire the backup maintenance lock for the request.
2. Decrypt the archive, verify ZIP integrity, validate its manifest, and parse
   its JSON database envelope before filesystem work.
3. Write the existing best-effort pre-restore safety snapshot.
4. Ensure every managed root exists and create one hidden staging directory
   inside each root.
5. Extract every archive tree into its corresponding staging directory,
   validating member paths, before replacing any managed child.
6. For each tree, move existing children to hidden rollback paths inside that
   same root, then move staged children into place. A partially failed tree
   unwinds its own successful renames before the failure escapes.
7. Validate the database rows through the existing importer, replace the
   database, and commit. Detailed database-validation failures use the database
   transaction and filesystem rollback rather than a duplicate preflight
   importer.
8. On failure, roll back database state and restore completed file-tree swaps in
   reverse order.
9. Remove staging and rollback paths, then release the maintenance lock.

Rejected unsafe member paths may create a safety snapshot and temporary staging
roots, which are cleaned in `finally`, but cannot mutate managed children.
Syntactically invalid database JSON rejected during parsing has the same no-
managed-data-mutation guarantee. Detailed database-row failures can occur after
the reversible file swap and must restore all original managed data.

## Error Handling and Compatibility

The API contract and archive format remain unchanged. Expected archive and
password errors continue to return HTTP 400, while unexpected restore failures
remain logged and return HTTP 500. Existing backups remain compatible across
Linux distributions and both Docker and non-Docker deployments.

Cleanup before the commit remains part of failure handling. After the database
commit, removal of rollback or staging paths is best-effort: each failure is
logged with its exact path and does not turn a committed restore into an HTTP
500. Retained `.qlsm-restore-*` paths remain excluded from later restore scans
and exports so displaced secrets or obsolete configuration cannot leak into a
backup or be consumed by another restore. Normal successful and rolled-back
operations are still expected to leave no temporary paths.

No cross-filesystem copy fallback will be added because it would weaken the
atomicity and interruption safety promised by the restore workflow.

## Tests

Regression tests will wrap the real rename operation with a filesystem-boundary
guard that raises `EXDEV` whenever a rename crosses into or out of the simulated
SSH-key bind mount. The tests will demonstrate that:

- the old implementation fails under the simulated Docker boundary;
- a successful restore completes while keeping every rename within the tree;
- a database failure rolls restored files back across the same boundary;
- failures after a current child is displaced and after a staged child is
  installed locally unwind the partial tree;
- unsafe paths cannot mutate managed children, while detailed database failures
  restore them through rollback;
- concurrent backup requests and entity-task lock acquisition receive HTTP 409
  while the conflicting lock is held;
- cleanup failure after commit is logged, returns success, and cannot expose a
  retained restore path through a later export; and
- no hidden staging or rollback paths remain after normal success or rollback.

The focused backup test suite and full backend suite will run before the PR is
opened.

## Release

This bug fix ships as v1.25.1. `VERSION`, `docs/user/version.json`, and
`docs/user/releases.md` will be updated together. The release note will use the
approved “Bug fixes and improvements” wording.

---
**Review loop closed:** 2026-08-07
- Findings: `docs/findings/2026-08-07-backup-import-cross-filesystem-findings.md`
- Assessment: `docs/assess-review-findings/2026-08-07-backup-import-cross-filesystem-assessment.md`
- Accepted findings folded in: 1. A failure inside `_swap_tree` can strand or delete the current data, 2. Backup requests are not serialized, so one restore can move another restore's staging directory, 3. The stated preflight validation order is not implemented by the plan, 4. Post-commit cleanup can report failure after the restore has already succeeded, 5. The focused-suite expected count is stale
- Deferred: 6. One simulated mount does not verify the per-tree invariant, automatic stale-path recovery from finding 4
