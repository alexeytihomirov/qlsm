# names.py 1.1.0 behavior

This is the plugin version, independent of the QLSM application version. Both
runtime pools and their built-in default presets carry `VERSION = "1.1.0"`.

- `!name <colored name>` / `!setname <colored name>` registers a spelling;
  `!name` removes an existing registration. Existing validation and Redis keys
  (`minqlx:players:<SteamID>:colored_name`) are unchanged.
- With `qlx_enforceSteamName` enabled (default), stored names are restored only
  when their color-stripped base matches the accepted client base, ignoring case.
  An incompatible historical registration is retained but not reapplied.
- A genuine client base-name change invalidates the previous registration and
  becomes the new comparison baseline. Client baseline-change detection remains
  case-sensitive; registration eligibility and command validation remain
  case-insensitive, as before.
- With enforcement disabled, an intentionally different registered alias remains
  valid when the client resends its original spelling with different colors.
  Repeated plugin alias assignments do not replace that original baseline.
- Plugin-generated name writes cannot swallow a later player's rename, including
  when assignment makes no change, is blocked, or raises. Guard lifetime is the
  synchronous setter invocation, not the next arbitrary userinfo event.
- After a plugin reload, the first fresh client name update initializes missing
  baseline state. Minqlxtended also lazily reads Redis once for missing registration
  state, caching both positive values and a known-negative `None`. Commands can be
  used immediately after reload; if no baseline exists they use the current player
  snapshot before assigning a name. Reset does not force a display-name rewrite.

## Storage visibility and limits

Minqlx still observes external Redis registration additions, edits and deletions
on each name event (one GET instead of EXISTS + GET). This remains synchronous
Redis I/O, not an asynchronous or session-cache performance fix. Minqlxtended
retains its existing session-cache policy: external changes become visible after
reconnect/load or missing-state hydration following reload, not on every event.
Commands update its local cache.

“Steam-name enforcement” compares local game names, not an authenticated Steam
profile. Reload cannot recover a client's pre-alias history or discover a changed
Steam persona remotely. Send fresh client `name <newname>` input or reconnect.

Rankcolors ownership, colors, hook ordering and priorities are unchanged; when
both plugins rewrite colors the existing ordering still determines final colors.
This release prevents an ineligible stale **base name** being restored, not color
competition. No live reload, deployment or server restart accompanies these files.

Audit decisions and offline test boundaries:
[`names-1.1.0-audit.md`](names-1.1.0-audit.md).
