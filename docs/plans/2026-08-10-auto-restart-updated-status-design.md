# Runtime-Confirmed `UPDATED` Status Reconciliation

Date: 2026-08-10

## Problem

Saving a running instance with **Restart after saving** disabled correctly syncs
the configuration without restarting the service and leaves the database status
as `UPDATED`. The status means the files on disk are newer than the configuration
loaded by the current QLDS process.

QLSM-managed instance restarts already set the status to `RESTARTING` and then
`RUNNING` when their Ansible task succeeds. Scheduled auto-restarts are different:
the host-local systemd timer updates Workshop content and reboots the host without
calling back into QLSM. The status poller confirms that the instance is live but
only caches live data in management Redis, so the database status remains
`UPDATED` indefinitely. An open Servers page also does not refresh instance records
while `UPDATED` because it is a long-lived settled state.

## Goals

- Change `UPDATED` to `RUNNING` only after confirming that the QLDS service has
  started a new runtime and that the live payload was published by that runtime.
- Cover scheduled host auto-restarts, manual host reboots, and out-of-band service
  restarts with one mechanism.
- Preserve the existing fast QLSM-managed restart flow and its three-second UI
  polling interval.
- Avoid schedule parsing, timer callbacks, minqlx plugin changes, and public API
  response changes.
- Prefer leaving a stale `UPDATED` label over falsely claiming that pending
  configuration was applied.

## Non-Goals

- Replacing the existing instance restart task or its status transitions.
- Reporting host timer execution history.
- Proving that every individual cvar took effect after restart.
- Changing the semantics of stopped instances, which remain `STOPPED` across host
  reboots.

## Considered Approaches

### Reset after the scheduled time

QLSM could calculate the most recent daily, weekly, or monthly schedule occurrence
and clear `UPDATED` after a grace period such as one hour. This appears small but
requires timezone and daylight-saving handling, schedule-change semantics, and
idempotent processing of missed windows. More importantly, it would report
`RUNNING` even if the timer or reboot failed. This approach is rejected.

### Detect a host boot ID change

The status poller could read `/proc/sys/kernel/random/boot_id` and reconcile updated
instances after the value changes. This confirms a host reboot but does not detect
an isolated `qlds@<port>` service restart. It is viable but narrower than the
meaning of `UPDATED`.

### Detect the systemd service invocation identity

systemd assigns a new `InvocationID` each time a service starts. Tracking the
identity for `qlds@<port>.service` directly models the event that makes pending
configuration current. This works for scheduled host reboots and isolated service
restarts without modifying the auto-restart timer or game plugin. This is the
selected approach.

## Data Model

Add a nullable `runtime_invocation_id` string column to `QLInstance`. The value is
the service invocation against which the current status was last reconciled.

The column is operational metadata:

- It starts as `NULL` for existing instances.
- It is not exposed by the public instance API unless implementation needs prove
  otherwise.
- It is deliberately excluded from backup export/import because an invocation ID
  belongs to the runtime on the current host and must not be restored elsewhere.
- A normal database migration adds and removes the nullable column.

## Runtime Identity Probe

Introduce a focused backend helper that reads `InvocationID`, `ActiveState`, and
`ActiveEnterTimestampMonotonic` for one or more `qlds@<port>.service` units over
SSH. Inputs use validated integer ports and the host's existing SSH connection
settings. The remote probe uses one bounded multi-unit `systemctl show` command,
not one sequential subprocess per port. It converts the monotonic active-enter
timestamp to a conservative whole-second epoch value using the target host's boot
time. An identity is usable only when the unit is explicitly `active`, the ID is
a normalized 32-character hexadecimal value, and the start timestamp is valid.

Redis reads use explicit one-second connect and read timeouts and bounded
concurrency of at most eight workers. The multi-unit systemd query has a
five-second timeout, and the containing SSH call has a ten-second deadline: five
seconds for systemd, up to two seconds for the bounded Redis phase, and three
seconds for connection and serialization overhead. Missing units and individual
Redis failures produce partial observations; the remote script still emits valid
siblings. Empty output, SSH failure, timeout, or malformed host-level output
returns no host observation rather than aborting the entire poll cycle.

