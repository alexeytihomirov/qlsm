"""Enumerates the on-disk file trees a global backup captures, beyond the
database: SSH keys, Terraform state, instance configs, non-builtin
presets, and uploaded plugin binaries. Paths are relative to the app's
working directory, matching the convention already used by
ui.preset_support.PRESETS_DIR.
"""
import os

from ui.preset_support import BUILTIN_PRESETS_DIR, PRESETS_DIR

SSH_KEYS_DIR = os.path.join('terraform', 'ssh-keys')
TERRAFORM_STATE_DIR = os.path.join('terraform', 'vultr-root', 'terraform.tfstate.d')
CONFIGS_DIR = 'configs'
MINQLX_PLUGINS_DIR = os.path.join('ql-assets', 'data', 'minqlx-plugins')
SYSTEM_HOOKS_DIR = os.path.join('ql-assets', 'data', 'system-hooks')


def backup_file_trees():
    """Return (archive_prefix, filesystem_dir, skip) tuples.

    `skip(name)` excludes a *direct child* of the root from that tree's
    walk. Order matters: 'configs' must come before 'presets' because
    PRESETS_DIR (configs/presets) is nested inside CONFIGS_DIR — the
    'configs' tree excludes its presets/ subfolder (skip below), and the
    'presets' tree captures it separately (excluding the app-shipped
    _builtin folder). On restore, this ordering guarantees configs/presets
    doesn't exist yet when the 'presets' entry places its own content
    there — see ui/task_logic/backup_import.py.
    """
    return [
        ('ssh-keys', SSH_KEYS_DIR, None),
        ('terraform-state', TERRAFORM_STATE_DIR, None),
        ('configs', CONFIGS_DIR, lambda name: name == 'presets'),
        ('presets', PRESETS_DIR, lambda name: name == os.path.basename(BUILTIN_PRESETS_DIR)),
        ('plugins/minqlx-plugins', MINQLX_PLUGINS_DIR, None),
        ('plugins/system-hooks', SYSTEM_HOOKS_DIR, None),
    ]


def walk_tree(root, skip=None):
    """Yield (relative_posix_path, absolute_path) for every real file
    under `root`. Symlinks are skipped (never followed into or copied),
    mirroring the same caution already used by preset export."""
    if not os.path.isdir(root):
        return
    for current_root, dirs, files in os.walk(root):
        if current_root == root and skip:
            dirs[:] = [d for d in dirs if not skip(d)]
        for filename in sorted(files):
            full_path = os.path.join(current_root, filename)
            if os.path.islink(full_path):
                continue
            rel_path = os.path.relpath(full_path, root).replace(os.sep, '/')
            yield rel_path, full_path
