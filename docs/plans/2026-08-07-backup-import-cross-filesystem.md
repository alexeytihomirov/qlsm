# Docker-Safe Backup Import Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore valid global backups in Docker deployments whose managed data directories are separate bind-mounted filesystems.

**Architecture:** Replace the single `/app` staging root with one hidden staging directory per managed tree, located inside that tree. Preserve displaced children in hidden paths inside the same root so staging, replacement, rollback, and cleanup continue to use atomic same-filesystem renames. Make each tree swap locally exception-safe, reserve restore-temporary names from scans and exports, and serialize backup maintenance with entity task locks through Redis.

**Tech Stack:** Python 3, Flask/SQLAlchemy, pytest, POSIX filesystem operations, Docker bind mounts

---

### Task 1: Reproduce the filesystem boundary and partial-swap failures

**Files:**
- Modify: `tests/test_backup_import.py`
- Create: `tests/test_backup_import_swap.py`
- Create: `tests/test_backup_import_validation.py`

**Step 1: Add a rename boundary guard**

Import `errno` and add a test helper that wraps the real `os.rename`. Treat
`terraform/ssh-keys` as a separate simulated mount and raise `OSError(EXDEV)`
when exactly one side of a rename is inside that tree:

```python
def _reject_crossing_ssh_mount(monkeypatch, app_root):
    mount_root = os.path.realpath(app_root / 'terraform' / 'ssh-keys')
    real_rename = os.rename

    def guarded_rename(source, target):
        source_path = os.path.realpath(source)
        target_path = os.path.realpath(target)
        source_inside = os.path.commonpath((mount_root, source_path)) == mount_root
        target_inside = os.path.commonpath((mount_root, target_path)) == mount_root
        if source_inside != target_inside:
            raise OSError(errno.EXDEV, 'Invalid cross-device link', source, target)
        return real_rename(source, target)

    monkeypatch.setattr('ui.task_logic.backup_import.os.rename', guarded_rename)
```

**Step 2: Add a successful-import regression test**

Build a backup containing the fixture SSH key, add an extra destination key,
enable the boundary guard, and restore. Assert the archived key is restored, the
extra key is removed, and no `.qlsm-restore-*` child remains in the SSH-key root.

**Step 3: Strengthen rollback coverage**

Enable the same boundary guard in
`test_rollback_on_db_failure_restores_old_file_trees`. Retain the existing
database failure and survival assertion, then assert no restore temporary path
remains in the SSH-key root.

**Step 4: Add partial-swap fault-injection tests**

In `tests/test_backup_import_swap.py`, add two `_swap_tree` regression tests
that wrap the real rename and raise a sentinel `OSError` only after earlier
qualifying renames have succeeded:

- `test_partial_swap_restores_children_when_displacement_fails` fails while
  moving the second current child. Assert both original children and contents
  are restored and no `.qlsm-restore-*` path remains.
- `test_partial_swap_restores_children_when_staged_install_fails` allows current
  children to be displaced and one staged child to be installed, then fails the
  next staged install. Assert the installed archive child is removed, every
  original is restored, and no rollback path remains.

The injected primary exception must be the exception observed by the test; a
cleanup attempt must not replace it.

**Step 5: Make the validation boundary explicit in tests**

Strengthen `test_path_traversal_entry_raises_and_touches_nothing` to snapshot
the managed-tree contents before restore and assert they are unchanged. A
best-effort safety snapshot is permitted, but per-tree staging directories must
be gone after `finally`. In `tests/test_backup_import_validation.py`, add a
syntactically invalid `db_export.json` test that asserts no safety snapshot,
staging root, or managed-data mutation occurs. Add a separate malformed
database-row test that reaches `replace_database`, then assert the database
transaction and every completed file swap are rolled back to their original
contents. Keep reusable setup local to the new focused modules so
`tests/test_backup_import.py` remains below the repository's 300-line limit.

**Step 6: Run the regression tests and verify RED**

Run:

```bash
/home/rage/qlsm/.venv/bin/pytest \
  tests/test_backup_import.py::TestRestoreBackupArchive::test_restores_across_managed_tree_filesystem_boundary \
  tests/test_backup_import.py::TestRestoreBackupArchive::test_rollback_on_db_failure_restores_old_file_trees \
  tests/test_backup_import_swap.py::test_partial_swap_restores_children_when_displacement_fails \
  tests/test_backup_import_swap.py::test_partial_swap_restores_children_when_staged_install_fails -v
```

Expected: the boundary tests fail with `OSError: [Errno 18] Invalid cross-device
link`, and the partial-swap tests fail their restoration assertions, proving the
production and data-loss paths before implementation.

### Task 2: Keep restore operations on each target filesystem

**Files:**
- Modify: `ui/task_logic/backup_import.py`
- Modify: `ui/task_logic/backup_files.py`
- Test: `tests/test_backup_import.py`
- Test: `tests/test_backup_import_swap.py`
- Test: `tests/test_backup_import_validation.py`
- Test: `tests/test_backup_export.py`

