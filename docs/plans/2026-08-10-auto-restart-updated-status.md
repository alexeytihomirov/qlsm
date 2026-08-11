# Runtime-Confirmed `UPDATED` Status Reconciliation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically change an instance from `UPDATED` to `RUNNING` after QLSM confirms that its systemd service started a new invocation and resumed publishing live status.

**Architecture:** Add an internal per-instance systemd `InvocationID` baseline. A shared, bounded SSH probe returns the existing Redis live-status value plus the service identity, active state, and start time. Every producer of `UPDATED` captures the exact post-change baseline, while the poller uses a guarded database update to promote only a still-`UPDATED` row whose identity changed and whose payload timestamp proves that the active invocation published it. The frontend keeps current three-second task polling and adds a 30-second refresh cadence only for settled `UPDATED` instances.

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
- Exactly one multi-unit `systemctl show` call for every validated unit on a host.
- Explicit one-second Redis connect/read timeouts, at most eight concurrent Redis
  workers, a five-second systemd deadline, and a ten-second outer SSH deadline.
- A valid observation containing `status`, an active unit, a normalized
  32-character invocation ID, and a whole-second service start time.
- Inactive, missing, or malformed units yielding no usable invocation identity
  without dropping valid live status.
- One Redis DB timeout and one missing/inactive unit not hiding valid sibling
  observations or exceeding the host deadline.
- A dictionary payload with an integer `updated` value strictly after the service
  start qualifying as fresh; boolean, missing, non-dictionary, same-second, stale,
  and pre-start values not qualifying.
- SSH failure, timeout, and invalid JSON returning `None` for the host probe.

Use this result shape in assertions:

```python
observations = parse_runtime_probe_output(output)
assert observations["27960"].status == {
    "map": "campgrounds",
    "updated": 1_786_320_010,
}
assert observations["27960"].active is True
assert observations["27960"].invocation_id == "a" * 32
assert observations["27960"].service_started_at == 1_786_320_000
assert observation_has_fresh_status(observations["27960"]) is True
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
    status: object | None
    invocation_id: str | None
    active: bool
    service_started_at: int | None


def build_runtime_probe_command(host, instances, redis_password=None): ...
def parse_runtime_probe_output(output): ...
def observation_has_fresh_status(observation): ...
def probe_host_runtime(host, instances, redis_password=None): ...
def probe_instance_invocation_id(instance): ...
def probe_host_invocation_ids(host, instances): ...
```

Build one remote Python command per host. Validate every port as an integer and
every Redis DB with `resolve_redis_db()` before constructing unit names. The remote
script must:

1. Read `/proc/uptime` and `time.time()` once to derive the host boot epoch.
2. Read Redis DBs with a `ThreadPoolExecutor(max_workers=min(8, len(ports)))`.
   Each client sets `socket_connect_timeout=1` and `socket_timeout=1`; each Redis
   failure becomes `status=None` for that port.
3. Run exactly one command for all units:

   ```python
   subprocess.run(
       [
           "systemctl",
           "show",
           *[f"qlds@{port}.service" for port in ports],
           "--property=Id",
           "--property=ActiveState",
           "--property=InvocationID",
           "--property=ActiveEnterTimestampMonotonic",
           "--no-pager",
       ],
       capture_output=True,
       text=True,
       timeout=5,
   )
   ```

4. Parse the blank-line-separated unit records independently and emit one JSON
   observation per requested port even when `systemctl` reports a missing unit or
   exits nonzero after printing valid sibling records. Convert a positive
   `ActiveEnterTimestampMonotonic` value to
   `floor(boot_epoch + monotonic_usec / 1_000_000)`.

Encode the Redis password before embedding it in the remote script. Quote the
completed script with `shlex.quote`; never interpolate unvalidated user strings
into the unit name. The local SSH subprocess uses `timeout=10`, a budget composed
of the five-second systemd deadline, no more than two seconds for concurrent Redis
work, and three seconds for connection and output overhead.

Normalize invocation IDs with:

```python
INVOCATION_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def _normalize_invocation_id(value):
    value = value.strip() if isinstance(value, str) else ""
    return value.lower() if INVOCATION_ID_RE.fullmatch(value) else None
```

`probe_host_runtime()` returns `None` when the SSH round-trip itself fails. A successful round-trip returns a mapping, even when individual observations contain `None` fields.

`parse_runtime_probe_output()` sets `active=True` only for `ActiveState=active` and
sets `invocation_id=None` unless the unit is active, its ID is valid, and its start
time is valid. `observation_has_fresh_status()` returns true only for an active
observation with a usable identity/start time and a dictionary `status` whose
`updated` member is an integer but not a boolean and is strictly greater than
`service_started_at`.

