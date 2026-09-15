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
| `telemetry-relay` | **Owns the feature.** QLSM core has no telemetry endpoints, tasks, settings module, playbook, payload or UI left. All of it lives here, including `ui/TelemetryRelayModal.jsx`. |
| `demo-management` | **Owns the feature.** The Demos screen, its endpoints, `ansible_instance_demos.py`, and the Bearer-token external API (`/api/addons/demo-management/instances/<id>/matches`, moved from core's old `/api/v1/instances/<id>/matches`) all live here. Uninstalling this addon removes demo listing/download for the UI and for external callers alike -- by design. |
| `demo-stream` | **Owns the UI.** The built-in feature had four endpoints and no frontend at all, so this adds a screen rather than replacing one. Still delegates to `ui/task_logic/demo_stream_instance.py`. |
| `_examples/hello-addon` | Reference only. Not loaded (`_examples` has no manifest of its own); copy it into the volume to try it. |
| `_examples/css-test-addon` | Reference only. Smallest possible tier-2 component, there only to prove `ui/Panel.css` gets loaded next to `ui/Panel.js`. Not loaded; copy it into the volume to try it. |

**Where the line falls.** `ui/stats_hub.py` holds the *mechanics* every
stats-hub integration needs (key storage, the reserve call, the server.cfg
cvar helpers) - that part stays in core because both telemetry and the live
demo stream use it. But the actual stats-hub *target* (URL, ingest token,
per-host override, per-instance server ID) is **not shared** between them:
each feature has its own, bound to a `feature` argument ('telemetry' vs
'demo_stream'), because the two may legitimately point at different
stats-hub instances. `telemetry-relay/settings.py` and `demo-stream`'s own
stats-hub endpoints each own their half; neither can see or overwrite the
other's configuration.

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

## Installing

Settings → Addons → **Install**, and upload a `.zip`. The archive may have
`qlsm-addon.json` at its root or nested one folder deep (what "Compress this
folder" produces). The install directory is named after the manifest's `id`,
not the folder in the archive.

**The addon is not live until QLSM restarts.** Flask cannot hot-add or drop a
blueprint on a running app, so a freshly installed addon is listed as
*pending restart* rather than pretended to be active — the alternative is an
entry whose endpoints 404 with no explanation. Same for uninstall.

Uninstall removes the package directory. It keeps the addon's `AddonState`
rows, so reinstalling the same addon finds its settings again.

The upload is checked for archive size, total uncompressed size, entry count,
per-member compression ratio, absolute/`..` paths, symlinks, and a valid
manifest. Nothing is swapped into place until the whole archive has been
validated and staged, so a rejected upload leaves the previous install
untouched.

## Trust

An addon's Python half runs in-process with QLSM's full authority: the
database, SSH private keys, the cloud API key. There is no sandbox, and the
`AddonContext` is an ergonomics boundary, not a security one. Only install
addons you would trust with the QLSM host itself.

**Read [TRUST.md](TRUST.md) before installing an addon you did not write.**
The install checks above are about not being exploitable by a malformed
archive; they say nothing about whether the code inside is safe to run, and
there is no signing.

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

## UI, tier 1.5 — a component QLSM already builds (bundled addons only)

A feature that already has a purpose-built screen must not lose half of it on
the way into an addon. The declarative panels are generic by design; the
Demos modal alone has a filename filter, a "N of M" counter, a refresh
button, a header subtitle, monospace filenames and a Recorded column that no
generic table reproduces by accident.

So a **bundled** addon may name a component QLSM already builds:

```json
{ "id": "relay", "label": "Telemetry Relay", "icon": "radio",
  "component": "bundled:relay-modal", "renders": "modal" }
```

`renders: "modal"` means the component *is* the whole dialog — QLSM's modal
shell is skipped. The registry lives in
`frontend-react/src/components/addons/bundledPanels.jsx`, and each entry
mounts the same component the built-in menu mounts with its data source
swapped for the addon's endpoints. Parity is then true by construction and
stays true when either side changes.

Only addons shipped in the image can do this — an uploaded `.zip` cannot
reach into QLSM's build, and `bundled:` is refused for it. Everything in that
registry is loaded lazily: it sits in the import chain of every action menu,
and anything heavy at module scope there breaks unrelated pages and their
tests.

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

**CSS is optional and found by convention, not declared in the manifest.**
If your component is `ui/Panel.js`, drop a `ui/Panel.css` next to it and
QLSM links it into the page automatically when that component mounts — no
manifest field needed. It stays in `document.head` for the page's lifetime
(not removed when the mount point unmounts), so switching a tab or panel in
and out doesn't reload it. See `_examples/css-test-addon` for the smallest
possible example.
