# Docker-Safe Backup Import Design

## Problem

Global backup import creates one staging directory under `/app` and uses
`os.rename()` to replace every managed file tree. Production Docker deployments
bind-mount SSH keys, Terraform state, inventory, and configs separately from
`/app`. Linux rejects a rename across those filesystem boundaries with `EXDEV`,
so a valid backup cannot be restored.

The existing unit tests put the application root and every managed tree on one
temporary filesystem, so they do not reproduce the Docker layout.

## Chosen Approach

Each managed tree will own its temporary restore state. The importer will create
a hidden staging directory inside the target root, extract that tree there, and
reserve hidden rollback paths inside the same root. All renames for that tree
therefore remain on one filesystem and retain the existing atomic replacement
and rollback guarantees.

The importer will exclude its staging directory from the target's current-child
scan. Existing exclusions still apply, including `configs/presets` while the
outer `configs` tree is restored and the shipped `_builtin` preset directory
while custom presets are restored.

## Restore Flow

1. Decrypt and fully validate the archive and manifest before filesystem work.
2. Write the existing best-effort pre-restore safety snapshot.
3. Ensure every managed root exists and create one hidden staging directory
   inside each root.
4. Extract every archive tree into its corresponding staging directory before
   replacing user data.
5. For each tree, move existing children to hidden rollback paths inside that
   same root, then move staged children into place.
6. Replace and commit the database.
7. On failure, roll back database state and restore swapped file children in
   reverse order.
8. Always remove staging directories; after success, remove rollback paths.

## Error Handling and Compatibility

The API contract and archive format remain unchanged. Expected archive and
password errors continue to return HTTP 400, while unexpected restore failures
remain logged and return HTTP 500. Existing backups remain compatible across
Linux distributions and both Docker and non-Docker deployments.

No cross-filesystem copy fallback will be added because it would weaken the
atomicity and interruption safety promised by the restore workflow.

## Tests

Regression tests will wrap the real rename operation with a filesystem-boundary
guard that raises `EXDEV` whenever a rename crosses into or out of the simulated
SSH-key bind mount. The tests will demonstrate that:

- the old implementation fails under the simulated Docker boundary;
- a successful restore completes while keeping every rename within the tree;
- a database failure rolls restored files back across the same boundary; and
- no hidden staging or rollback paths remain after success or rollback.

The focused backup test suite and full backend suite will run before the PR is
opened.

## Release

This bug fix ships as v1.25.1. `VERSION`, `docs/user/version.json`, and
`docs/user/releases.md` will be updated together. The release note will use the
approved “Bug fixes and improvements” wording.
