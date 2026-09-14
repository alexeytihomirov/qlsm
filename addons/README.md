# QLSM addons

Optional features that plug into QLSM without core knowing they exist.
Full design: `docs/superpowers/specs/2026-09-14-qlsm-addon-system-design.md`
in the monorepo.

## Where addons are loaded from

| Source | Path | Notes |
|--------|------|-------|
| Bundled | `addons/<id>/` | Ships inside the Docker image |
| Installed | `$ADDON_PACKAGES_DIR/<id>/` (default `./addon-packages`) | Operator-writable volume |

A directory is an addon only if it contains `qlsm-addon.json`. An id present
in both sources resolves to the **installed** copy, so an operator can
override a bundled addon without rebuilding the image.

`addons/_examples/` has no manifest of its own, so it is skipped by the
scanner — the reference addon inside it does not load in production. To try
it, copy `addons/_examples/hello-addon/` into your addon-packages volume and
restart.

## What ships here today

| Addon | State |
|-------|-------|
| `telemetry-relay` | **Migration.** Runs alongside the built-in Telemetry Relay panel; entries suffixed "(addon)". Delegates to `ui/telemetry_relay_settings.py` + `ui/task_logic/ansible_telemetry_relay.py` rather than copying them, so the two paths cannot drift while both exist. |
| `demo-management` | **Migration.** Runs alongside the built-in Demos modal. Delegates to `ui/task_logic/ansible_instance_demos.py`, which owns the filename validation that keeps a remote path safe. |
| `_examples/hello-addon` | Reference only. Not loaded (`_examples` has no manifest of its own); copy it into the volume to try it. |

Both migration addons are verified against a real host **before** the
built-in code they duplicate is deleted, and that deletion is a separate
change. Until then, seeing two "Telemetry Relay" entries in a host menu is
expected, not a bug.

## Layout

```
<addon-id>/
  qlsm-addon.json     # required: manifest
  backend.py          # optional: register(ctx)
  ui/                 # optional: pre-built components (.js/.css/.map only)
  playbooks/          # optional: addon-owned Ansible
  assets/             # optional: host-side payload
  plugins/            # optional: minqlx plugins the addon ships
```

## Failure isolation

A broken addon never takes QLSM down. A malformed manifest, an import that
raises, a `register()` that throws, a hook handler that blows up mid-deploy,
a component that crashes while rendering — each is contained and reported.
Broken addons stay **visible** on the Addons page with their error attached,
because silently disappearing is the harder failure to diagnose.

## Trust

An addon's Python half runs in-process with QLSM's full authority: the
database, SSH private keys, the cloud API key. There is no sandbox, and the
`AddonContext` is an ergonomics boundary, not a security one. Only install
addons you would trust with the QLSM host itself.

## Scopes

Three layers, each requiring the one above it:

| Scope | Means |
|-------|-------|
| `global` | The addon is on for this QLSM at all |
| `host` | Its payload is installed / enabled on that host |
| `instance` | The feature is on for that game server |

Turning an instance on while its host is off stores the intent but leaves the
addon inactive; the UI says so rather than silently doing nothing.

## UI, tier 1 — declarative

The manifest's `ui` block declares mount points; QLSM renders them with its
own components. Panel kinds: `form`, `table`. A `form` panel with no `load`
route is **managed** — values are stored by QLSM and an addon needs no
backend code at all for its settings.

A `table` panel declares its columns (`text` / `bytes` / `datetime`
formatting), an optional `selectable` flag with `bulk_actions`, and
`row_actions`. A route may contain both scope placeholders (`{instance_id}`)
and row placeholders (`{name}`); row values are URL-encoded, so a filename
with a space cannot break the query string. An action with `"download": true`
is fetched as a blob and saved under the filename from the response's
`Content-Disposition`, which keeps auth headers and works for POST endpoints
(the batch download posts a selection and gets a zip back). Bulk actions post
the selection under `selection_key` (default `selected`), so an addon can
keep the field name its API already uses.

Mount points: `host_menu`, `instance_menu`, `instance_tabs`,
`settings_section`, `page`. Routes in a panel are always relative to the
addon's own `/api/addons/<id>/` prefix; absolute paths are rejected at
manifest validation, so a panel cannot point at a core endpoint.

## UI, tier 2 — the addon's own component

Build it yourself and ship the built file in `ui/`:

```js
// vite.config.js in the addon's own project
export default {
  build: { lib: { entry: 'src/Panel.jsx', formats: ['es'] } },
  rollupOptions: { external: ['react', 'react-dom', '@qlsm/ui'] },
}
```

**Do not bundle React.** QLSM publishes its own React and UI kit on
`window.__qlsm` precisely so your bundle can mark them external — two React
copies on one page break hooks in ways that are painful to debug.

The component receives one prop:

```js
export default function Panel({ ctx }) { /* ... */ }
// ctx = { addonId, scope: { kind, id }, api, ui, manifest }
```

`ctx.api(method, path, { params, data })` is pre-pinned to your addon's own
prefix. `ctx.ui` is the shared component kit.

Declare `"ui_api"` in the manifest. A core that does not implement the
version you ask for lists the addon but withholds its UI, with the reason
shown — instead of mounting it and crashing.