**Step 1: Reserve restore names and keep them out of scans and exports**

Add one shared direct-child predicate for the `.qlsm-restore-*` namespace in
`backup_files.py`. Compose it with each tree's existing `skip` callback in
`walk_tree`, and use the same predicate for current and staged children in
`_swap_tree`. Add an export test proving files under a retained
`.qlsm-restore-old-*` directory are absent from the ZIP, plus a restore test
proving a foreign `.qlsm-restore-staging-*` child is left untouched and is never
reported as swapped data.

**Step 2: Reserve rollback paths inside the managed root**

Change `_reserve_temp_path` to accept the managed `root` and create its hidden
placeholder there. In `_swap_tree`, call it with `root`, not the root's parent.

**Step 3: Make `_swap_tree` locally exception-safe**

Track displaced `(name, rollback_path)` entries and installed staged names
immediately after each successful rename. If any later rename fails, remove
installed targets in reverse order and rename displaced originals back in
reverse order before re-raising the saved primary exception. Attempt every local
rollback operation even if one fails, logging secondary rollback failures so
they never obscure the primary error. Return the complete rollback entries only
after the whole tree swap succeeds, so the outer restore owns only completed
tree swaps.

**Step 4: Create and fill one staging directory per managed root**

In `restore_backup_archive`, remove the shared `staging_root`. Before extraction,
ensure each root exists, create a `.qlsm-restore-staging-*` directory with
`dir=root`, record it in `staged_dirs`, then extract that archive prefix into it.
Finish extraction and unsafe-member validation for every tree before the first
call to `_swap_tree`. Do not add a duplicate database-row validator:
`replace_database` remains the single detailed validator, protected by its
transaction and the file rollback path.

**Step 5: Make cleanup reflect commit state**

In `finally`, iterate over `staged_dirs.values()` and remove each directory with
one best-effort helper that logs the exact path and exception. After a successful
database commit, remove every rollback path with that helper and never propagate
a cleanup-only failure. Before commit, preserve the primary failure, roll back
the database and completed trees, and log secondary rollback or cleanup errors.
Normal success and rollback must remove all temporary paths; an injected
post-commit cleanup failure must still return the successful restore summary.

Add cleanup-failure coverage that retains one rollback path, verifies the
committed database and files remain restored, asserts the failure is logged, and
builds a later export to prove the retained path and its displaced content are
excluded.

**Step 6: Run the regression tests and verify GREEN**

Run the command from Task 1. Expected: all named tests pass.

**Step 7: Run all backup import and export tests**

Run:

```bash
/home/rage/qlsm/.venv/bin/pytest \
  tests/test_backup_import.py tests/test_backup_import_swap.py \
  tests/test_backup_import_validation.py tests/test_backup_export.py \
  tests/test_backup_files.py -q
```

Expected: all collected tests pass with no failures.

**Step 8: Commit the tested filesystem fix**

```bash
git add ui/task_logic/backup_import.py ui/task_logic/backup_files.py \
  tests/test_backup_import.py tests/test_backup_import_swap.py \
  tests/test_backup_import_validation.py tests/test_backup_export.py
git commit -m "fix: restore backups across Docker mounts"
```

### Task 3: Serialize backup maintenance with entity tasks

**Files:**
- Modify: `ui/task_lock.py`
- Modify: `ui/routes/backup_routes.py`
- Test: `tests/test_task_lock.py`
- Test: `tests/test_backup_routes.py`

**Step 1: Add atomic-contention tests and verify RED**

In `tests/test_task_lock.py`, cover these Redis-level outcomes:

- maintenance acquisition fails when `maintenance_lock:backup` or any
  `task_lock:*` key exists;
- entity `acquire_lock` fails while `maintenance_lock:backup` exists;
- maintenance acquisition and an entity acquisition cannot both win regardless
  of which atomic script runs first;
- only the owner token can refresh or release maintenance; and
- expiry is set on acquisition and restored on every owner refresh.

Update the existing `acquire_lock` call assertions for its Lua-backed atomic
operation. Run `tests/test_task_lock.py` and confirm the new tests fail because
the maintenance protocol does not exist yet.

**Step 2: Coordinate both lock directions atomically**

Add `maintenance_lock:backup` and owner-token helpers in `ui/task_lock.py`.
Acquire maintenance with one Redis Lua script that refuses when the maintenance
key or any `task_lock:*` key exists and otherwise sets the owner token with a
300-second TTL. Change `acquire_lock` to one Lua script that checks the
maintenance key and performs its existing `SET NX EX` in the same atomic Redis
operation. Keep `acquire_locks` routed through `acquire_lock`; once its first
entity lock succeeds, maintenance acquisition must see it and fail.

Use owner-checked Lua scripts for refresh and release. Wrap an acquired
maintenance lock in a context manager that captures the Redis client, refreshes
the TTL every 60 seconds on a daemon keepalive, stops and joins that keepalive in
`finally`, and releases only its own token. The bounded TTL is the recovery path
if a request worker terminates without running `finally`.

