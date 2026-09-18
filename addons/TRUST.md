# Addon trust model

Read this before installing an addon you did not write.

## The short version

**Installing an addon gives it everything QLSM has.** There is no sandbox.
An addon is not a plugin with limited permissions; it is a piece of QLSM.

Install addons from sources you would trust with the QLSM host itself, and
with every game host QLSM manages. If you would not paste the author's code
into `ui/` and run it, do not install their addon.

## What an addon can reach

An addon's `backend.py` is imported into the QLSM web and worker processes and
runs with their full authority. That includes, without any further check:

| Reachable | Why it matters |
|-----------|----------------|
| The SQLite database | Every host, instance, user password hash, API key |
| `terraform/ssh-keys/` | The private keys that log into every managed game host |
| The Vultr API key | Can provision and destroy cloud servers, which costs money |
| Ansible + Terraform | Can run arbitrary commands on every managed host |
| The network | Can send anything above anywhere |
| The filesystem | Read and write anything the container user can |

`AddonContext` (`ui/addons/context.py`) is an **ergonomics and consistency
boundary, not a security one**. It exists so addons are written the same way
and so core can change its internals; it does not stop an addon from
importing `ui.models` directly. Nothing in QLSM tries to stop that, and no
future version of this document should imply otherwise unless the addon
backend actually runs out-of-process.

## What the install path does and does not check

Uploading a `.zip` runs these checks before anything lands on disk. They are
about **not being trivially exploitable by a malformed archive** -- they are
not, and cannot be, a judgement about whether the code is safe to run.

Checked:

- Archive size, total uncompressed size, and entry count (zip bombs).
- Every entry path: no absolute paths, no `..`, no symlinks (zip-slip).
- A valid `qlsm-addon.json` at the archive root, with an `id` that is
  kebab-case and matches the directory it installs into.
- Nothing is swapped into place until the whole archive has been validated
  and staged, so a rejected upload leaves the previous state untouched.

**Not** checked, and not checkable:

- What `backend.py` does when imported.
- Whether the addon's own UI bundle is honest.
- Who actually wrote the archive. There is no signing.

## The browser side

An addon's pre-built component is loaded into the same page as QLSM, with a
React error boundary around it and nothing else. It can read the DOM and call
any same-origin endpoint with your session.

An `iframe` sandbox was considered and rejected on purpose: the addon's Python
half already has the database and the SSH keys, so a browser sandbox protects
nothing that has not already been handed over, while costing modals, portals,
theme plumbing and size sync. Sandboxing the UI only becomes worth doing
together with moving the backend out of process -- one decision, not two.

## Uninstalling

Removing an addon deletes its package directory. It does **not** undo what
the addon did while it was installed: rows it wrote, files it put on a game
host, cvars it set in a `server.cfg`, credentials it may have copied
elsewhere. Treat an addon you no longer trust the way you would treat a host
that ran untrusted code, not as something a delete button cleans up.

Its `AddonState` rows are kept on uninstall so that reinstalling the same
addon finds its settings again. Delete them explicitly if that is not what
you want.

## If this changes

The moment addon backends run out-of-process, or signing appears, this
document and `ui/addons/context.py`'s docstring both have to change in the
same commit. A stale trust document is worse than none, because it is the
thing an operator reads instead of the code.
