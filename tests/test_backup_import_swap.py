import os
import shutil

import pytest

from ui.task_logic.backup_import import _swap_tree


def _write_tree(root, files):
    root.mkdir()
    for name, contents in files.items():
        (root / name).write_text(contents)


def _restore_paths(parent):
    return list(parent.rglob('.qlsm-restore-*'))


def test_partial_swap_restores_children_when_displacement_fails(tmp_path, monkeypatch):
    root = tmp_path / 'managed'
    staged = tmp_path / 'staged'
    _write_tree(root, {'old-a': 'old a', 'old-b': 'old b'})
    _write_tree(staged, {'archive-a': 'archive a'})
    sentinel = OSError('second displacement failed')
    real_move = shutil.move
    displaced = 0

    def fail_second_displacement(source, target):
        nonlocal displaced
        if os.path.dirname(source) == str(root) and os.path.basename(target).startswith('.qlsm-restore-old-'):
            displaced += 1
            if displaced == 2:
                raise sentinel
        return real_move(source, target)

    monkeypatch.setattr('ui.task_logic.backup_import.shutil.move', fail_second_displacement)

    with pytest.raises(OSError) as raised:
        _swap_tree(str(root), str(staged))

    assert raised.value is sentinel
    assert (root / 'old-a').read_text() == 'old a'
    assert (root / 'old-b').read_text() == 'old b'
    assert not _restore_paths(tmp_path)


def test_partial_swap_restores_children_when_staged_install_fails(tmp_path, monkeypatch):
    root = tmp_path / 'managed'
    staged = tmp_path / 'staged'
    _write_tree(root, {'old-a': 'old a', 'old-b': 'old b'})
    _write_tree(staged, {'archive-a': 'archive a', 'archive-b': 'archive b'})
    sentinel = OSError('second staged install failed')
    real_move = shutil.move
    installed = 0

    def fail_second_staged_install(source, target):
        nonlocal installed
        if os.path.dirname(source) == str(staged) and os.path.dirname(target) == str(root):
            installed += 1
            if installed == 2:
                raise sentinel
        return real_move(source, target)

    monkeypatch.setattr('ui.task_logic.backup_import.shutil.move', fail_second_staged_install)

    with pytest.raises(OSError) as raised:
        _swap_tree(str(root), str(staged))

    assert raised.value is sentinel
    assert not (root / 'archive-a').exists()
    assert not (root / 'archive-b').exists()
    assert (root / 'old-a').read_text() == 'old a'
    assert (root / 'old-b').read_text() == 'old b'
    assert not _restore_paths(tmp_path)


def test_swap_leaves_restore_namespace_children_unmanaged(tmp_path):
    root = tmp_path / 'managed'
    staged = root / '.qlsm-restore-staging-owned'
    foreign = root / '.qlsm-restore-staging-foreign'
    root.mkdir()
    staged.mkdir()
    foreign.mkdir()
    (foreign / 'local-data').write_text('leave untouched')
    (staged / 'archive-data').write_text('install me')
    staged_foreign = staged / '.qlsm-restore-old-foreign'
    staged_foreign.mkdir()
    (staged_foreign / 'archive-secret').write_text('do not install')

    swapped = _swap_tree(str(root), str(staged))

    assert (foreign / 'local-data').read_text() == 'leave untouched'
    assert (root / 'archive-data').read_text() == 'install me'
    assert (staged_foreign / 'archive-secret').read_text() == 'do not install'
    assert swapped == [('archive-data', None)]


def test_swap_survives_a_directory_rename_that_only_works_via_copy_fallback(tmp_path, monkeypatch):
    """Reproduces the live production failure: a directory whose plain
    os.rename() throws EXDEV (observed on OverlayFS for an un-copied-up
    image layer, unrelated to any Docker bind mount) must still swap
    successfully, because shutil.move() falls back to copy+delete."""
    import errno

    root = tmp_path / 'managed'
    staged = tmp_path / 'staged'
    root.mkdir()
    (root / 'stuck-dir').mkdir()
    (root / 'stuck-dir' / 'plugin.py').write_text('old plugin')
    _write_tree(staged, {'new-file': 'new content'})
    real_rename = os.rename

    def rename_refuses_stuck_dir(source, target):
        if os.path.basename(source) == 'stuck-dir':
            raise OSError(errno.EXDEV, 'Invalid cross-device link', source, target)
        return real_rename(source, target)

    monkeypatch.setattr('ui.task_logic.backup_import.os.rename', rename_refuses_stuck_dir)

    swapped = _swap_tree(str(root), str(staged))

    assert (root / 'new-file').read_text() == 'new content'
    assert not (root / 'stuck-dir').exists()
    displaced_name, backup_path = next(
        (name, path) for name, path in swapped if name == 'stuck-dir'
    )
    assert displaced_name == 'stuck-dir'
    assert os.path.isdir(backup_path)
    with open(os.path.join(backup_path, 'plugin.py')) as f:
        assert f.read() == 'old plugin'