The regular status poll gathers Redis live status and runtime metadata in the same
SSH round-trip. Runtime metadata remains internal; only the existing live-status
value is written to `server:status:<host_id>:<instance_id>`, preserving the
`GET /api/server-status` contract.

For reconciliation, a live value is fresh only when it is a dictionary whose
`updated` member is an integer (not a boolean) strictly greater than the service's
whole-second start time. Requiring `updated > service_started_at` deliberately
rejects the same-second boundary and may wait for the plugin's next publication.
Missing, malformed, non-dictionary, stale, or pre-start values remain eligible for
the existing management-Redis cache behavior but are absent as reconciliation
evidence. This binds promotion to the observed active invocation instead of a
previous invocation's still-live 15-second Redis payload.

The same helper supports exception-safe single-instance and host-batch identity
reads after successful no-restart updates. Keeping command construction and
parsing in one module prevents update tasks and the poller from developing
different identity semantics.

## Establishing the Pending Baseline

A continuously observed identity alone is insufficient. A service could restart
between the last poll and a no-restart configuration save; comparing against the
old observation would incorrectly attribute that earlier restart to the newly
saved files.

Every backend producer of `UPDATED` follows one rule: after its file-changing work
succeeds, it reads the current service invocation and writes that baseline in the
same database commit that writes `UPDATED`. This applies both to
`sync_instance_configs_and_restart.yml` with `restart=False` and to running
instances left without a restart by the Workshop update task. The captured value
is the exact runtime that still has the previous files loaded. A Workshop update
retains `STOPPED` for an instance that was stopped before the operation, even when
that instance appears in the requested restart set; stopped instances are neither
probed nor changed to an unobservable `UPDATED` state.

If a post-update identity read returns no identity or raises unexpectedly, the
task logs a warning, still succeeds as `UPDATED`, and clears
`runtime_invocation_id`. Probe helpers normalize expected failures, and each update
task also guards the optional probe call so probe defects cannot convert completed
Ansible work into `ERROR`. The first later eligible poll establishes a baseline
without promotion. This can delay reconciliation until another restart, but cannot
create a false `RUNNING` status.

Saves with restart enabled keep their existing behavior: Ansible success writes
`RUNNING` immediately. The status poller may update the stored identity afterward,
but it is not on the critical path.

## Poller Reconciliation

For every instance selected by the existing `RUNNING`/`UPDATED` poll:

1. Cache its public live-status value exactly as today.
2. Reject the observation for reconciliation unless the unit is active, its
   invocation identity and start time are valid, and its dictionary payload has
   an `updated` timestamp strictly after that start time.
3. Read a current snapshot of the row's status and stored baseline after the
   network operation; skip statuses other than `RUNNING` and `UPDATED`.
4. If the stored baseline is `NULL`, issue a guarded update that stores the
   observed identity only when the row still has the snapshotted status and a
   `NULL` baseline. Preserve the status.
5. If the identity is unchanged, make no database change.
6. If the identity changed while the snapshot status is `RUNNING`, issue a guarded
   baseline-only update requiring the row to still be `RUNNING` with the exact
   snapshotted baseline.
7. If the identity changed while the snapshot status is `UPDATED`, issue one
   guarded update that sets `RUNNING` and the new baseline only when the row is
   still `UPDATED` with the exact snapshotted baseline. Append the concise
   reconciliation log only when that conditional update affects one row.

Commit reconciliations once per host where practical. Every status and baseline
write uses instance ID, expected status, and expected baseline as database-level
compare-and-set predicates; a zero-row result means another task won the race and
is left untouched. A database error rolls back only reconciliation changes;
live-status caching continues, and a later poll retries. Failure for one service
must not prevent other instances on the host from being processed.

The transition condition intentionally requires both a new active systemd
invocation and a plugin payload published after that invocation became active. A
newly started but unhealthy QLDS process, or an old payload surviving its process,
does not clear the pending label.

## Concurrency

QLSM-managed manual restart remains:

```text
UPDATED -> RESTARTING -> RUNNING
```

