"""Enumerates the on-disk file trees a global backup captures, beyond the
database: SSH keys, Terraform state, instance configs, non-builtin
presets, operator-downloaded plugins and system hooks. Paths are relative to the app's
working directory, matching the convention already used by
ui.preset_support.PRESETS_DIR.
"""
import os

from ui.preset_support import BUILTIN_PRESETS_DIR, PRESETS_DIR

SSH_KEYS_DIR = os.path.join('terraform', 'ssh-keys')
TERRAFORM_STATE_DIR = os.path.join('terraform', 'vultr-root', 'terraform.tfstate.d')
CONFIGS_DIR = 'configs'
# The operator tier of the plugin pool (see ui/plugin_pool.py). The built-in
# tier in ql-assets/ is image-owned and not backed up, for the same reason
# configs/presets/_builtin is skipped below: a restore must never replace
# release-managed files with an older copy. Archives from before this split
# carry 'plugins/minqlx-plugins' and 'plugins/minqlxtended-plugins' trees;
# restore ignores prefixes that are not listed here, so those are skipped.
OPERATOR_PLUGINS_DIR = os.path.join('data', 'shared-plugins')
SYSTEM_HOOKS_DIR = os.path.join('ql-assets', 'data', 'system-hooks')
# Operator-installed addon packages. Real state: an addon uploaded through the
# UI exists nowhere else, so a backup that skipped this would silently lose it
# on a restore to a fresh host.
ADDON_PACKAGES_DIR = 'addon-packages'
RESTORE_PATH_PREFIX = '.qlsm-restore-'


def is_restore_child(name):
    """Return whether a direct child belongs to restore bookkeeping."""
    return name.startswith(RESTORE_PATH_PREFIX)


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
        ('plugins/shared-plugins', OPERATOR_PLUGINS_DIR, None),
        ('plugins/system-hooks', SYSTEM_HOOKS_DIR, None),
        ('addon-packages', ADDON_PACKAGES_DIR, None),
    ] + _addon_contributed_trees()


def _addon_contributed_trees():
    """Extra trees enabled addons want captured.

    Each handler returns (archive_prefix, directory) pairs. Prefixes are
    namespaced under `addon/` by core, so an addon cannot collide with a core
    tree -- or claim one -- by returning a clever prefix. Returns [] when no
    addon contributes, so the archive layout is unchanged without addons.
    """
    try:
        from ui.addons import dispatch

        contributions = dispatch('backup.export') or []
    except Exception:
        return []

    trees = []
    for item in contributions:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            prefix, directory = item
        elif isinstance(item, str):
            prefix, directory = os.path.basename(item.rstrip('/').rstrip('\\')), item
        else:
            continue
        # Rebuild the prefix from clean segments rather than patching the
        # string: stripping '..' out of '../configs' leaves '/configs' and a
        # doubled separator, which is namespaced but ugly enough to look like
        # a bug later.
        segments = [s for s in str(prefix).replace('\\', '/').split('/')
                    if s and s not in ('.', '..')]
        if not segments or not directory:
            continue
        trees.append(('addon/' + '/'.join(segments), str(directory), None))
    return trees


def walk_tree(root, skip=None):
    """Yield (relative_posix_path, absolute_path) for every real file
    under `root`. Symlinks are skipped (never followed into or copied),
    mirroring the same caution already used by preset export."""
    if not os.path.isdir(root):
        return
    for current_root, dirs, files in os.walk(root):
        if current_root == root:
            excluded = lambda name: is_restore_child(name) or (skip and skip(name))
            dirs[:] = [name for name in dirs if not excluded(name)]
            files = [name for name in files if not excluded(name)]
        for filename in sorted(files):
            full_path = os.path.join(current_root, filename)
            if os.path.islink(full_path):
                continue
            rel_path = os.path.relpath(full_path, root).replace(os.sep, '/')
            yield rel_path, full_path
