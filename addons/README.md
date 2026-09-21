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
| `demo-stream` | qlsm-extra -- **owns the feature.** Core has no demo-stream endpoints, tasks, settings module or task-logic left -- its four built-in endpoints existed only to reach parity, and were deleted once this addon's own endpoints fully replaced them. |
| `_examples/hello-addon` | Here, reference only. Not loaded (`_examples` has no manifest of its own); copy it into the volume to try it. |
| `_examples/css-test-addon` | Here, reference only. Smallest possible tier-2 component, there only to prove `ui/Panel.css` gets loaded next to `ui/Panel.js`. Not loaded; copy it into the volume to try it. |
| `_examples/ui-kit-test-addon` | Here, reference only. Exercises the shared `window.__qlsm.ui` kit (`Modal`, `Button`, `Panel`/`Card`, `AddonField`, `Icon`, `Stack`/`Row`) and needs no CSS of its own. Not loaded; copy it into the volume to try it. |

**Where the line falls.** Mechanics two addons both need used to sit in core
precisely because more than one feature used them: `ui/stats_hub.py` (the
stats-hub key storage, the reserve call, the server.cfg cvar helpers), shared
between telemetry-relay and demo-stream via a `feature` argument, and
`ui/instance_demo_transport.py` (the SFTP "open a session to this instance's
demo dir" plumbing), the same pattern for demo-management and qlmatch-packer.

Both are gone from core now, and each of the two addons in each pair carries
its own private copy. A shared addon that both install instead was considered
and rejected: this addon system has no addon-to-addon dependency concept (no
manifest field, no install ordering, no uninstall guard), so a shared addon
could vanish out from under both features at once instead of one of them
degrading gracefully -- the opposite of the failure isolation this doc
promises above. Duplicating is not free -- the two copies of each module are
free to diverge and nothing keeps them in sync -- but it was judged the
lesser risk. Core keeping them alive was not an option either: it no longer
ships the features that motivated them.

Note what was never shared to begin with, even when the mechanics were: the
stats-hub *target* each feature points at (URL, ingest token, per-host
override, per-instance server ID). telemetry-relay and demo-stream each keep
their own, because the two may legitimately point at different stats-hub
instances.

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
  "component": "ui/Panel.js", "renders": "modal" }
```

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

## Cross-addon UI contribution (addon-owned hooks)

None of the tiers above cover one addon adding UI elements — actions,
grouping rules, badges — to another addon's **hand-built** (tier 2)
component. The first precedent is `demo_management.file_kinds`
(qlmatch-packer's `backend.py` `contribute_file_kinds`, dispatched from
demo-management's `ansible_instance_demos.py` `_demo_filename_re()`; both
addons live in the qlsm-extra repo): it is a real, working addon-owned hook,
but it is
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
it exists only because the call site lives in the addon instead of `ui/`. Say
so explicitly in the `HOOK_SCOPES` comment for the entry, the way
`demo_management.file_kinds` already does, and add the name to
`tests/test_addon_hooks_are_wired.py`'s `OUT_OF_TREE` set — that test demands
a real dispatch call site inside this repo, and an addon's is not in it.

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