The restart task owns this transition. The runtime reconciler's conditional write
only promotes a row that is still `UPDATED` with the expected baseline at write
time, so it cannot overwrite `RESTARTING`, `CONFIGURING`, `STOPPING`, `STARTING`,
`ERROR`, or `STOPPED`, nor can a baseline-only refresh replace a baseline captured
by a concurrent update task.

The post-save identity read happens after config synchronization. If a service
starts after that read, the subsequent identity change is valid evidence that the
synced configuration could be loaded. If identity capture is ambiguous or fails,
the system falls back to baseline-only behavior instead of guessing.

## Frontend Refresh Behavior

Preserve the current three-second polling interval whenever any instance is in a
task-owned transitional state. Add a separate slow interval, initially 30 seconds,
when at least one instance is `UPDATED` and no faster condition is required.

Polling priority is:

1. Any transitional instance: refresh every three seconds.
2. Otherwise, any `UPDATED` instance: refresh every 30 seconds.
3. Otherwise: no instance-list interval.

This ensures a manual restart still becomes visibly `RUNNING` within roughly one
normal polling interval after its task completes. The slower interval only keeps a
page open across an external or scheduled restart synchronized with the database.

## Rollout

On deployment, existing instances have no baseline. Their first observation with
an active unit and invocation-bound fresh live data records the current identity
without changing `UPDATED`. This prevents the rollout itself from clearing pending
labels. An existing stale `UPDATED` instance may need one further restart before
it self-heals, which is the safe outcome when QLSM has no reliable pre-deployment
runtime identity.

No target-host changes, timer redeployment, minqlx plugin updates, or public API
migration are required. The release must bump `VERSION`, `docs/user/version.json`,
and `docs/user/releases.md` together.

## Testing

Backend tests cover:

- Runtime identity command construction and parsing for one and multiple instances.
- Per-instance tolerance of missing, empty, inactive, failed, and malformed
  systemd results.
- A prior invocation's still-live payload, same-second payload, non-dictionary
  payload, and pre-start payload never qualifying for reconciliation.
- One multi-instance systemd query, bounded Redis timeouts, and a failed service or
  Redis DB not hiding valid sibling observations.
- Post-save baseline capture with `restart=False`.
- Clearing the baseline when post-save capture fails.
- A raised post-save probe exception preserving successful Ansible work as
  `UPDATED` with a cleared baseline.
- Workshop no-restart updates capturing baselines for running instances while
  originally stopped instances remain `STOPPED`.
- First observation establishing a baseline without promotion.
- An unchanged identity preserving `UPDATED`.
- A changed identity plus fresh live data promoting `UPDATED` to `RUNNING`.
- A changed identity without live data preserving `UPDATED`.
- A changed identity on `RUNNING` updating only the baseline.
- A status or baseline changed after reconciliation reads it never being
  overwritten by the guarded write, and no reconciliation log on a lost race.
- One instance failure not blocking reconciliation of another instance.
- Database rollback followed by successful retry on a later poll.

Frontend tests use fake timers to cover:

- Three-second polling for transitional statuses.
- Thirty-second polling for `UPDATED`.
- Fast polling priority when both categories are present.
- Returning from fast to slow polling when only `UPDATED` remains.
- Stopping interval polling after no relevant status remains.

Documentation updates explain that `UPDATED` represents configuration pending on
the current service invocation and clears after a confirmed healthy restart,
including scheduled auto-restarts.

---
**Review loop closed:** 2026-08-10
- Findings: `/home/rage/qlsm/docs/findings/2026-08-10-auto-restart-updated-status-findings.md`
- Assessment: `/home/rage/qlsm/docs/assess-review-findings/2026-08-10-auto-restart-updated-status-assessment.md`
- Accepted findings folded in: 1. A new invocation can be paired with the previous invocation's Redis payload, 2. The plan does not baseline every producer of `UPDATED`, 3. Refresh-then-commit is still a time-of-check/time-of-use race, 4. One slow per-port probe can still discard every observation for the host, 5. An unexpected baseline-probe exception turns a successful save into `ERROR`
- Deferred: none
