import os
import zipfile

import pytest
from ui import db
from ui.models import Host, ConfigPreset
from ui.backup_crypto import encrypt_archive
from ui.task_logic.backup_export import build_backup_zip_bytes
from ui.task_logic.backup_import import restore_backup_archive, BackupRestoreError, BACKUP_SNAPSHOTS_DIR


@pytest.fixture
def app_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'VERSION').write_text('1.0.0')
    (tmp_path / 'terraform' / 'ssh-keys').mkdir(parents=True)
    (tmp_path / 'terraform' / 'ssh-keys' / 'old_key').write_text('OLD KEY')
    (tmp_path / 'configs' / 'presets' / '_builtin' / 'default').mkdir(parents=True)
    (tmp_path / 'configs' / 'presets' / '_builtin' / 'default' / 'server.cfg').write_text('shipped with app')
    return tmp_path


def _make_backup_with_host(app, app_root, password=None):
    with app.app_context():
        db.session.add(Host(name='original-host', provider='vultr'))
        db.session.commit()
        zip_bytes = build_backup_zip_bytes()
    return encrypt_archive(zip_bytes, password)


class TestRestoreBackupArchive:
    def test_wipes_and_reloads_database(self, app, app_root):
        blob = _make_backup_with_host(app, app_root)
        with app.app_context():
            db.session.query(Host).delete()
            db.session.add(Host(name='pre-existing-host-to-be-wiped', provider='standalone'))
            db.session.commit()

            summary = restore_backup_archive(blob, None)

            names = {h.name for h in Host.query.all()}
            assert names == {'original-host'}
            assert summary['qlsm_version'] == '1.0.0'

    def test_restores_file_trees(self, app, app_root):
        (app_root / 'configs' / 'presets' / 'custom').mkdir(parents=True)
        (app_root / 'configs' / 'presets' / 'custom' / 'server.cfg').write_text('custom preset')
        with app.app_context():
            db.session.add(Host(name='h', provider='vultr'))
            db.session.commit()
            zip_bytes = build_backup_zip_bytes()
        blob = encrypt_archive(zip_bytes, None)

        # Simulate a different on-disk state before restoring.
        (app_root / 'terraform' / 'ssh-keys' / 'old_key').unlink()
        (app_root / 'terraform' / 'ssh-keys' / 'unexpected_leftover').write_text('should be gone after restore')

        with app.app_context():
            restore_backup_archive(blob, None)

        assert (app_root / 'configs' / 'presets' / 'custom' / 'server.cfg').read_text() == 'custom preset'
        assert not (app_root / 'terraform' / 'ssh-keys' / 'unexpected_leftover').exists()
        # The app-shipped builtin preset folder must be untouched by the swap.
        assert (app_root / 'configs' / 'presets' / '_builtin' / 'default' / 'server.cfg').exists()

    def test_swapped_out_file_child_is_cleaned_up_after_success(self, app, app_root):
        """terraform/ssh-keys has flat *files* as direct children (unlike
        configs/presets, whose direct children are subdirectories). A
        successful restore must reclaim the swapped-out old file, not
        just a swapped-out old directory."""
        blob = _make_backup_with_host(app, app_root)
        # Not part of the backup being restored, so the swap moves it
        # aside as a *file* rather than restaging it from the archive.
        (app_root / 'terraform' / 'ssh-keys' / 'second_key').write_text('SECOND KEY')

        with app.app_context():
            restore_backup_archive(blob, None)

        leftovers = [
            name for name in os.listdir(app_root / 'terraform')
            if name.startswith('.qlsm-restore-old-')
        ]
        assert leftovers == []

    def test_wrong_password_raises_and_touches_nothing(self, app, app_root):
        blob = _make_backup_with_host(app, app_root, password='correct-pw')
        with app.app_context():
            db.session.query(Host).delete()
            db.session.add(Host(name='untouched', provider='standalone'))
            db.session.commit()

            with pytest.raises(BackupRestoreError):
                restore_backup_archive(blob, 'wrong-pw')

            assert [h.name for h in Host.query.all()] == ['untouched']

    def test_corrupted_archive_raises(self, app, app_root):
        with app.app_context():
            with pytest.raises(BackupRestoreError):
                restore_backup_archive(b'not a real backup', None)

    def test_writes_a_pre_restore_safety_snapshot(self, app, app_root):
        blob = _make_backup_with_host(app, app_root)
        with app.app_context():
            restore_backup_archive(blob, None)
        snapshots = os.listdir(BACKUP_SNAPSHOTS_DIR)
        assert len(snapshots) == 1
        assert snapshots[0].endswith('.qlsmbak')

    def test_rollback_on_db_failure_restores_old_file_trees(self, app, app_root, monkeypatch):
        blob = _make_backup_with_host(app, app_root)
        (app_root / 'terraform' / 'ssh-keys' / 'must_survive_rollback').write_text('x')

        def _boom(_data):
            raise RuntimeError('simulated failure after file swap')

        monkeypatch.setattr('ui.task_logic.backup_import.replace_database', _boom)

        with app.app_context():
            with pytest.raises(RuntimeError):
                restore_backup_archive(blob, None)

        assert (app_root / 'terraform' / 'ssh-keys' / 'must_survive_rollback').exists()

    def test_builtin_presets_are_never_touched(self, app, app_root, monkeypatch):
        """configs/presets/_builtin ships with the app (it's in git, not
        user data) and must survive both a successful restore and a
        rolled-back one untouched — it's never captured in a backup and
        never deleted by one either, even though it's nested two levels
        inside a tree ('configs') that gets wiped and replaced."""
        (app_root / 'configs' / 'presets' / 'custom').mkdir(parents=True)
        (app_root / 'configs' / 'presets' / 'custom' / 'server.cfg').write_text('old custom')
        with app.app_context():
            db.session.add(Host(name='h', provider='vultr'))
            db.session.commit()
            zip_bytes = build_backup_zip_bytes()
        blob = encrypt_archive(zip_bytes, None)

        # Successful restore: _builtin must still be exactly as it was.
        with app.app_context():
            restore_backup_archive(blob, None)
        assert (app_root / 'configs' / 'presets' / '_builtin' / 'default' / 'server.cfg').read_text() == 'shipped with app'

        # A restore that fails after the file swap must also leave
        # _builtin alone, and must roll the custom preset back too.
        (app_root / 'configs' / 'presets' / 'custom' / 'server.cfg').write_text('changed after first restore')

        def _boom(_data):
            raise RuntimeError('simulated failure')

        monkeypatch.setattr('ui.task_logic.backup_import.replace_database', _boom)
        with app.app_context():
            with pytest.raises(RuntimeError):
                restore_backup_archive(blob, None)

        assert (app_root / 'configs' / 'presets' / '_builtin' / 'default' / 'server.cfg').read_text() == 'shipped with app'
        assert (app_root / 'configs' / 'presets' / 'custom' / 'server.cfg').read_text() == 'changed after first restore'