`probe_instance_invocation_id()` and `probe_host_invocation_ids()` select
`REDIS_PASSWORD` only for the self-host provider and return only usable identities.
Both seams normalize expected command, SSH, parse, and missing-observation failures
to `None` or an empty/per-port-`None` mapping and log them; they do not raise into
an update task.

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

Do not require `observation_has_fresh_status()` for caching. The freshness rule is
internal reconciliation evidence only; `_write_status_to_redis()` must continue to
receive the parsed status value exactly as before, including deleting the key for
`None`.

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

| Stored identity | Observed identity | Invocation-bound live status | Snapshot DB status | Expected |
| --- | --- | --- | --- | --- |
| `NULL` | `A` | fresh | `UPDATED` | guarded store of `A`, remain `UPDATED` |
| `A` | `A` | fresh | `UPDATED` | no change |
| `A` | `B` | absent or stale | `UPDATED` | no change |
| `A` | `B` | prior invocation's still-live payload | `UPDATED` | no change |
| `A` | malformed or inactive | fresh-looking | `UPDATED` | no change |
| `A` | `B` | fresh and after B's start | `UPDATED` | guarded store of `B`, become `RUNNING`, append log |
| `A` | `B` | fresh and after B's start | `RUNNING` | guarded store of `B`, remain `RUNNING` |
| `A` | `B` | fresh and after B's start | `RESTARTING` | no change |

Also test that a commit exception rolls back and leaves the row retryable.

Add deterministic lost-race tests for both writes. Return a stale snapshot from
the reconciliation read after a separate session has committed (a) each
task-owned transitional status and (b) a replacement baseline. Assert that the
conditional update affects zero rows and does not change status, baseline, or
logs. Include the same guard assertion for a `RUNNING` baseline-only update.

Use `RuntimeObservation` values directly:

```python
observations = {
    "27960": RuntimeObservation(
        status={
            "map": "campgrounds",
            "players": [],
            "updated": 1_786_320_010,
        },
        invocation_id="b" * 32,
        active=True,
        service_started_at=1_786_320_000,
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

Create snapshot and compare-and-set helpers in the focused module. Do not mutate a
loaded ORM row to reconcile status. The write predicate must contain the instance
ID, exact snapshot status, and exact snapshot baseline (`IS NULL` when the snapshot
baseline is `NULL`):

```python
ELIGIBLE_STATUSES = frozenset({InstanceStatus.RUNNING, InstanceStatus.UPDATED})


def _guarded_runtime_update(snapshot, values):
    statement = (
        update(QLInstance)
        .where(
            QLInstance.id == snapshot.id,
            QLInstance.status == snapshot.status,
            QLInstance.runtime_invocation_id == snapshot.runtime_invocation_id,
        )
        .values(**values)
    )
    return db.session.execute(statement).rowcount == 1
```

`reconcile_runtime_observations()` must first reject any observation for which
`observation_has_fresh_status()` is false. For each remaining instance, query only
ID, current status, and current baseline to create the snapshot, then:

- With a `NULL` baseline, guard an identity-only update and preserve the exact
  snapshot status.
- With an unchanged identity, do nothing.
- With a changed identity and snapshot status `RUNNING`, guard a baseline-only
  update requiring `RUNNING` plus the expected baseline.
- With a changed identity and snapshot status `UPDATED`, guard one update of both
  status (`RUNNING`) and baseline requiring `UPDATED` plus the expected baseline.
  Only after `rowcount == 1`, reload the row and append:

  ```text
  Confirmed service restart; pending configuration is now active. Status: running.
  ```

Commit successful guarded updates and their logs once per host. A zero-row result
is a normal lost race, is not counted as a promotion, and emits no user log. Any
database exception rolls back all reconciliation writes for that host and returns
zero so the next poll can retry. Do not log invocation IDs; they add noise and are
not needed for users.

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
def test_no_restart_save_clears_baseline_and_succeeds_when_probe_raises(): ...
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

For the raised-exception case, make the probe raise `OSError`, initialize the same
stale baseline, and assert that the completed Ansible sync still returns success,
commits `InstanceStatus.UPDATED`, clears the baseline, and emits a warning with
exception context.

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
    try:
        baseline = service_runtime.probe_instance_invocation_id(instance)
    except Exception:
        current_app.logger.warning(
            "Configuration synced, but runtime baseline capture failed for "
            "instance %s",
            instance.id,
            exc_info=True,
        )
        baseline = None
    if baseline is None:
        current_app.logger.warning(
            "Configuration synced without a runtime baseline for instance %s",
            instance.id,
        )
    instance.runtime_invocation_id = baseline
```

