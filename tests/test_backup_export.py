import io
import json
import zipfile

import pytest
from ui.task_logic.backup_export import build_backup_archive, build_backup_zip_bytes
from ui.backup_crypto import MAGIC_ENCRYPTED, MAGIC_PLAIN, decrypt_archive


@pytest.fixture
def app_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'VERSION').write_text('9.9.9')
    (tmp_path / 'terraform' / 'ssh-keys').mkdir(parents=True)
    (tmp_path / 'terraform' / 'ssh-keys' / 'host1_id_rsa').write_text('PRIVATE KEY')
    (tmp_path / 'configs' / 'myhost' / '1').mkdir(parents=True)
    (tmp_path / 'configs' / 'myhost' / '1' / 'server.cfg').write_text('sv_hostname test')
    (tmp_path / 'configs' / 'presets' / 'mypreset').mkdir(parents=True)
    (tmp_path / 'configs' / 'presets' / 'mypreset' / 'server.cfg').write_text('preset cfg')
    (tmp_path / 'configs' / 'presets' / '_builtin' / 'default').mkdir(parents=True)
    (tmp_path / 'configs' / 'presets' / '_builtin' / 'default' / 'server.cfg').write_text('builtin, not backed up')
    return tmp_path


class TestBuildBackupZipBytes:
    def test_contains_manifest_and_db_export(self, app, app_root):
        with app.app_context():
            zip_bytes = build_backup_zip_bytes()
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
        names = archive.namelist()
        assert 'manifest.json' in names
        assert 'db_export.json' in names
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['type'] == 'qlsm-global-backup'
        assert manifest['qlsm_version'] == '9.9.9'

    def test_includes_file_trees_and_excludes_builtin_presets(self, app, app_root):
        with app.app_context():
            zip_bytes = build_backup_zip_bytes()
        names = zipfile.ZipFile(io.BytesIO(zip_bytes)).namelist()
        assert 'files/ssh-keys/host1_id_rsa' in names
        assert 'files/configs/myhost/1/server.cfg' in names
        assert 'files/presets/mypreset/server.cfg' in names
        assert not any('_builtin' in n for n in names)
        # configs/presets must not be double-captured under the 'configs' prefix
        assert not any(n.startswith('files/configs/presets/') for n in names)


class TestBuildBackupArchive:
    def test_no_password_is_plaintext(self, app, app_root):
        with app.app_context():
            blob, filename = build_backup_archive(None)
        assert blob.startswith(MAGIC_PLAIN)
        assert filename.endswith('.qlsmbak')
        zipfile.ZipFile(io.BytesIO(decrypt_archive(blob, None)))  # doesn't raise

    def test_with_password_is_encrypted(self, app, app_root):
        with app.app_context():
            blob, _ = build_backup_archive('hunter2')
        assert blob.startswith(MAGIC_ENCRYPTED)
        zipfile.ZipFile(io.BytesIO(decrypt_archive(blob, 'hunter2')))  # doesn't raise