**Step 3: Hold maintenance across complete import and export operations**

In `backup_routes.py`, validate the request shape first, create a UUID owner
token, and enter the maintenance-lock context immediately before
`build_backup_archive` or `restore_backup_archive`. Keep the context active until
the builder or restorer has returned or raised, so safety snapshot, extraction,
swap, database commit/rollback, and cleanup are all covered. Replace the
point-in-time `any_lock_held()` route check. If acquisition loses contention,
return the existing locked HTTP 409 response without calling either operation.

**Step 4: Add route-level contention tests**

Update route mocks to the maintenance-lock API. Test a second import and an
export while maintenance is already held; both must return 409, and their
restore/build functions must not be called. Retain coverage that an existing
entity lock blocks backup acquisition, and assert both successful and failing
backup operations release their owner lock.

Together with the task-lock test from Step 1, this proves that a background task
cannot acquire its entity lock during a restore. The foreign staging-path test
from Task 2 proves defense in depth if a stale or externally created restore
path is present.

**Step 5: Run lock and backup route tests**

Run:

```bash
/home/rage/qlsm/.venv/bin/pytest tests/test_task_lock.py tests/test_backup_routes.py -q
```

Expected: all collected tests pass with no failures.

**Step 6: Commit the maintenance lock**

```bash
git add ui/task_lock.py ui/routes/backup_routes.py \
  tests/test_task_lock.py tests/test_backup_routes.py
git commit -m "fix: serialize backup maintenance operations"
```

### Task 4: Publish v1.25.1 release metadata

**Files:**
- Modify: `VERSION`
- Modify: `docs/user/version.json`
- Modify: `docs/user/releases.md`

**Step 1: Bump both machine-readable versions**

Set `VERSION` and `docs/user/version.json` to `1.25.1`.

**Step 2: Add the release-note row**

Add this row above v1.25.0, after confirming PR #170 is still the next PR:

```markdown
| `v1.25.1` | 2026-08-07 | [#170](https://github.com/dngrtech/qlsm/pull/170) | Bug fixes and improvements. |
```

**Step 3: Verify the version files agree**

Run:

```bash
/home/rage/qlsm/.venv/bin/python - <<'PY'
import json
from pathlib import Path

version = Path('VERSION').read_text().strip()
published = json.loads(Path('docs/user/version.json').read_text())['latest']
release_notes = Path('docs/user/releases.md').read_text()
assert version == published == '1.25.1'
assert '| `v1.25.1` |' in release_notes
print(version)
PY
```

Expected: `1.25.1`.

**Step 4: Commit the release metadata**

```bash
git add VERSION docs/user/version.json docs/user/releases.md
git commit -m "chore: bump version to 1.25.1"
```

### Task 5: Verify and publish the pull request

**Files:**
- Review all branch changes against `main`

**Step 1: Run the complete backend suite**

Run:

```bash
/home/rage/qlsm/.venv/bin/pytest tests/ -q
```

Expected: all tests pass with no failures.

**Step 2: Run repository hygiene checks**

Run:

```bash
git diff main...HEAD --check
git status --short
```

Expected: no whitespace errors and only intentional files are present.

**Step 3: Request code review**

Use the required requesting-code-review skill. Address only findings assessed as
valid and in scope, then repeat the focused and full verification commands.

**Step 4: Push and create the PR**

Push `bug/backup-import-cross-filesystem` and open a PR to `main` titled
`Fix backup import across Docker mounts`. Include the production root cause,
atomic per-tree staging approach, v1.25.1 release bump, and test evidence.

**Step 5: Stop before merge**

Report the PR URL to the user. Do not enable auto-merge and do not merge without
the user's explicit approval.

## Deferred follow-ups

- Finding 6, expanding the simulated filesystem boundary to every managed tree,
  is deferred because the representative SSH boundary exercises the shared swap
  path and existing tests already cover the nested preset exclusions. Revisit it
  only if tree-specific swap behavior is introduced.
- Automatic startup discovery or recovery of abandoned `.qlsm-restore-*` paths
  is deferred because safely distinguishing an abandoned path from an active
  restore requires a journal or equivalent ownership metadata. This change logs
  cleanup failures and excludes retained paths from restore scans and exports.

---
**Review loop closed:** 2026-08-07
- Findings: `docs/findings/2026-08-07-backup-import-cross-filesystem-findings.md`
- Assessment: `docs/assess-review-findings/2026-08-07-backup-import-cross-filesystem-assessment.md`
- Accepted findings folded in: 1. A failure inside `_swap_tree` can strand or delete the current data, 2. Backup requests are not serialized, so one restore can move another restore's staging directory, 3. The stated preflight validation order is not implemented by the plan, 4. Post-commit cleanup can report failure after the restore has already succeeded, 5. The focused-suite expected count is stale
- Deferred: 6. One simulated mount does not verify the per-tree invariant, automatic stale-path recovery from finding 4