Do not probe for `RUNNING` or `STOPPED` outcomes. A `None` result or raised
exception intentionally clears any stale baseline. Write `status=UPDATED` and the
captured or cleared baseline in the same final commit. The module-level warning is
a last-resort boundary in addition to the helper's expected-failure normalization;
runtime capture must never fail otherwise successful configuration work.

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

### Task 5: Apply the baseline invariant to Workshop updates

**Files:**

- Modify: `ui/task_logic/ansible_workshop_update.py:1-105`
- Create: `tests/test_task_workshop_runtime_baseline.py`
- Modify: `tests/test_task_ansible_workshop_update.py:1-120`

**Step 1: Write failing Workshop baseline and stopped-state tests**

Create focused tests covering:

```python
def test_workshop_no_restart_captures_running_instance_baselines_in_one_probe(): ...
def test_workshop_probe_failure_clears_baselines_but_preserves_success(): ...
def test_workshop_probe_exception_clears_baselines_but_preserves_success(): ...
def test_workshop_no_restart_preserves_originally_stopped_instance(): ...
def test_workshop_requested_restart_still_preserves_originally_stopped_instance(): ...
def test_workshop_baseline_does_not_credit_an_earlier_unobserved_restart(): ...
```

For the primary case, start with two `RUNNING` instances and mock one
`probe_host_invocation_ids(host, instances)` call returning their current IDs.
Assert both final `update_instance()` operations write `status=UPDATED` and the
matching `runtime_invocation_id` together.

For the stopped cases, assert an originally `STOPPED` instance remains `STOPPED`
whether or not its ID appears in `restart_instance_ids`, is not included in the
baseline probe, and is not queued for restart. Preserve its existing runtime
baseline and write a log explaining that Workshop files were updated while the
stopped service was left stopped.

For the attribution regression, start with stored baseline A while the current
service is already B, run a successful no-restart Workshop update whose probe
returns B, then reconcile a fresh B observation. Assert it remains `UPDATED`; only
a later fresh C observation may promote it.

**Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_task_workshop_runtime_baseline.py tests/test_task_ansible_workshop_update.py -v
```

Expected: FAIL because Workshop updates do not capture baselines and currently
change originally stopped instances to `UPDATED`.

**Step 3: Capture running baselines once and preserve stopped instances**

Import the module as a stable seam:

```python
from . import service_runtime
```

After the Workshop playbook succeeds and before final per-instance status writes,
build `pending_instances` from originally non-`STOPPED` instances that are not
being restarted. If it is non-empty, call
`service_runtime.probe_host_invocation_ids(host, pending_instances)` exactly once.
Guard that optional call with `try/except Exception`; on a `None` result or raised
exception, warn with context and use a per-port `None` baseline. Do not fail the
successful Workshop task.

Apply this exact final-state order for each instance:

1. If its original status was `STOPPED`, restore `STOPPED`, do not change its
   baseline, and do not queue a restart.
2. Otherwise, if restart was requested, write `RESTARTING` and queue the existing
   restart task; do not include it in baseline capture.
3. Otherwise, call `update_instance()` once with both `status=UPDATED` and
   `runtime_invocation_id=baselines.get(str(instance.port))`. A missing identity
   deliberately clears a stale baseline in the same commit as `UPDATED`.

Keep the existing failure and unexpected-exception paths restoring every original
status. Do not change Workshop playbook behavior or restart queue semantics beyond
preserving originally stopped instances.

**Step 4: Run Workshop and reconciliation tests**

Run:

```bash
pytest tests/test_task_workshop_runtime_baseline.py tests/test_task_ansible_workshop_update.py tests/test_instance_runtime_reconciliation.py -v
```

Expected: PASS. Every successful backend write of `UPDATED` now stores or clears a
post-change baseline, and stopped Workshop instances remain `STOPPED`.

**Step 5: Commit**

```bash
git add ui/task_logic/ansible_workshop_update.py tests/test_task_workshop_runtime_baseline.py tests/test_task_ansible_workshop_update.py
git commit -m "fix: baseline workshop updates safely"
```

### Task 6: Refresh settled `UPDATED` instances without slowing manual restarts

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

### Task 7: Document behavior and bump the patch release

**Files:**

- Modify: `docs/architecture.md:245-250`
- Modify: `docs/user/operations/edit-configs.md:36-44`
- Modify: `docs/user/operations/auto-restart.md:11-19`
- Modify: `VERSION`
- Modify: `docs/user/version.json`
- Modify: `docs/user/releases.md:5-10`

**Step 1: Update technical behavior documentation**

Extend the live-status flow in `docs/architecture.md` to state that the poller also
reads systemd invocation identity, active state, and service start time internally.
Document that `UPDATED` reconciliation requires the payload's integer `updated`
timestamp to be strictly after the active invocation's start time, and that the
database write is conditional on the expected status and baseline.

In `edit-configs.md`, document:

```markdown
When restart is skipped, the instance remains **Updated** until QLSM confirms that
the service has started a new runtime and that runtime has reported live status.
This applies to both configuration saves and Workshop updates and also covers the
next scheduled auto-restart. An instance that was already stopped remains
**Stopped** after a no-restart Workshop update.
```

In `auto-restart.md`, add verification that an instance previously marked
`UPDATED` returns to `RUNNING` after the scheduled reboot, the unit is active, and
the new invocation publishes a post-start live payload.

**Step 2: Bump all three version files together**

Set `VERSION` to:

```text
1.26.1
```

Set `docs/user/version.json` `latest` to `1.26.1`. Add a top release row dated `2026-08-11` with PR `—` unless the actual PR number is already known:

```markdown
| `v1.26.1` | 2026-08-11 | — | Clear an instance's `UPDATED` status after QLSM confirms that its service restarted and resumed live status, including scheduled host auto-restarts. |
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

