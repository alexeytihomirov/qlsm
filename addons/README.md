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

**No feature addon does.** QLSM's image carries this documentation and the
reference examples, nothing else. Every real addon lives in a repository the
operator installs from, so a QLSM install only runs the features its operator
asked for.

| Addon | Where it lives |
|-------|----------------|
| `telemetry-relay` | [qlsm-extra](https://github.com/alexeytihomirov/qlsm-extra) -- **owns the feature.** Core has no telemetry endpoints, tasks, settings module, playbook, payload or UI left. |
| `demo-management` | qlsm-extra -- **owns the feature.** The Demos screen (as a tier-2 component), its endpoints, `ansible_instance_demos.py` and its own copy of the SFTP transport. Recognises raw `.dm_91` only by default; packed/derived formats are another addon's job to add via the `demo_management.file_kinds` hook. Not installing it means no demo listing/download in the UI at all -- by design. |
| `qlmatch-packer` | qlsm-extra -- **owns the format.** Deploys the external Node `.qlmatch` packer to hosts (`host.payload_sync`), teaches `demo-management` to recognise `.qlmatch`/`.replay.json.gz`/`.packer.log` (`demo_management.file_kinds`), clusters a pack with its sidecar/log into one row and contributes Rebuild-sidecar/Full-rebuild actions to the Demos modal (`demo_management.match_groups`), and owns the Bearer-token external match API (`/api/addons/qlmatch-packer/instances/<id>/matches`, which came from core's old `/api/v1/instances/<id>/matches`). Its only UI presence is what it contributes into demo-management's. |
| `demo-stream` | qlsm-extra -- **owns the UI.** The built-in feature had four endpoints and no frontend at all, so this adds a screen rather than replacing one. |
| `_examples/hello-addon` | Here, reference only. Not loaded (`_examples` has no manifest of its own); copy it into the volume to try it. |
| `_examples/css-test-addon` | Here, reference only. Smallest possible tier-2 component, there only to prove `ui/Panel.css` gets loaded next to `ui/Panel.js`. Not loaded; copy it into the volume to try it. |
| `_examples/ui-kit-test-addon` | Here, reference only. Exercises the shared `window.__qlsm.ui` kit (`Modal`, `Button`, `Panel`/`Card`, `AddonField`, `Icon`, `Stack`/`Row`) and needs no CSS of its own. Not loaded; copy it into the volume to try it. |

**Where the line falls.** Mechanics two addons both need (the stats-hub key
storage and cvar helpers; the SFTP "open a session to this instance's demo
dir" plumbing) used to sit in core -- `ui/stats_hub.py`,
`ui/instance_demo_transport.py` -- precisely because more than one feature
used them. That did not survive the addons moving out of the image. The addon
system has no way to declare or enforce a dependency between addons, so a
third "shared" addon could be uninstalled out from under both dependents; and
core cannot be asked to keep a module alive for a feature it no longer ships.

So each addon carries its **own private copy** of the mechanics it needs,
free to diverge from its sibling. `ui/instance_demo_transport.py` went with
demo-management and is gone from core; `ui/stats_hub.py` is still here only
because core's own demo-stream wiring has not been removed yet, and it is
already duplicated inside both addons that use it. Duplication was chosen
over a dependency the system cannot express -- the cost is two copies
drifting; the cost of the alternative was a feature breaking with no
diagnosis path.

Note what was never shared in the first place: the stats-hub *target* (URL,
ingest token, per-host override, per-instance server ID). telemetry-relay and
demo-stream each own their own, because the two may legitimately point at
different stats-hub instances; neither can see or overwrite the other's.

## Layout

```
<addon-id>/
  qlsm-addon.json     # required: manifest (settings, UI mounts, owned hooks)
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
// ctx = { addonId, scope: { kind, id }, api, apiFor, download, saveBlob, ui, manifest, modal }
```

`ctx.api(method, path, { params, data })` is pre-pinned to your addon's own
prefix; `ctx.apiFor(otherAddonId)` returns the same call pinned to another
addon's, which is how a component runs an action a *different* addon
contributed into it (see "Cross-addon UI contribution" below). Neither can
reach a core endpoint. `ctx.download(method, path, { data, fallbackName })` is the same call
for a file response -- it comes back as `{ blob, filename }`, keeping the
CSRF header and the 401 interceptor a bare `<a href>` would lose, and
`ctx.saveBlob(blob, filename)` hands it to the browser. `ctx.ui` is the
shared component kit.

**A component may be the whole dialog.** A mount point in `host_menu` or
`instance_menu` that declares `"renders": "modal"` gets no shell from core --
your component renders it, which is how a feature keeps a purpose-built
screen (its own width, header actions, subtitle) that the generic shell
cannot express. Then `ctx.modal` is set:

```json
{ "id": "demos", "label": "Demos", "icon": "film",
  "component": "Panel.js", "renders": "modal" }
```

`"component"` is a path relative to the addon's own `ui/` directory (core
serves it from `/api/addons/<id>/ui/<component>`) — not prefixed with `ui/`
itself, or the asset URL doubles up as `.../ui/ui/Panel.js` and 404s.

```js
// ctx.modal = { isOpen, onClose, entity, subtitle }
const { Modal } = window.__qlsm.ui;
return h(Modal, { isOpen: ctx.modal.isOpen, onClose: ctx.modal.onClose, size: '2xl' }, ...);
```

`entity` is the whole host/instance object, not just its id, because a
purpose-built screen usually shows its name and port too. Nothing is rendered
while the bundle loads: the operator clicked a menu entry, and a flash of
placeholder before the real dialog is worse than the dialog simply appearing.

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

## Extension points an addon owns

Core's hooks (`instance.launch_args`, `host.setup`, ...) are integration
points *core* dispatches. An addon can also offer its own, so a second addon
can extend it — add a file format it recognises, a row action, a badge —
without either of them being part of QLSM.

**Core never learns the name.** The addon that is being extended declares its
points in its own manifest; the registry collects those from every installed
manifest at startup and validates subscriptions against them. There is no
table in core to add a name to, and no QLSM release needed to ship a new
extension point.

### Declaring one

```json
{
  "id": "file-browser",
  "hooks": {
    "file_kinds": {
      "scope": "global",
      "list": true,
      "description": "Extra filename extensions to list alongside the defaults"
    }
  }
}
```

| Key | Meaning |
|-----|---------|
| `scope` | `global` / `host` / `instance` — the enable switch that gates a contributor, exactly like core's own hooks. `null` means always, even for a switched-off addon. Defaults to `global`. |
| `list` | `true` for a contribution hook: every contributor's list is concatenated into one flat list. `false` (default) collects one value per addon. |
| `description` | For humans reading the manifest. |

The full hook name is `<your addon id, dashes as underscores>.<point>`, so
the block above declares `file_browser.file_kinds`. **The namespace is built
from your id, not taken from the manifest** — an addon physically cannot
declare a point in core's namespace or another addon's, and a collision with
a core hook name is refused with an error on the addon.

### Dispatching it

The owner calls it from its own code, the same way core calls its own:

```python
from ui.addons import dispatch

extra = dispatch('file_browser.file_kinds', 0)   # -> ['qlmatch', 'replay.json.gz']
```

The second argument is the scope id the gate is checked against (`0` for
`global`). Contributions come back in addon-id alphabetical order.

### Subscribing to someone else's

```python
def register(ctx):
    @ctx.on('file_browser.file_kinds')
    def contribute_file_kinds():
        return ['qlmatch', 'replay.json.gz']
```

Three outcomes, and the difference is deliberate:

- The point exists → subscribed.
- The owner **is installed** but declares no such point → `UnknownHookError`
  at load time, and your addon is listed as broken. It is a typo, and a typo
  that only showed up as "my addon silently does nothing" is the worst
  failure a plugin system has.
- The owner is **not installed** → accepted, logged as dormant, never fires.
  An optional integration must not turn into a hard dependency: shipping an
  addon that extends another has to work whether or not the operator
  installed that other one. Declare it in `depends` if you want the
  relationship visible.

Dispatching a point that nothing declares does not raise either — it logs an
error and returns no contributions. That is the mixed-version case (an addon
package whose code and manifest disagree), and a listing endpoint returning
fewer rows beats it returning a 500.

### Naming

`<owner_addon_id_with_underscores>.<point>` is not a suggestion; it is how
the name is built. Pick the point name for what is contributed
(`file_kinds`, `match_groups`), and note that it does **not** name the
contributor: a second addon contributing the same kind of thing subscribes to
the same hook rather than getting one of its own.

### Expected return shape

`list: true` with a flat list of strings is enough when the consumer only
turns it into a regex. A UI contribution (row actions, bulk actions, badges,
menu entries) needs a structured item instead. There is no schema QLSM
validates — this is convention between a hook's owner and its contributors —
but shape a contribution like:

```python
@ctx.on('file_browser.row_actions')
def contribute_row_actions():
    return [{
        'id': 'my-addon.rebuild',         # "<contributor addon id>.<action>"
        'label': 'Rebuild',
        'icon': 'refresh-cw',             # name from the ctx.ui icon vocabulary
        'addon_id': 'my-addon',           # whose prefix `route` is relative to
        'action': {'route': 'items/{name}/rebuild', 'method': 'POST',
                   'confirm': 'Rebuild this?'},
    }]
```

- `id` is namespaced by the **contributing** addon's id (the mirror image of
  the hook name itself, which is namespaced by the **owner**) so the consumer
  can key a React list and log which addon a broken contribution came from.
- `addon_id` says whose `/api/addons/<id>/` prefix `route` is relative to.
  The consumer is a hand-built component, not a declarative panel, so nothing
  resolves that prefix for it — `ctx.apiFor(addon_id)` is the call.
- `action` reuses the tier-1 `row_actions` route/method/confirm shape
  (`AddonTablePanel.jsx`) rather than inventing a second one.

Keep the payload JSON-safe if it is going to the browser. A callable (say, a
`match(row)` predicate) cannot survive the trip, so a contribution that needs
per-row logic has to resolve it on the Python side and send the result.

### Merge order and conflicts

`dispatch()` iterates addons sorted by id — alphabetical, deterministic
regardless of load or install order. For a `list: true` point every
contributor's return value is concatenated in that order; a handler that
raises is logged and dropped without aborting the others. Render contributed
items in that same order, after the consumer's own.

**Nothing dedupes or resolves conflicts.** Duplicate filename extensions are
harmless (a regex alternation with a repeated branch matches the same set),
but a UI contribution does not get that for free: two addons contributing the
same `id`, or two claiming the same row, will both render unless the
**consumer** guards against it. De-duplicate by `id` (build a dict, log and
drop the later duplicate). `dispatch()` gives you ordering and isolation from
a throwing handler, nothing more.

### What is actually enforced

- **Enforced:** the hook name exists — core's, or a point declared by an
  installed addon. Checked by `ctx.on()` at addon **load** time, not at
  dispatch time.
- **Enforced:** an addon cannot declare a point outside its own namespace,
  and cannot shadow a core hook.
- **Enforced:** every hook in core's own table has a real dispatch call site
  in core (`tests/test_addon_hooks_are_wired.py`).
- **Enforced:** the scope gate attached to the point — a disabled addon's
  handlers are skipped even when the hook fires.
- **Enforced:** whether contributions are flattened into one list (`list`)
  or collected one per addon.
- **Not enforced — return shape.** Beyond list-vs-value, QLSM does not know
  or check what is inside a contribution.
- **Not enforced — who dispatches.** `ctx.on()` and `dispatch()` are
  symmetric from the registry's point of view; nothing stops an addon from
  dispatching a point it does not own. Ownership is a fact about the manifest
  and a convention about the call site, not a runtime check.
- **Not enforced — conflict resolution across contributors.** See above; that
  is entirely on the consuming addon.
