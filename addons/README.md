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
| `demo-management` | **Owns the feature.** The Demos screen, its endpoints, and `ansible_instance_demos.py` all live here. Recognises raw `.dm_91` only by default -- packed/derived formats are another addon's job to add via the `demo_management.file_kinds` hook (see `qlmatch-packer`). Uninstalling this addon removes demo listing/download for the UI entirely -- by design. |
| `qlmatch-packer` | **Owns the format.** Deploys the external Node `.qlmatch` packer to hosts (`host.payload_sync`), teaches `demo-management` to recognise `.qlmatch`/`.replay.json.gz`/`.packer.log` (`demo_management.file_kinds`), clusters a pack with its sidecar/log into one row and contributes Rebuild-sidecar/Full-rebuild actions to the Demos modal (`demo_management.match_groups`), and owns the Bearer-token external match API (`/api/addons/qlmatch-packer/instances/<id>/matches`, moved here from `demo-management`, which itself moved it from core's old `/api/v1/instances/<id>/matches`). No declarative panel of its own -- its only UI presence is what it contributes into demo-management's. |
| `demo-stream` | **Owns the UI.** The built-in feature had four endpoints and no frontend at all, so this adds a screen rather than replacing one. Still delegates to `ui/task_logic/demo_stream_instance.py`. |
| `_examples/hello-addon` | Reference only. Not loaded (`_examples` has no manifest of its own); copy it into the volume to try it. |
| `_examples/css-test-addon` | Reference only. Smallest possible tier-2 component, there only to prove `ui/Panel.css` gets loaded next to `ui/Panel.js`. Not loaded; copy it into the volume to try it. |
| `_examples/ui-kit-test-addon` | Reference only. Exercises the shared `window.__qlsm.ui` kit (`Modal`, `Button`, `Panel`/`Card`, `AddonField`, `Icon`, `Stack`/`Row`) and needs no CSS of its own. Not loaded; copy it into the volume to try it. |

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

Or from a repository: Settings → Repositories. A repository that publishes
`qlsm-repository.json` with an `addons` section (see
`ui/plugin_repositories.py` for the format) lists its addon packages there
with one-click **Install** / **Update** — the downloaded `.zip` goes through
exactly the same installer and checks as an upload, including the optional
`sha256` the repo manifest declares for the archive. Update detection
compares the repo entry's `version` against the installed package's own
`qlsm-addon.json`.

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
possible example, or `_examples/ui-kit-test-addon` for one that needs no CSS
at all because every visual piece comes from `ctx.ui`.

## Cross-addon UI contribution (addon-owned hooks)

None of the tiers above cover one addon adding UI elements — actions,
grouping rules, badges — to another addon's **hand-built** (tier 1.5/2)
component. The only precedent today is `demo_management.file_kinds`
(`addons/qlmatch-packer/backend.py`'s `contribute_file_kinds`, dispatched
from `addons/demo-management/ansible_instance_demos.py`'s
`_demo_filename_re()`): it is a real, working addon-owned hook, but it is
narrow (a flat list of filename extensions feeding a regex) and was never
written up as a general pattern. The section below is that write-up, so the
next case (e.g. a `demo_management.match_actions` hook letting
qlmatch-packer add a per-row "Rebuild" button to `ViewDemosModal.jsx`) has
something to follow instead of inventing its own shape.

**This is a convention, not a mechanism QLSM enforces.** See "What
`ctx.on`/`dispatch()` actually check" below for exactly where the line falls.

### What makes a hook "addon-owned"

An ordinary hook (`instance.launch_args`, `host.setup`, ...) is declared in
`ui/addons/hooks.py` *and* dispatched from core (`ui/`). An addon-owned hook
is declared in the same `HOOK_SCOPES` dict, but **dispatched from inside the
addon that consumes the contribution**, not from core — `demo-management`
calls `dispatch('demo_management.file_kinds', 0)` from its own module, the
same way core calls `dispatch('instance.launch_args', instance_id)` from
`ansible_instance_mgmt.py`. Nothing in the registry marks this distinction;
it exists only because the call site happens to live in `addons/` instead of
`ui/`. Say so explicitly in the `HOOK_SCOPES` comment for the entry, the way
`demo_management.file_kinds` already does.

### Naming convention

`<consuming_addon_id_with_underscores>.<extension_point>` — the addon whose
surface is being extended goes first, using its manifest `id` with hyphens
turned into underscores (`demo-management` -> `demo_management`), then a
short noun for what's being contributed (`file_kinds`, `match_actions`).

The name deliberately does **not** include the contributing addon's id.
`demo_management.file_kinds` has exactly one contributor today
(qlmatch-packer), but the hook belongs to demo-management's surface, not to
qlmatch-packer, and a second contributor (some other packed-demo format)
would register the same hook name, not a new one.

### Expected return shape

`file_kinds` gets away with a flat list of strings because the consumer only
turns it into a regex. A UI contribution (row actions, bulk actions, badges,
menu entries) needs a structured item instead. There is no schema QLSM
validates — until a second real UI-contribution hook exists this is a
recommendation, not code — but shape a contribution like:

```python
@ctx.on('demo_management.match_actions')
def contribute_match_actions():
    return [{
        'id': 'qlmatch-packer.rebuild',   # unique, "<contributor_addon_id>.<action>"
        'label': 'Rebuild',
        'icon': 'refresh-cw',             # name from the ctx.ui icon vocabulary
        'match': lambda demo: demo['name'].endswith('.qlmatch'),
        'action': {'route': 'matches/{name}/rebuild', 'method': 'POST', 'confirm': 'Rebuild this match?'},
    }]
```

- `id` is namespaced by the **contributing** addon's id (the mirror image of
  the hook name itself, which is namespaced by the **consuming** addon) so
  the consumer can key a React list and log which addon a broken contribution
  came from.
