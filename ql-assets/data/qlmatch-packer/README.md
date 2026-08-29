# qlmatch-packer

Builds one `.qlmatch` package (zip, STORE) per finished match from the
per-player POV `.dm_91` files + `index/*.snaps.json` that minqlxtended's
native demo capture (`demo_match.c`, vendored in
`ql-assets/patches/minqlxtended/`) leaves in an instance's demo directory,
then optionally delivers it to any number of rclone targets.

Contract: `ql-demo-recorder/docs/superpowers/prompts/2026-08-17-sv-demorecord-multi-pov-AGENT-PROMPT.md`,
section "Post-process (off the game thread) -> `.qlmatch`".

## How it runs in production

- Deployed to every game host at `/home/ql/qlmatch-packer/` by
  `ansible/playbooks/tasks/sync_qlmatch_packer.yml` (part of host setup and
  of the "Update Plugins" host action). Requires Node.js >= 22 (installed by
  the same task from NodeSource; `vendor/qldemo` uses
  `import ... with { type: "json" }`).
- Launched by `demo_native_autorecord.py` (plugin pool) as a **separate
  process** on `demo_match_finalized` — never on the QLDS game thread and
  never inside the QLDS process. Output goes to
  `<demo_dir>/<match_id>.packer.log`; if the packer (or node) is missing on
  the host, the plugin falls back to its old in-process zip build.
- Configured per instance via plugin cvars (editable from the QLSM Plugins
  tab, delivered through server.cfg like every other setting):
  - `qlx_qlmatchNameTemplate` — output filename template (no extension)
  - `qlx_qlmatchRcloneTargets` — comma-separated rclone destinations
    (e.g. `gdrive:ql-demos/frontier,/home/ql/qlmatch-archive`)
- rclone itself must be installed and its remotes configured on the game
  host by the operator (`rclone config`); the packer only calls
  `rclone copy <pack> <target>` per target.

## CLI

```
node pack.mjs --dir <demo_dir> --match-id <stamp> [--map <map>]
              [--name-template <tpl>] [--rclone-targets a,b]
              [--min-window-ms 5000] [--out-dir <dir>]
```

Exit codes: 0 ok; 2 window validation failed (empty/short POV overlap — no
zip written, raw files left in place); 3 no POV files for the match; 4 pack
written but >= 1 rclone delivery failed; 5 usage/IO error.

## Filename template placeholders

Every substitution is stripped of QL color codes and sanitized to
`[A-Za-z0-9._-]`. Default template: `{match_id}_{map}`.

| Placeholder | Meaning |
|---|---|
| `{match_id}` | UTC match stamp, e.g. `20260816T161443Z` |
| `{date}` / `{time}` | `20260816` / `161443` from the stamp |
| `{map}` | map name |
| `{gametype}` | short gametype (`ffa`, `duel`, `tdm`, `ca`, `ctf`, ...) |
| `{players}` | all non-spectator players, `-`-joined |
| `{pov_players}` | players that actually have a POV demo in this pack |
| `{total_players}` | player count |
| `{red_count}` / `{blue_count}` | per-team player counts |
| `{red_players}` / `{blue_players}` | per-team name lists |
| `{teams}` | `red1-red2_vs_blue1-blue2` (or `{players}` in non-team modes) |

If the rendered name lacks the match stamp and a file with that name already
exists, `_{match_id}` is appended instead of overwriting the previous match.

## vendor/qldemo

Verbatim copy of the **production** demo parser
`ql-stream-tools/live-overlay/lib/qldemo/` (not the stale
`_tmp/overkilldemos/qldemo-nquery` snapshot the first prototype used).
Refresh with `bash sync-vendor.sh` from a monorepo workspace whenever
lib/qldemo changes, and commit the result — see `vendor/VENDOR-INFO.txt`.
