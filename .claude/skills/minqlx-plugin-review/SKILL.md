---
name: minqlx-plugin-review
description: >-
  Use when reviewing, writing, or debugging a minqlx/minqlxtended plugin for
  QLSM's plugin pool (ql-assets/data/minqlx-plugins/) or any plugin a user
  wants added to it. Covers frame/thread safety, hot-hook performance,
  HTTP/Redis batching, reload-safe workers, output flood control,
  console-command injection, and minqlx vs. minqlxtended API differences.
---

# minqlx Plugin Review

## Overview

QLSM ships and maintains a pool of custom minqlx/minqlxtended plugins
(`match_restore`, `tournament_access`, `chat_rcon`, `stream_telemetry_unified`,
`lobby`, and others) at `ql-assets/data/minqlx-plugins/` — the authoritative
copy per `docs/architecture.md`'s "Plugin Pool as Source of Truth" entry.
This skill is for *reviewing* a plugin (existing or new) for correctness and
safety issues specific to the minqlx/minqlxtended runtime — not general
Python style, and not the pool/preset sync mechanics themselves (see
`ui/plugin_pool_sync.py` / `tests/test_plugin_pool_preset_sync.py` for that).

## Source of truth: fetch, don't guess

The actual review checklist is **not vendored into this file**. It lives
upstream, maintained independently, at
[`dngrtech/minqlx-plugin-review`](https://github.com/dngrtech/minqlx-plugin-review):

1. Fetch the current checklist before reviewing anything:
   `https://raw.githubusercontent.com/dngrtech/minqlx-plugin-review/main/minqlx-plugin-review/SKILL.md`
   (`WebFetch` it, or `git clone` the repo if a review needs more than that
   one file).
2. Follow it as written — its section order is the checklist: execution
   contexts (which threading/frame decorator a hook needs), the review
   checklist proper, Redis/storage performance, library/environment
   compatibility, minqlxtended-specific differences, common lag spikes and
   their cause, and quick audit steps.
3. If the fetch fails (offline, repo moved, rate-limited), say so explicitly
   instead of reviewing from memory — the checklist can change upstream, and
   a stale recollection here is worse than admitting it couldn't be loaded.

## QLSM-specific context to bring to the checklist

- The engine is **minqlxtended**, not vanilla minqlx — including a vendored
  C-patch chain (item-events, item-respawn, native demo capture, redis-pool,
  set-position) built into the engine, and native `map_entities()`. Apply the
  checklist's minqlxtended-differences section, not the minqlx-only baseline.
- **Edit plugin logic in the pool** (`ql-assets/data/minqlx-plugins/`), never
  directly in `configs/presets/_builtin/default/scripts/` or an instance's
  own copy — the pool is what `ui/plugin_manifest.py` reads `.ql-plugin.json`
  metadata from, and what `setup_host.yml` deploys as the host baseline.
- After a pool edit, run `flask sync-plugin-pool` (or `--check` to verify
  without writing) to mirror it onto the builtin default preset's `scripts/`
  dir — `tests/test_plugin_pool_preset_sync.py` fails the suite if the two
  diverge. The one deliberate exception is `highfps.py`/`highfps_hook.so`, a
  togglable per-preset LD_PRELOAD hook, not a pool plugin.

## Related

- `ql-assets/data/minqlx-plugins/` — the plugin pool this skill reviews.
- `docs/architecture.md` — "Plugin Pool as Source of Truth" entry, full
  pool/preset sync and manifest details.
- `ui/plugin_pool_sync.py`, `tests/test_plugin_pool_preset_sync.py` — the
  sync/drift-guard mechanism itself.
