# Runtime-Confirmed UPDATED Status Reconciliation Review Findings

Reviewed:
- `/home/rage/qlsm/docs/plans/2026-08-10-auto-restart-updated-status-design.md`
- `/home/rage/qlsm/docs/plans/2026-08-10-auto-restart-updated-status.md`

## Critical

### A new invocation can be paired with the previous invocation's Redis payload
`serverchecker.py` writes every 10 seconds and leaves its Redis key alive for 15 seconds. During an isolated service restart, the poller can therefore observe invocation `B` while Redis still contains the payload written by invocation `A`. The planned `observation.status is not None` check would promote `UPDATED` even if invocation `B` has not published anything or has already failed. The probe also reads only `InvocationID`, so it does not explicitly enforce the design requirement that inactive or failed units yield no identity. This violates the core goal of confirming a new healthy runtime and the stated preference for a stale label over a false promotion.

Required fix: Amend the design and Tasks 2-3 so live evidence is provably associated with the observed active invocation. At minimum, probe and validate the unit's active state and bind the payload to that invocation using service-start/freshness metadata (for example, compare the payload's existing `updated` value with a systemd start timestamp), or persist a candidate invocation and require a later payload update before promotion. Treat missing, malformed, non-dict, stale, or pre-start status payloads as absent for reconciliation while preserving the existing cache contract.

## Important

### The plan does not baseline every producer of `UPDATED`
`ui/task_logic/ansible_workshop_update.py` also writes `UPDATED`, but Task 4 captures an exact baseline only in `apply_instance_config_logic`. If baseline `A` is stored, an unobserved out-of-band restart changes the service to `B`, and a no-restart Workshop update then writes `UPDATED`, the next poll will attribute the earlier `A -> B` restart to Workshop files downloaded after `B` started and falsely promote the row. The same task currently marks originally stopped instances `UPDATED`, despite the design saying stopped instances retain `STOPPED`; those rows would also trigger 30-second frontend polling indefinitely while their disabled services have no invocation.

Required fix: Inventory every `UPDATED` transition and define one baseline rule for all of them. Add the Workshop update path to the implementation plan and capture the post-update identity atomically with `UPDATED` for running instances. Reconcile the stopped-instance behavior with the design, preferably restoring `STOPPED` for instances that were stopped rather than creating an unobservable `UPDATED` row.

### Refresh-then-commit is still a time-of-check/time-of-use race
`db.session.refresh(instance)` only makes the row current at that instant. Another request or RQ task can commit `CONFIGURING`, `RESTARTING`, `STOPPING`, or another status after the refresh and before the reconciler's host-level commit. The planned ORM mutation can then write `RUNNING` over that newer status and append a log based on stale state. A pre-refresh transitional-status test does not cover this window.

Required fix: Replace the promotion with an atomic compare-and-set that updates only when the database row is still `UPDATED` with the expected baseline (and similarly guard baseline-only updates). Append the reconciliation log only when that guarded update succeeds. Add a deterministic race test in which the status changes after observation/read but before the attempted write and assert that status, baseline, and logs remain task-owned.

### One slow per-port probe can still discard every observation for the host
Task 2 runs a separate `systemctl` subprocess with a five-second timeout for each port, while the current outer SSH call has a ten-second timeout and the plan does not define a replacement host deadline. Because the remote script prints only after processing all ports, two slow units can make the local SSH call time out and discard valid observations already collected for other instances. Redis calls also have no stated connect/read timeout. This contradicts the design requirement that one service failure not prevent other instances on the host from being processed.

Required fix: Specify a bounded multi-instance probe design: use one systemd query for all validated units or bounded concurrent per-unit queries, set explicit Redis connect/read timeouts, and choose an outer SSH deadline consistent with the inner work. Add probe-level multi-instance failure tests; a reconciliation-only test is insufficient.

### An unexpected baseline-probe exception turns a successful save into `ERROR`
The design says any post-save identity-read failure must leave the task successful as `UPDATED` with a cleared baseline. Task 4 directly calls `probe_instance_invocation_id()` inside the outer config-task `try`. A command-construction error, missing observation, OS error not normalized by the helper, or future probe regression would reach the existing broad handler and mark the instance `ERROR`. The planned failure test covers only a normal `None` return.

Required fix: Make the single-instance baseline seam exception-safe by contract and also guard the Task 4 call so every probe failure is converted to `None` plus a warning. Add a test where the probe raises and assert the Ansible success still commits `UPDATED`, clears the prior baseline, and returns success.

## Minor

### The end-to-end UI timing is longer than the stated 30 seconds
The backend reconciles every 15 seconds and the frontend independently refreshes `UPDATED` rows every 30 seconds. From an external restart, worst-case visibility is roughly 45 seconds plus probe/request duration, even though the acceptance scenario says the open page refreshes within 30 seconds.

Suggested fix: State that the UI refreshes within 30 seconds after database reconciliation, and document the approximately 45-second end-to-end worst case. If 30 seconds from restart is a requirement, reduce or coordinate one of the intervals.

## Open Questions

- Is `UPDATED` from a no-restart Workshop update intended to use this same runtime reconciliation? If so, should an originally stopped instance remain `STOPPED` with pending Workshop content, or is a separate stopped-and-pending state required?
- What exact evidence defines a "fresh live payload" from the new invocation: active unit plus payload timestamp after service start, or a later payload observation after first seeing the new invocation?

## Tests To Add

- Observe invocation `B` with the still-live Redis payload from invocation `A`; assert `UPDATED` is not promoted until payload evidence is tied to `B`.
- Return a valid-looking invocation ID for an inactive or failed unit; assert the identity is rejected and no promotion occurs.
- Return a non-dict or malformed per-instance status value with a changed identity; assert it is cached/handled compatibly but cannot qualify for reconciliation.
- Change the row from `UPDATED` to each task-owned transitional status after the reconciler reads it but before its guarded write; assert no status, baseline, or log overwrite.
- Run a no-restart Workshop update after an unobserved service restart; assert the post-update baseline prevents attribution of the earlier restart.
- Preserve `STOPPED` for an originally stopped instance during a no-restart Workshop update, or test the explicitly chosen replacement semantics.
- Make one unit's systemd query and one Redis DB query time out in a multi-instance host probe; assert other observations are returned within the host deadline.
- Make `probe_instance_invocation_id()` raise after successful Ansible sync; assert the save still succeeds as `UPDATED` with a `NULL` baseline.
- Force reconciliation commit failure, then run reconciliation again successfully; assert the second pass promotes and logs exactly once.
- Exercise migration upgrade and downgrade against a temporary SQLite database, not only `flask db heads`.
