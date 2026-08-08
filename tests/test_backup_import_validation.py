import io
import json
import os
import zipfile

import pytest

from ui import db
from ui.backup_crypto import encrypt_archive
from ui.models import Host
from ui.task_logic.backup_db_import import replace_database as real_replace_database
from ui.task_logic.backup_export import build_backup_zip_bytes
from ui.task_logic.backup_files import backup_file_trees
from ui.task_logic.backup_import import BackupRestoreError, restore_backup_archive


@pytest.fixture
def app_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'VERSION').write_text('1.0.0')
    (tmp_path / 'terraform' / 'ssh-keys').mkdir(parents=True)
    (tmp_path / 'terraform' / 'ssh-keys' / 'old_key').write_text('ARCHIVED SSH KEY')
    (tmp_path / 'configs' / 'presets' / '_builtin' / 'default').mkdir(parents=True)
    (tmp_path / 'configs' / 'presets' / '_builtin' / 'default' / 'server.cfg').write_text('shipped with app')
    return tmp_path


def _managed_tree_contents(app_root):
    contents = {}
    for _prefix, root, _skip in backup_file_trees():
        root_path = app_root / root
        contents[root] = {}
        for directory, _dirs, files in os.walk(root_path):
            for filename in files:
                path = os.path.join(directory, filename)
                with open(path, 'rb') as file:
                    contents[root][os.path.relpath(path, root_path)] = file.read()
    return contents


def _restore_paths(app_root):
    paths = list(app_root.glob('.qlsm-restore-staging-*'))
    for _prefix, root, _skip in backup_file_trees():
        paths.extend((app_root / root).glob('.qlsm-restore-staging-*'))
    return paths


def _replace_db_export(zip_bytes, db_export):
    source = zipfile.ZipFile(io.BytesIO(zip_bytes))
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for info in source.infolist():
            if info.filename != 'db_export.json':
                archive.writestr(info, source.read(info))
        archive.writestr('db_export.json', db_export)
    source.close()
    return output.getvalue()


def test_invalid_db_export_json_does_not_create_artifacts_or_mutate_files(app, app_root):
    with app.app_context():
        db.session.add(Host(name='original-host', provider='vultr'))
        db.session.commit()
        zip_bytes = build_backup_zip_bytes()

    blob = encrypt_archive(_replace_db_export(zip_bytes, b'{not json'), None)
    contents_before_restore = _managed_tree_contents(app_root)

    with app.app_context():
        with pytest.raises(BackupRestoreError):
            restore_backup_archive(blob, None)

        assert [host.name for host in Host.query.all()] == ['original-host']
    assert not (app_root / 'backup_snapshots').exists()
    assert not _restore_paths(app_root)
    assert _managed_tree_contents(app_root) == contents_before_restore


def test_malformed_database_row_rolls_back_database_and_completed_file_swaps(app, app_root, monkeypatch):
    ssh_keys = app_root / 'terraform' / 'ssh-keys'
    (ssh_keys / 'archive_only').write_text('archive only')
    state_dir = app_root / 'terraform' / 'vultr-root' / 'terraform.tfstate.d'
    state_dir.mkdir(parents=True)
    (state_dir / 'default.tfstate').write_text('archived state')
    (app_root / 'configs' / 'runtime.cfg').write_text('archived config')
    with app.app_context():
        db.session.add(Host(name='archived-host', provider='vultr'))
        db.session.commit()
        zip_bytes = build_backup_zip_bytes()
        db.session.query(Host).delete()
        db.session.add(Host(name='local-host', provider='standalone'))
        db.session.commit()

    db_export = json.loads(zipfile.ZipFile(io.BytesIO(zip_bytes)).read('db_export.json'))
    del db_export['hosts'][0]['provider']
    blob = encrypt_archive(_replace_db_export(zip_bytes, json.dumps(db_export)), None)
    (ssh_keys / 'old_key').write_text('local ssh key')
    (ssh_keys / 'archive_only').unlink()
    (ssh_keys / 'local_only').write_text('local only')
    (state_dir / 'default.tfstate').write_text('local state')
    (app_root / 'configs' / 'runtime.cfg').write_text('local config')
    contents_before_restore = _managed_tree_contents(app_root)
    reached_replace_database = False

    def track_replace_database(data):
        nonlocal reached_replace_database
        reached_replace_database = True
        return real_replace_database(data)

    monkeypatch.setattr('ui.task_logic.backup_import.replace_database', track_replace_database)

    with app.app_context():
        with pytest.raises(KeyError):
            restore_backup_archive(blob, None)

        assert reached_replace_database
        assert [host.name for host in Host.query.all()] == ['local-host']
    assert _managed_tree_contents(app_root) == contents_before_restore
