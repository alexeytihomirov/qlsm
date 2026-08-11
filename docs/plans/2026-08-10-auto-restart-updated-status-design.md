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
  started a new runtime and is publishing fresh live status.
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

Introduce a focused backend helper that reads the `InvocationID` for one or more
`qlds@<port>.service` units over SSH. Inputs use validated integer ports and the
host's existing SSH connection settings. Empty output, an inactive/missing unit,
SSH failure, timeout, or malformed output produces no identity for that instance
rather than an exception that aborts the entire poll cycle.

The regular status poll should gather Redis live status and runtime identities in
the same SSH round-trip. Runtime metadata remains internal; only the existing live
status object is written to `server:status:<host_id>:<instance_id>`, preserving the
`GET /api/server-status` contract.

The same helper supports a single-instance read after a no-restart configuration
save. Keeping the command construction and parsing in one module prevents the save
task and poller from developing different identity semantics.

## Establishing the Pending Baseline

A continuously observed identity alone is insufficient. A service could restart
between the last poll and a no-restart configuration save; comparing against the
old observation would incorrectly attribute that earlier restart to the newly
saved files.

After `sync_instance_configs_and_restart.yml` succeeds with `restart=False`, the
configuration task therefore reads the service's current invocation identity and
commits it together with `UPDATED`. That value is the exact runtime that still has
the previous configuration loaded.

If the post-save identity read fails, the task still succeeds and sets `UPDATED`,
but clears `runtime_invocation_id`. The first later successful poll establishes a
baseline without promotion. This can delay reconciliation until another restart,
but cannot create a false `RUNNING` status.

Saves with restart enabled keep their existing behavior: Ansible success writes
`RUNNING` immediately. The status poller may update the stored identity afterward,
but it is not on the critical path.

## Poller Reconciliation

For every instance selected by the existing `RUNNING`/`UPDATED` poll:

1. Cache its public live-status payload exactly as today.
2. Refresh or re-query the database row after the network operation so a stale ORM
   object cannot overwrite a newer task-owned status.
3. Skip runtime reconciliation unless the refreshed status is still `RUNNING` or
   `UPDATED`.
4. If no live payload or no invocation identity exists, preserve both status and
   stored baseline.
5. If the stored baseline is `NULL`, save the observed identity and preserve the
   status.
6. If the identity is unchanged, make no database change.
7. If the identity changed while status is `RUNNING`, update only the baseline.
8. If the identity changed while status is `UPDATED` and fresh live status exists,
   set `RUNNING`, update the baseline, and append a concise reconciliation log.

Commit reconciliations once per host where practical. A database error rolls back
only reconciliation changes; live-status caching continues, and a later poll
retries. Failure for one service must not prevent other instances on the host from
being processed.

The transition condition intentionally requires both a new systemd invocation and
a live plugin payload. A newly started but unhealthy QLDS process does not clear
the pending label.

## Concurrency

QLSM-managed manual restart remains:

```text
UPDATED -> RESTARTING -> RUNNING
```

The restart task owns this transition. The runtime reconciler only promotes rows
whose freshly read status is still `UPDATED`, so it cannot overwrite
`RESTARTING`, `CONFIGURING`, `STOPPING`, `STARTING`, `ERROR`, or `STOPPED`.

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

On deployment, existing instances have no baseline. Their first successful poll
records the current identity without changing `UPDATED`. This prevents the rollout
itself from clearing pending labels. An existing stale `UPDATED` instance may need
one further restart before it self-heals, which is the safe outcome when QLSM has
no reliable pre-deployment runtime identity.

No target-host changes, timer redeployment, minqlx plugin updates, or public API
migration are required. The release must bump `VERSION`, `docs/user/version.json`,
and `docs/user/releases.md` together.

## Testing

Backend tests cover:

- Runtime identity command construction and parsing for one and multiple instances.
- Per-instance tolerance of missing, empty, and malformed systemd results.
- Post-save baseline capture with `restart=False`.
- Clearing the baseline when post-save capture fails.
- First observation establishing a baseline without promotion.
- An unchanged identity preserving `UPDATED`.
- A changed identity plus fresh live data promoting `UPDATED` to `RUNNING`.
- A changed identity without live data preserving `UPDATED`.
- A changed identity on `RUNNING` updating only the baseline.
- A refreshed transitional status never being overwritten.
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
