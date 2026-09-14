import os
import pytest
from ui.task_logic.backup_files import backup_file_trees, walk_tree


class TestBackupFileTrees:
    def test_returns_the_core_trees_in_configs_before_presets_order(self):
        trees = backup_file_trees()
        prefixes = [t[0] for t in trees]
        assert prefixes == [
            'ssh-keys', 'terraform-state', 'configs', 'presets',
            'plugins/minqlx-plugins', 'plugins/minqlxtended-plugins',
            'plugins/system-hooks',
            # Operator-installed addon packages: an addon uploaded through the
            # UI exists nowhere else, so leaving it out would silently lose it
            # when restoring onto a fresh host.
            'addon-packages',
        ]
        assert prefixes.index('configs') < prefixes.index('presets')

    def test_addon_contributed_trees_are_namespaced_and_come_last(self, monkeypatch):
        """An addon must not be able to claim or shadow a core tree by
        returning a clever prefix."""
        import ui.task_logic.backup_files as backup_files

        monkeypatch.setattr(backup_files, '_addon_contributed_trees',
                            lambda: [('addon/mine', '/tmp/mine', None)])
        prefixes = [t[0] for t in backup_file_trees()]
        assert prefixes[-1] == 'addon/mine'
        assert prefixes.count('configs') == 1


class TestWalkTree:
    def test_yields_nested_files_with_relative_posix_paths(self, tmp_path):
        root = tmp_path / 'root'
        (root / 'a' / 'b').mkdir(parents=True)
        (root / 'a' / 'b' / 'file.txt').write_text('hi')
        (root / 'top.txt').write_text('bye')

        found = dict(walk_tree(str(root)))
        assert set(found.keys()) == {'a/b/file.txt', 'top.txt'}

    def test_missing_root_yields_nothing(self, tmp_path):
        assert list(walk_tree(str(tmp_path / 'does-not-exist'))) == []

    def test_skip_excludes_only_direct_children(self, tmp_path):
        root = tmp_path / 'root'
        (root / 'presets' / 'inner').mkdir(parents=True)
        (root / 'presets' / 'inner' / 'f.txt').write_text('x')
        (root / 'keep.txt').write_text('y')

        found = dict(walk_tree(str(root), skip=lambda name: name == 'presets'))
        assert set(found.keys()) == {'keep.txt'}

    def test_skips_symlinks(self, tmp_path):
        root = tmp_path / 'root'
        root.mkdir()
        real = tmp_path / 'outside.txt'
        real.write_text('secret')
        (root / 'link.txt').symlink_to(real)

        assert list(walk_tree(str(root))) == []


def test_backup_includes_both_plugin_baselines():
    """A restore onto a fresh machine must carry both runtimes' baselines, or a
    minqlxtended host comes back with no plugins."""
    from ui.task_logic.backup_files import backup_file_trees

    prefixes = [prefix for prefix, _, _ in backup_file_trees()]
    assert 'plugins/minqlx-plugins' in prefixes
    assert 'plugins/minqlxtended-plugins' in prefixes


def test_missing_minqlxtended_baseline_is_not_an_error(tmp_path):
    """P2 creates that directory; walking a missing root must yield nothing
    rather than raise."""
    from ui.task_logic.backup_files import walk_tree

    assert list(walk_tree(str(tmp_path / "does-not-exist"))) == []