### Task 8: Full verification and review

**Files:**

- Review all files changed since `origin/main`
- Do not modify production code unless a verification failure identifies a specific defect

**Step 1: Run backend verification**

Run focused local verification:

```bash
pytest tests/test_runtime_invocation_model.py tests/test_service_runtime.py tests/test_instance_runtime_reconciliation.py tests/test_task_server_status_poll.py tests/test_task_apply_config.py tests/test_task_apply_config_runtime_baseline.py tests/test_task_workshop_runtime_baseline.py tests/test_task_ansible_workshop_update.py tests/test_backup_db_serializers.py -v
python3 -m py_compile ui/task_logic/service_runtime.py ui/task_logic/instance_runtime_reconciliation.py ui/task_logic/server_status_poll.py ui/task_logic/ansible_instance_mgmt.py ui/task_logic/ansible_workshop_update.py
.venv/bin/flask db heads
```

Expected: the focused tests PASS, compilation succeeds, and exactly one migration
head is reported. Leave the full `pytest tests/` suite to PR CI.

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

Workshop update without restart:
Originally running instances become UPDATED with their current InvocationID
captured; originally stopped instances remain STOPPED.

Scheduled or external service restart:
UPDATED remains until a new active InvocationID is observed and a dictionary live
payload has an integer `updated` timestamp strictly after that invocation's start,
then becomes RUNNING through a compare-and-set write. The backend poll may take up
to 15 seconds to reconcile, after which an open page refreshes within 30 seconds.
Worst-case end-to-end visibility from the restart is approximately 45 seconds plus
SSH probe and API request duration.

Unhealthy or unobservable restart:
UPDATED remains unchanged. An old invocation's still-live Redis payload, an
inactive unit, or a lost database race cannot promote or overwrite the row.
```

### Task 9: Publish the implementation for user review

**Step 1: Confirm branch state**

Run:

```bash
git branch --show-current
git status --short
```

Expected: branch is `bug/auto-restart-updated-status` and the worktree is clean.

**Step 2: Push the branch**

Push the branch so it is available for user review:

```bash
git push -u origin bug/auto-restart-updated-status
```

**Step 3: Wait for user instruction before opening a pull request**

Stop after pushing and ask the user whether to open a pull request. Only after
explicit instruction, create a PR targeting `main` and include the status-transition
matrix and verification commands in its body. Never enable auto-merge or run
`gh pr merge` until the user clearly asks for it.

**Step 4: Stop before merge**

If a PR was opened, report its URL and wait for explicit merge approval.

---
**Review loop closed:** 2026-08-10
- Findings: `/home/rage/qlsm/docs/findings/2026-08-10-auto-restart-updated-status-findings.md`
- Assessment: `/home/rage/qlsm/docs/assess-review-findings/2026-08-10-auto-restart-updated-status-assessment.md`
- Accepted findings folded in: 1. A new invocation can be paired with the previous invocation's Redis payload, 2. The plan does not baseline every producer of `UPDATED`, 3. Refresh-then-commit is still a time-of-check/time-of-use race, 4. One slow per-port probe can still discard every observation for the host, 5. An unexpected baseline-probe exception turns a successful save into `ERROR`
- Deferred: none