- `match` keeps the consumer format-agnostic — demo-management does not need
  to know what `.qlmatch` means, only that qlmatch-packer's contribution
  applies to rows for which `match(demo)` is true. This mirrors how
  `file_kinds` already keeps demo-management ignorant of what a `.qlmatch`
  file actually is.
- `action` reuses the tier-1 `row_actions` route/method/confirm shape
  (`AddonTablePanel.jsx`) rather than inventing a second one, since the
  consumer is likely to hand it to a similar route-caller.

### Merge order and conflicts

`dispatch()` (`ui/addons/registry.py`) iterates addons
`sorted(get_addons().values(), key=lambda a: a.id)` — alphabetical by addon
id, deterministic regardless of load/install order. For a hook in
`LIST_HOOKS`, every contributor's return value is concatenated into one flat
list in that order; a handler that raises is logged and dropped, it does not
abort the others. For a UI-contribution hook this means: render contributed
actions in addon-id alphabetical order, after the consumer's own hardcoded
actions (if it has any).

**Nothing dedupes or resolves conflicts.** `file_kinds` never needed
conflict handling because duplicate extensions are harmless (a regex
alternation with a repeated branch still matches the same set). A UI
contribution does not get that for free — two addons contributing the same
`id`, or two `match` predicates both claiming the same row, will both render
unless the **consumer** guards against it. The consuming addon is
responsible for de-duplicating by `id` (e.g. build a `dict` keyed by `id`
before rendering, log-and-drop the later duplicate) — `dispatch()` gives you
ordering and isolation from a throwing handler, nothing more.

### What `ctx.on`/`dispatch()` actually check (`ui/addons/context.py`, `ui/addons/hooks.py`, `ui/addons/registry.py`)

- **Enforced:** the hook name must be a key in the `HOOK_SCOPES` dict —
  `ctx.on()` calls `validate_hook_name()`, which raises `UnknownHookError` at
  addon **load** time (not dispatch time), so a typo'd hook name breaks the
  addon visibly instead of silently firing at nobody.
- **Enforced:** every declared hook has a real dispatch call site somewhere
  in core or an addon (`tests/test_addon_hooks_are_wired.py`) — a hook can't
  be declared and then forgotten.
- **Enforced:** the scope gate (`global`/`host`/`instance`/`None`) attached
  to the hook in `HOOK_SCOPES` — `_gates_open()` skips a disabled addon's
  handlers even if the hook fires.
- **Enforced:** whether `dispatch()` flattens contributions into one list
  (`LIST_HOOKS` membership) or collects one value per addon — the only
  structural contract the registry knows about.
- **Not enforced — naming convention.** `HOOK_SCOPES` is a flat dict of
  strings; `instance.launch_args` and `demo_management.file_kinds` are
  validated identically. The `<owner>.<point>` convention above is a human
  discipline, not a mechanical rule — nothing stops a new hook from being
  named inconsistently.
- **Not enforced — return shape.** Beyond list-vs-single-value
  (`LIST_HOOKS`), QLSM does not know or check what is inside a contribution.
  The dict shape suggested above is convention between a hook's declarer and
  its contributors, not a validated schema.
- **Not enforced — who "owns" a hook.** `ctx.on()` (subscribe) and
  `dispatch()` (fire) are symmetric from the registry's point of view; there
  is no manifest field or registry table recording which addon dispatches a
  given hook. "Addon-owned" is purely a fact about where the `dispatch(...)`
  call site happens to live in the source tree, documented by convention
  (the `HOOK_SCOPES` comment) and nothing else.
- **Not enforced — conflict resolution across contributors.** See "Merge
  order and conflicts" above; this is entirely on the consuming addon.
