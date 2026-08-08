import os

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
    real_rename = os.rename
    displaced = 0

    def fail_second_displacement(source, target):
        nonlocal displaced
        if os.path.dirname(source) == str(root) and os.path.basename(target).startswith('.qlsm-restore-old-'):
            displaced += 1
            if displaced == 2:
                raise sentinel
        return real_rename(source, target)

    monkeypatch.setattr('ui.task_logic.backup_import.os.rename', fail_second_displacement)

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
    real_rename = os.rename
    installed = 0

    def fail_second_staged_install(source, target):
        nonlocal installed
        if os.path.dirname(source) == str(staged) and os.path.dirname(target) == str(root):
            installed += 1
            if installed == 2:
                raise sentinel
        return real_rename(source, target)

    monkeypatch.setattr('ui.task_logic.backup_import.os.rename', fail_second_staged_install)

    with pytest.raises(OSError) as raised:
        _swap_tree(str(root), str(staged))

    assert raised.value is sentinel
    assert not (root / 'archive-a').exists()
    assert (root / 'old-a').read_text() == 'old a'
    assert (root / 'old-b').read_text() == 'old b'
    assert not _restore_paths(tmp_path)
