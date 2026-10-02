"""Installed addons must live inside the data volume every deployment mounts.

A dedicated ./addon-packages bind mount only exists in compose files newer
than a59f023; an install on an older (or hand-copied) compose lost its addon
files on every container recreate while the DB row still said "installed".
"""
import os

from ui.task_logic.backup_files import backup_file_trees


def test_default_install_dir_is_inside_the_data_volume(monkeypatch):
    monkeypatch.delenv('ADDON_PACKAGES_DIR', raising=False)
    import importlib
    import ui.config
    importlib.reload(ui.config)
    try:
        assert os.path.normpath(ui.config.Config.ADDON_PACKAGES_DIR) == os.path.join('data', 'addon-packages')
    finally:
        importlib.reload(ui.config)


def test_backup_captures_the_install_dir_under_its_old_archive_prefix():
    trees = {prefix: fs_dir for prefix, fs_dir, _skip in backup_file_trees()}
    assert os.path.normpath(trees['addon-packages']) == os.path.join('data', 'addon-packages')
