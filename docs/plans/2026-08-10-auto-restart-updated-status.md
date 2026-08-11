# Runtime-Confirmed `UPDATED` Status Reconciliation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically change an instance from `UPDATED` to `RUNNING` after QLSM confirms that its systemd service started a new invocation and resumed publishing live status.

**Architecture:** Add an internal per-instance systemd `InvocationID` baseline. A shared SSH probe returns both the existing Redis live-status payload and the service identity; the config-save path captures the exact post-sync baseline, while the poller promotes only a still-`UPDATED` row whose identity later changes and whose live payload is healthy. The frontend keeps current three-second task polling and adds a 30-second refresh cadence only for settled `UPDATED` instances.

**Tech Stack:** Flask, SQLAlchemy/Alembic, Python subprocess/SSH, Redis, pytest, React 19, Vitest, Vite.

---

## Required workflow before implementation

- Invoke `@pre-implementation-review-loop` against this plan and the approved design at `docs/plans/2026-08-10-auto-restart-updated-status-design.md`.
- Incorporate accepted findings into both documents before changing production code.
- Use `@superpowers:test-driven-development` for every behavior change below.
- Keep the work on `bug/auto-restart-updated-status`; never edit `main` directly.
- Do not start or restart any development server or related process.
- The legacy `ui/task_logic/ansible_instance_mgmt.py` file already exceeds the repository size limit. Add only the minimal integration call there and keep all new probe/reconciliation logic in focused modules under 300 lines.

### Task 1: Persist internal runtime identity metadata

**Files:**

- Create: `migrations/versions/20260810000000_add_runtime_invocation_id.py`
- Modify: `ui/models.py:120-165`
- Create: `tests/test_runtime_invocation_model.py`
- Verify unchanged behavior: `ui/task_logic/backup_db_export.py:28-43`
- Verify unchanged behavior: `ui/task_logic/backup_db_import.py:58-72`

**Step 1: Write the failing model test**

Create `tests/test_runtime_invocation_model.py`:

```python
from ui import db
from ui.database import create_host, create_instance
from ui.models import HostStatus, QLInstance
from ui.task_logic.backup_db_export import serialize_database


def test_runtime_invocation_id_is_persisted_but_not_public_or_backed_up(app):
    with app.app_context():
        host = create_host(
            name="runtime-id-host",
            provider="standalone",
            status=HostStatus.ACTIVE,
        )
        instance = create_instance(
            name="runtime-id-instance",
            host_id=host.id,
            port=27960,
            hostname="Runtime ID Test",
        )
        instance.runtime_invocation_id = "a" * 32
        db.session.commit()
        instance_id = instance.id
        db.session.expunge_all()

        stored = db.session.get(QLInstance, instance_id)
        assert stored.runtime_invocation_id == "a" * 32
        assert "runtime_invocation_id" not in stored.to_dict()

        exported = serialize_database()
        assert "runtime_invocation_id" not in exported["instances"][0]
```

**Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/test_runtime_invocation_model.py -v
```

Expected: FAIL because `QLInstance` does not map `runtime_invocation_id`.

**Step 3: Add the model field**

Add beside `redis_db` in `QLInstance`:

```python
runtime_invocation_id = db.Column(db.String(64), nullable=True)
```

Do not add it to `QLInstance.to_dict()`, `_instance_row()`, or backup import. It is host-local operational metadata.

**Step 4: Add the Alembic migration**

Create a migration with the current head `755d969fcce8` as its parent:

```python
"""add runtime invocation id to qlinstance

Revision ID: 20260810000000
Revises: 755d969fcce8
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa


revision = "20260810000000"
down_revision = "755d969fcce8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ql_instance", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("runtime_invocation_id", sa.String(length=64), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("ql_instance", schema=None) as batch_op:
        batch_op.drop_column("runtime_invocation_id")
```

**Step 5: Run model and serializer tests**

Run:

```bash
pytest tests/test_runtime_invocation_model.py tests/test_backup_db_serializers.py -v
.venv/bin/flask db heads
```

Expected: tests PASS and migration output contains exactly `20260810000000 (head)`.

**Step 6: Commit**

```bash
git add ui/models.py migrations/versions/20260810000000_add_runtime_invocation_id.py tests/test_runtime_invocation_model.py
git commit -m "fix: persist instance runtime identity"
```

### Task 2: Build the combined live-status and systemd runtime probe

**Files:**

- Create: `ui/task_logic/service_runtime.py`
- Create: `tests/test_service_runtime.py`
- Modify: `ui/task_logic/server_status_poll.py:1-125`
- Modify: `tests/test_task_server_status_poll.py:1-230`

**Step 1: Write failing probe tests**

Create focused tests for:

- One and multiple `(port, Redis DB)` pairs.
- Self-host target resolution and base64-protected Redis passwords.
- No plaintext password in the SSH command.
- A valid observation containing both `status` and a normalized 32-character invocation ID.
- Missing or malformed invocation IDs becoming `None` without dropping valid live status.
- SSH failure, timeout, and invalid JSON returning `None` for the host probe.

Use this result shape in assertions:

```python
observations = parse_runtime_probe_output(output)
assert observations["27960"].status == {"map": "campgrounds"}
assert observations["27960"].invocation_id == "a" * 32
```

Include a security assertion:

```python
command = build_runtime_probe_command(host, instances, redis_password='p@$$"word')
assert 'p@$$"word' not in " ".join(command)
```

**Step 2: Run the probe tests to verify they fail**

Run:

```bash
pytest tests/test_service_runtime.py -v
```

Expected: FAIL because `ui.task_logic.service_runtime` does not exist.

**Step 3: Implement the focused probe module**

Create `ui/task_logic/service_runtime.py` with these public seams:

```python
@dataclass(frozen=True)
class RuntimeObservation:
    status: dict | None
    invocation_id: str | None


def build_runtime_probe_command(host, instances, redis_password=None): ...
def parse_runtime_probe_output(output): ...
def probe_host_runtime(host, instances, redis_password=None): ...
def probe_instance_invocation_id(instance): ...
```

Build one remote Python command per host. For each validated integer port, it must:

```python
raw = redis.Redis(db=db, password=password).get(
    f"minqlx:server_status:{port}"
)
status = json.loads(raw or "null")
result = subprocess.run(
    [
        "systemctl",
        "show",
        f"qlds@{port}.service",
        "--property=InvocationID",
        "--value",
        "--no-pager",
    ],
    capture_output=True,
    text=True,
    timeout=5,
)
```

Catch Redis and systemctl errors independently per port so either datum can remain useful. Encode the Redis password before embedding it in the remote script. Quote the completed script with `shlex.quote`; never interpolate unvalidated user strings into the unit name.

Normalize invocation IDs with:

```python
INVOCATION_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def _normalize_invocation_id(value):
    value = value.strip() if isinstance(value, str) else ""
    return value.lower() if INVOCATION_ID_RE.fullmatch(value) else None
```

`probe_host_runtime()` returns `None` when the SSH round-trip itself fails. A successful round-trip returns a mapping, even when individual observations contain `None` fields.

`probe_instance_invocation_id()` selects `REDIS_PASSWORD` only for the self-host provider, calls the host probe with one instance, and returns only the observation identity.

**Step 4: Make the status poller consume the shared probe**

Replace the poller's private SSH construction/parsing/subprocess code with `probe_host_runtime()`. Preserve `_write_status_to_redis()` and the existing management Redis key/value contract.

Introduce a small result type:

```python
@dataclass(frozen=True)
class HostPollResult:
    active_count: int
    observations: dict[str, RuntimeObservation]
```

Have `_fetch_and_cache_host()` return `HostPollResult` on a successful SSH probe and `None` on a host-level failure. Cache only `observation.status`.

Do not add reconciliation yet. Update the existing poller tests to import command/parser tests from the new module or remove duplicates covered by `tests/test_service_runtime.py`. Keep `tests/test_task_server_status_poll.py` focused on management Redis caching and host iteration.

**Step 5: Run the focused tests**

Run:

```bash
pytest tests/test_service_runtime.py tests/test_task_server_status_poll.py -v
```

Expected: PASS with the previous Redis cache behavior unchanged.

**Step 6: Commit**

```bash
git add ui/task_logic/service_runtime.py ui/task_logic/server_status_poll.py tests/test_service_runtime.py tests/test_task_server_status_poll.py
git commit -m "refactor: collect service runtime with live status"
```

### Task 3: Reconcile a changed runtime identity safely

**Files:**

- Create: `ui/task_logic/instance_runtime_reconciliation.py`
- Create: `tests/test_instance_runtime_reconciliation.py`
- Modify: `ui/task_logic/server_status_poll.py:100-175`

**Step 1: Write failing reconciliation tests**

Create database-backed tests covering this table:

| Stored identity | Observed identity | Live status | Refreshed DB status | Expected |
| --- | --- | --- | --- | --- |
| `NULL` | `A` | present | `UPDATED` | store `A`, remain `UPDATED` |
| `A` | `A` | present | `UPDATED` | no change |
| `A` | `B` | absent | `UPDATED` | no change |
| `A` | malformed | present | `UPDATED` | no change |
| `A` | `B` | present | `UPDATED` | store `B`, become `RUNNING`, append log |
| `A` | `B` | present | `RUNNING` | store `B`, remain `RUNNING` |
| `A` | `B` | present | `RESTARTING` | no change |

Also test that a commit exception rolls back and leaves the row retryable.

Use `RuntimeObservation` values directly:

```python
observations = {
    "27960": RuntimeObservation(
        status={"map": "campgrounds", "players": []},
        invocation_id="b" * 32,
    )
}
```

**Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_instance_runtime_reconciliation.py -v
```

Expected: FAIL because the reconciliation module does not exist.

**Step 3: Implement reconciliation in a focused module**

Create:

```python
ELIGIBLE_STATUSES = frozenset({InstanceStatus.RUNNING, InstanceStatus.UPDATED})


def reconcile_runtime_observations(instances, observations):
    dirty = False
    promoted = 0
    try:
        for listed_instance in instances:
            instance = db.session.get(QLInstance, listed_instance.id)
            if instance is None:
                continue
            db.session.refresh(instance)
            if instance.status not in ELIGIBLE_STATUSES:
                continue

            observation = observations.get(str(instance.port))
            if (
                observation is None
                or observation.status is None
                or not observation.invocation_id
            ):
                continue

            previous = instance.runtime_invocation_id
            current = observation.invocation_id
            if previous is None:
                instance.runtime_invocation_id = current
                dirty = True
            elif previous != current:
                instance.runtime_invocation_id = current
                dirty = True
                if instance.status == InstanceStatus.UPDATED:
                    instance.status = InstanceStatus.RUNNING
                    append_log(
                        instance,
                        "Confirmed service restart; pending configuration is now active. "
                        "Status: running.",
                    )
                    promoted += 1

        if dirty:
            db.session.commit()
        return promoted
    except Exception:
        db.session.rollback()
        log.exception("Failed to reconcile instance runtime observations")
        return 0
```

Do not log invocation IDs; they add noise and are not needed for users.

**Step 4: Integrate reconciliation after successful host polling**

In `poll_all_hosts()`:

```python
poll_result = _fetch_and_cache_host(host, running, redis_client)
if poll_result is None:
    continue

reconcile_runtime_observations(running, poll_result.observations)
active_count = poll_result.active_count
```

Keep the existing `HostStatus.ERROR -> ACTIVE` recovery conditional on `active_count`.

**Step 5: Run reconciliation and poller tests**

Run:

```bash
pytest tests/test_instance_runtime_reconciliation.py tests/test_task_server_status_poll.py -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add ui/task_logic/instance_runtime_reconciliation.py ui/task_logic/server_status_poll.py tests/test_instance_runtime_reconciliation.py tests/test_task_server_status_poll.py
git commit -m "fix: reconcile updated status after service restart"
```

### Task 4: Capture the exact baseline after a no-restart save

**Files:**

- Modify: `ui/task_logic/ansible_instance_mgmt.py:616-647`
- Create: `tests/test_task_apply_config_runtime_baseline.py`

**Step 1: Write failing config-baseline tests**

Create a separate focused test file rather than expanding the existing near-limit test module. Reuse the same mocked Ansible result pattern and cover:

```python
def test_no_restart_save_stores_post_sync_invocation_id(): ...
def test_no_restart_save_clears_stale_baseline_when_probe_fails(): ...
def test_restart_save_does_not_wait_for_baseline_probe(): ...
def test_stopped_no_restart_save_does_not_probe_runtime(): ...
```

For the primary case:

```python
mock_probe.return_value = "b" * 32
result = apply_instance_config(12, restart=False)
assert mock_instance.status == InstanceStatus.UPDATED
assert mock_instance.runtime_invocation_id == "b" * 32
mock_probe.assert_called_once_with(mock_instance)
```

For probe failure, initialize the mock instance with `runtime_invocation_id="a" * 32`, return `None`, and assert the field is cleared.

**Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_task_apply_config_runtime_baseline.py -v
```

Expected: FAIL because the config task does not call the runtime probe.

**Step 3: Add the minimal save-path integration**

Import the new module, not the function, so tests can patch one stable seam:

```python
from . import service_runtime
```

Immediately before the final successful commit:

```python
if final_status == InstanceStatus.UPDATED:
    instance.runtime_invocation_id = (
        service_runtime.probe_instance_invocation_id(instance)
    )
```

Do not probe for `RUNNING` or `STOPPED` outcomes. A `None` result intentionally clears any stale baseline. Add an application warning when capture fails, but do not fail an otherwise successful configuration save.

**Step 4: Run all config-apply tests**

Run:

```bash
pytest tests/test_task_apply_config.py tests/test_task_apply_config_runtime_baseline.py -v
```

Expected: PASS. Existing restart-success commit counts and status assertions remain unchanged.

**Step 5: Commit**

```bash
git add ui/task_logic/ansible_instance_mgmt.py tests/test_task_apply_config_runtime_baseline.py
git commit -m "fix: baseline runtime after deferred config save"
```

### Task 5: Refresh settled `UPDATED` instances without slowing manual restarts

**Files:**

- Modify: `frontend-react/src/hooks/useInstances.js:7-68`
- Create: `frontend-react/src/hooks/__tests__/useInstances.test.jsx`

**Step 1: Write failing polling-policy tests**

Export a pure policy function and test it first:

```javascript
expect(getInstancePollingInterval([{ status: 'restarting' }])).toBe(3000);
expect(getInstancePollingInterval([{ status: 'updated' }])).toBe(30000);
expect(getInstancePollingInterval([
  { status: 'updated' },
  { status: 'configuring' },
])).toBe(3000);
expect(getInstancePollingInterval([{ status: 'running' }])).toBeNull();
```

Add fake-timer hook tests that mock `getInstances()` and verify:

- `UPDATED` does not refresh at 29,999 ms and does refresh at 30,000 ms.
- A transitional status refreshes at 3,000 ms.
- After a fast refresh returns only `UPDATED`, the old fast interval is cleaned up and the next refresh waits 30 seconds.
- After a refresh returns `RUNNING`, interval polling stops.

**Step 2: Run the frontend test to verify it fails**

Run:

```bash
cd frontend-react && pnpm exec vitest run src/hooks/__tests__/useInstances.test.jsx
```

Expected: FAIL because the policy and slow polling do not exist.

**Step 3: Implement interval selection**

Add:

```javascript
export const POLLING_INTERVAL = 3000;
export const UPDATED_POLLING_INTERVAL = 30000;

export function getInstancePollingInterval(instances) {
  if (instances.some((instance) =>
    POLLABLE_INSTANCE_STATUSES.includes(instance.status)
  )) return POLLING_INTERVAL;
  if (instances.some((instance) => instance.status === 'updated')) {
    return UPDATED_POLLING_INTERVAL;
  }
  return null;
}
```

Replace `shouldPoll` with a memoized interval:

```javascript
const pollingInterval = useMemo(
  () => getInstancePollingInterval(instances),
  [instances]
);

useEffect(() => {
  if (pollingInterval === null) return undefined;
  const intervalId = setInterval(
    () => refreshInstances(false),
    pollingInterval
  );
  return () => clearInterval(intervalId);
}, [pollingInterval, refreshInstances]);
```

Keep `UPDATED` out of `POLLABLE_INSTANCE_STATUSES`; adding it there would make the slow state poll every three seconds.

**Step 4: Run frontend tests and lint**

Run:

```bash
cd frontend-react && pnpm exec vitest run src/hooks/__tests__/useInstances.test.jsx src/pages/__tests__/ServersPage.test.jsx
cd frontend-react && pnpm lint
```

Expected: tests PASS and lint exits zero.

**Step 5: Commit**

```bash
git add frontend-react/src/hooks/useInstances.js frontend-react/src/hooks/__tests__/useInstances.test.jsx
git commit -m "fix: refresh updated instances after external restart"
```

### Task 6: Document behavior and bump the patch release

**Files:**

- Modify: `docs/architecture.md:245-250`
- Modify: `docs/user/operations/edit-configs.md:36-44`
- Modify: `docs/user/operations/auto-restart.md:11-19`
- Modify: `VERSION`
- Modify: `docs/user/version.json`
- Modify: `docs/user/releases.md:5-10`

**Step 1: Update technical behavior documentation**

Extend the live-status flow in `docs/architecture.md` to state that the poller also reads systemd invocation identities internally and reconciles a pending `UPDATED` status only after a new identity has fresh live data.

In `edit-configs.md`, document:

```markdown
When restart is skipped, the instance remains **Updated** until QLSM confirms that
the service has started a new runtime and resumed reporting live status. This also
covers the next scheduled auto-restart.
```

In `auto-restart.md`, add verification that an instance previously marked `UPDATED` returns to `RUNNING` after the scheduled reboot and live recovery.

**Step 2: Bump all three version files together**

Set `VERSION` to:

```text
1.26.1
```

Set `docs/user/version.json` `latest` to `1.26.1`. Add a top release row dated `2026-08-10` with PR `—` unless the actual PR number is already known:

```markdown
| `v1.26.1` | 2026-08-10 | — | Clear an instance's `UPDATED` status after QLSM confirms that its service restarted and resumed live status, including scheduled host auto-restarts. |
```

Before editing, re-read all three version files. If `main` has advanced and the branch has been rebased, bump the then-current patch version instead; the three values must remain identical.

**Step 3: Check documentation and version consistency**

Run:

```bash
git diff --check
python3 -m json.tool docs/user/version.json
test "$(cat VERSION)" = "$(python3 -c 'import json; print(json.load(open("docs/user/version.json"))["latest"])')"
```

Expected: all commands exit zero.

**Step 4: Commit**

```bash
git add docs/architecture.md docs/user/operations/edit-configs.md docs/user/operations/auto-restart.md VERSION docs/user/version.json docs/user/releases.md
git commit -m "docs: explain runtime-confirmed status updates"
```

### Task 7: Full verification and review

**Files:**

- Review all files changed since `origin/main`
- Do not modify production code unless a verification failure identifies a specific defect

**Step 1: Run backend verification**

Run:

```bash
pytest tests/test_runtime_invocation_model.py tests/test_service_runtime.py tests/test_instance_runtime_reconciliation.py tests/test_task_server_status_poll.py tests/test_task_apply_config.py tests/test_task_apply_config_runtime_baseline.py tests/test_backup_db_serializers.py -v
pytest tests/
python3 -m py_compile ui/task_logic/service_runtime.py ui/task_logic/instance_runtime_reconciliation.py ui/task_logic/server_status_poll.py ui/task_logic/ansible_instance_mgmt.py
.venv/bin/flask db heads
```

Expected: all tests PASS, compilation succeeds, and exactly one migration head is reported.

**Step 2: Run frontend verification**

Run:

```bash
cd frontend-react && pnpm test
cd frontend-react && pnpm lint
cd frontend-react && pnpm build
```

Expected: test, lint, and production build commands exit zero.

**Step 3: Review the final diff**

Run:

```bash
git diff --check origin/main...HEAD
git status --short
git diff --stat origin/main...HEAD
git log --oneline origin/main..HEAD
```

Expected: clean whitespace check, only intended files changed, and no uncommitted changes.

**Step 4: Request code review**

Invoke `@requesting-code-review` and assess every finding with `@assess-review`. Apply only accepted findings using test-first fix loops, then rerun the affected verification plus the full suites above.

**Step 5: Verify the user-visible acceptance scenarios**

Confirm from automated tests and code paths:

```text
Save with restart enabled:
CONFIGURING -> RUNNING through the existing task; UI polls every 3 seconds.

Save with restart disabled:
CONFIGURING -> UPDATED with the current InvocationID captured.

Scheduled or external service restart:
UPDATED remains until a new InvocationID and live status are both observed,
then becomes RUNNING; an open page refreshes within 30 seconds.

Unhealthy or unobservable restart:
UPDATED remains unchanged.
```

### Task 8: Publish the implementation for user review

**Step 1: Confirm branch state**

Run:

```bash
git branch --show-current
git status --short
```

Expected: branch is `bug/auto-restart-updated-status` and the worktree is clean.

**Step 2: Push and open a pull request**

Push the branch and create a PR targeting `main`. Include the status-transition matrix and verification commands in the PR body.

```bash
git push -u origin bug/auto-restart-updated-status
gh pr create --base main --title "Fix UPDATED status after scheduled restarts" --body "## Summary
- track each QLDS service runtime with systemd InvocationID
- clear UPDATED only after a new invocation resumes live status
- preserve fast polling for QLSM-managed restarts and add slow UPDATED refreshes

## Test plan
- pytest tests/
- cd frontend-react && pnpm test
- cd frontend-react && pnpm lint
- cd frontend-react && pnpm build"
```

**Step 3: Stop before merge**

Report the PR URL to the user and wait for explicit merge approval. Do not enable auto-merge and do not run `gh pr merge` until the user clearly asks for it.
