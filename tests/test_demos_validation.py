"""Validation tests for the demo-listing and demo-download endpoints.

Guards GET /api/instances/<id>/demos: missing instance/host state is
classified before any SFTP session is opened, a successful list is returned
sorted newest-first, and a missing demos/ directory degrades to an empty
list rather than a 500. Also guards GET .../demos/download and
POST .../demos/download-batch: filename validation happens before any SFTP
session is opened, and a missing file is a 404, not a 500.
"""
import io
import stat
import zipfile
from unittest.mock import MagicMock, patch

import paramiko
from flask_jwt_extended import create_access_token

from ui import db
from ui.database import create_host, create_instance
from ui.models import HostStatus, QLInstance

FETCH_MODULE = 'ui.task_logic.ansible_instance_demos'


def _make_instance(app):
    with app.app_context():
        host = create_host(name='demo-host', provider='vultr', status=HostStatus.ACTIVE)
        instance = create_instance(
            name='demo-inst', host_id=host.id, port=27960, hostname='demo.host',
        )
        db.session.commit()
        token = create_access_token(identity='testuser')
        return instance.id, token


def _make_instance_without_host(app):
    with app.app_context():
        instance = QLInstance(
            name='demo-no-host', host_id=999999, port=27961, hostname='demo.nohost',
        )
        db.session.add(instance)
        db.session.commit()
        token = create_access_token(identity='testuser')
        return instance.id, token


def _headers(token):
    return {'Authorization': f'Bearer {token}'}


def _get_demos(client, instance_id, token):
    return client.get(f'/api/instances/{instance_id}/demos', headers=_headers(token))


def _fake_host():
    return MagicMock(
        name='demo-host', ssh_key_path='/fake/key', ssh_user='ansible',
        ssh_port=22, ip_address='10.0.0.1', provider='vultr',
    )


def _attr(name, size, mtime, is_dir=False):
    entry = paramiko.SFTPAttributes()
    entry.filename = name
    entry.st_size = size
    entry.st_mtime = mtime
    entry.st_mode = (stat.S_IFDIR if is_dir else stat.S_IFREG) | 0o644
    return entry


def _mock_ssh_client(sftp):
    client = MagicMock()
    client.open_sftp.return_value = sftp
    return client


def test_missing_instance_returns_404_before_task_logic(client, app):
    _, token = _make_instance(app)
    with patch(f'{FETCH_MODULE}.list_instance_demos') as mock_list:
        resp = _get_demos(client, 999999, token)
    assert resp.status_code == 404
    mock_list.assert_not_called()


def test_missing_host_returns_400_before_task_logic(client, app):
    instance_id, token = _make_instance_without_host(app)
    with patch(f'{FETCH_MODULE}.list_instance_demos') as mock_list:
        resp = _get_demos(client, instance_id, token)
    assert resp.status_code == 400
    mock_list.assert_not_called()


@patch(f'{FETCH_MODULE}.list_instance_demos',
       return_value=(True, [{'name': 'a.dm_91', 'size': 100, 'mtime': 1.0}], None))
def test_list_request_returns_demos(mock_list, client, app):
    instance_id, token = _make_instance(app)
    resp = _get_demos(client, instance_id, token)
    assert resp.status_code == 200
    assert resp.get_json()['data'] == {
        'demos': [{'name': 'a.dm_91', 'size': 100, 'mtime': 1.0}],
        'instance_name': 'demo-inst',
    }
    mock_list.assert_called_once_with(instance_id)


@patch(f'{FETCH_MODULE}.list_instance_demos', return_value=(False, [], 'boom'))
def test_list_failure_returns_500(mock_list, client, app):
    instance_id, token = _make_instance(app)
    resp = _get_demos(client, instance_id, token)
    assert resp.status_code == 500
    assert resp.get_json()['error']['message'] == 'boom'


def test_list_unexpected_exception_returns_generic_error():
    from ui.task_logic.ansible_instance_demos import list_instance_demos
    with patch(f'{FETCH_MODULE}._resolve_instance', side_effect=RuntimeError('boom')):
        success, demos, error = list_instance_demos(1)
    assert success is False
    assert demos == []
    assert error == "Failed to list demos."


def test_list_missing_directory_returns_empty_list_not_error():
    from ui.task_logic.ansible_instance_demos import list_instance_demos

    sftp = MagicMock()
    sftp.listdir_attr.side_effect = FileNotFoundError()

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), _fake_host(), None)), \
         patch(f'{FETCH_MODULE}.paramiko.SSHClient', return_value=_mock_ssh_client(sftp)):
        success, demos, error = list_instance_demos(1)

    assert success is True
    assert demos == []
    assert error is None


def test_list_sorts_newest_first_and_drops_malformed_entries():
    from ui.task_logic.ansible_instance_demos import list_instance_demos

    sftp = MagicMock()
    sftp.listdir_attr.return_value = [
        _attr('old.dm_91', 10, 1.0),
        _attr('new.dm_91', 20, 2.0),
        _attr('some-dir', 0, 3.0, is_dir=True),
        _attr('not-a-demo.txt', 5, 4.0),
    ]

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), _fake_host(), None)), \
         patch(f'{FETCH_MODULE}.paramiko.SSHClient', return_value=_mock_ssh_client(sftp)):
        success, demos, error = list_instance_demos(1)

    assert success is True
    assert error is None
    assert [d['name'] for d in demos] == ['new.dm_91', 'old.dm_91']


def test_list_keeps_qlmatch_and_replay_sidecar_entries_alongside_dm91():
    # native-demo's build_match_package() ships "{match_id}_{map}.qlmatch"
    # next to the per-POV .dm_91 files, and qlmatch-packer additionally
    # drops "{match_id}_{map}.replay.json.gz" in the same demos/ directory -
    # the listing must not drop either.
    from ui.task_logic.ansible_instance_demos import list_instance_demos

    sftp = MagicMock()
    sftp.listdir_attr.return_value = [
        _attr('20260827T170920Z_phrantic_p0_a3_1_1.dm_91', 10, 1.0),
        _attr('20260827T170920Z_phrantic.qlmatch', 20, 2.0),
        _attr('20260827T170920Z_phrantic.replay.json.gz', 30, 3.0),
    ]

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), _fake_host(), None)), \
         patch(f'{FETCH_MODULE}.paramiko.SSHClient', return_value=_mock_ssh_client(sftp)):
        success, demos, error = list_instance_demos(1)

    assert success is True
    assert error is None
    assert [d['name'] for d in demos] == [
        '20260827T170920Z_phrantic.replay.json.gz',
        '20260827T170920Z_phrantic.qlmatch',
        '20260827T170920Z_phrantic_p0_a3_1_1.dm_91',
    ]


def test_list_ssh_failure_returns_error_not_exception():
    from ui.task_logic.ansible_instance_demos import list_instance_demos

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), _fake_host(), None)), \
         patch(f'{FETCH_MODULE}.paramiko.SSHClient') as mock_cls:
        mock_cls.return_value.connect.side_effect = paramiko.SSHException('unreachable')
        success, demos, error = list_instance_demos(1)

    assert success is False
    assert demos == []
    assert error == "Failed to list demos from remote host."


def _get_download(client, instance_id, token, filename):
    return client.get(
        f'/api/instances/{instance_id}/demos/download',
        query_string={'filename': filename},
        headers=_headers(token),
    )


def _post_batch(client, instance_id, token, filenames):
    return client.post(
        f'/api/instances/{instance_id}/demos/download-batch',
        json={'filenames': filenames},
        headers=_headers(token),
    )


def test_download_missing_instance_returns_404_before_task_logic(client, app):
    _, token = _make_instance(app)
    with patch(f'{FETCH_MODULE}.fetch_instance_demos') as mock_fetch:
        resp = _get_download(client, 999999, token, 'a.dm_91')
    assert resp.status_code == 404
    mock_fetch.assert_not_called()


def test_download_missing_host_returns_400_before_task_logic(client, app):
    instance_id, token = _make_instance_without_host(app)
    with patch(f'{FETCH_MODULE}.fetch_instance_demos') as mock_fetch:
        resp = _get_download(client, instance_id, token, 'a.dm_91')
    assert resp.status_code == 400
    mock_fetch.assert_not_called()


@patch(f'{FETCH_MODULE}.fetch_instance_demos', return_value=(True, {'a.dm_91': b'demo-bytes'}, [], None))
def test_download_returns_file_bytes(mock_fetch, client, app):
    instance_id, token = _make_instance(app)
    resp = _get_download(client, instance_id, token, 'a.dm_91')
    assert resp.status_code == 200
    assert resp.data == b'demo-bytes'
    assert resp.mimetype == 'application/octet-stream'
    mock_fetch.assert_called_once_with(instance_id, ['a.dm_91'])


@patch(f'{FETCH_MODULE}.fetch_instance_demos', return_value=(True, {}, ['a.dm_91'], None))
def test_download_missing_file_returns_404(mock_fetch, client, app):
    instance_id, token = _make_instance(app)
    resp = _get_download(client, instance_id, token, 'a.dm_91')
    assert resp.status_code == 404


@patch(f'{FETCH_MODULE}.fetch_instance_demos', return_value=(False, {}, [], 'boom'))
def test_download_failure_returns_500(mock_fetch, client, app):
    instance_id, token = _make_instance(app)
    resp = _get_download(client, instance_id, token, 'a.dm_91')
    assert resp.status_code == 500
    assert resp.get_json()['error']['message'] == 'boom'


def test_batch_missing_instance_returns_404_before_task_logic(client, app):
    _, token = _make_instance(app)
    with patch(f'{FETCH_MODULE}.fetch_instance_demos') as mock_fetch:
        resp = _post_batch(client, 999999, token, ['a.dm_91'])
    assert resp.status_code == 404
    mock_fetch.assert_not_called()


def test_batch_missing_host_returns_400_before_task_logic(client, app):
    instance_id, token = _make_instance_without_host(app)
    with patch(f'{FETCH_MODULE}.fetch_instance_demos') as mock_fetch:
        resp = _post_batch(client, instance_id, token, ['a.dm_91'])
    assert resp.status_code == 400
    mock_fetch.assert_not_called()


def test_batch_empty_filenames_rejected_before_task_logic(client, app):
    instance_id, token = _make_instance(app)
    with patch(f'{FETCH_MODULE}.fetch_instance_demos') as mock_fetch:
        resp = _post_batch(client, instance_id, token, [])
    assert resp.status_code == 400
    mock_fetch.assert_not_called()


@patch(f'{FETCH_MODULE}.fetch_instance_demos',
       return_value=(True, {'a.dm_91': b'AAA', 'b.dm_91': b'BBB'}, [], None))
def test_batch_returns_zip_with_requested_files(mock_fetch, client, app):
    instance_id, token = _make_instance(app)
    resp = _post_batch(client, instance_id, token, ['a.dm_91', 'b.dm_91'])
    assert resp.status_code == 200
    assert resp.mimetype == 'application/zip'

    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        assert sorted(zf.namelist()) == ['a.dm_91', 'b.dm_91']
        assert zf.read('a.dm_91') == b'AAA'
        assert zf.read('b.dm_91') == b'BBB'

    mock_fetch.assert_called_once_with(instance_id, ['a.dm_91', 'b.dm_91'])


@patch(f'{FETCH_MODULE}.fetch_instance_demos', return_value=(True, {}, ['a.dm_91'], None))
def test_batch_none_found_returns_404(mock_fetch, client, app):
    instance_id, token = _make_instance(app)
    resp = _post_batch(client, instance_id, token, ['a.dm_91'])
    assert resp.status_code == 404


@patch(f'{FETCH_MODULE}.fetch_instance_demos', return_value=(False, {}, [], 'boom'))
def test_batch_failure_returns_500(mock_fetch, client, app):
    instance_id, token = _make_instance(app)
    resp = _post_batch(client, instance_id, token, ['a.dm_91'])
    assert resp.status_code == 500
    assert resp.get_json()['error']['message'] == 'boom'


# Direct coverage of fetch_instance_demos itself: filename validation must
# reject before ever opening an SFTP session.


def test_fetch_rejects_empty_filenames_without_touching_ssh():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos
    with patch(f'{FETCH_MODULE}.paramiko.SSHClient') as mock_cls:
        success, files, missing, error = fetch_instance_demos(1, [])
    assert success is False
    assert files == {}
    assert 'non-empty list' in error
    mock_cls.assert_not_called()


def test_fetch_rejects_invalid_filename_without_touching_ssh():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos
    with patch(f'{FETCH_MODULE}.paramiko.SSHClient') as mock_cls:
        success, files, missing, error = fetch_instance_demos(1, ['../../../etc/passwd'])
    assert success is False
    assert files == {}
    assert 'Invalid demo filename' in error
    mock_cls.assert_not_called()


def test_fetch_rejects_non_demo_extension_without_touching_ssh():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos
    with patch(f'{FETCH_MODULE}.paramiko.SSHClient') as mock_cls:
        success, files, missing, error = fetch_instance_demos(1, ['a.zip'])
    assert success is False
    assert files == {}
    assert 'Invalid demo filename' in error
    mock_cls.assert_not_called()


def test_fetch_accepts_qlmatch_filename():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos

    sftp = MagicMock()
    sftp.open.return_value.__enter__.return_value.read.return_value = b'zip-bytes'

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), _fake_host(), None)), \
         patch(f'{FETCH_MODULE}.paramiko.SSHClient', return_value=_mock_ssh_client(sftp)):
        success, files, missing, error = fetch_instance_demos(1, ['match.qlmatch'])

    assert success is True
    assert error is None
    assert files == {'match.qlmatch': b'zip-bytes'}
    assert missing == []


def test_fetch_accepts_replay_sidecar_filename():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos

    sftp = MagicMock()
    sftp.open.return_value.__enter__.return_value.read.return_value = b'gz-bytes'

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), _fake_host(), None)), \
         patch(f'{FETCH_MODULE}.paramiko.SSHClient', return_value=_mock_ssh_client(sftp)):
        success, files, missing, error = fetch_instance_demos(1, ['match_map.replay.json.gz'])

    assert success is True
    assert error is None
    assert files == {'match_map.replay.json.gz': b'gz-bytes'}
    assert missing == []


def test_fetch_rejects_batch_over_limit_without_touching_ssh():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos, MAX_DEMO_BATCH
    with patch(f'{FETCH_MODULE}.paramiko.SSHClient') as mock_cls:
        success, files, missing, error = fetch_instance_demos(
            1, [f'{i}.dm_91' for i in range(MAX_DEMO_BATCH + 1)])
    assert success is False
    assert files == {}
    assert 'Cannot fetch more than' in error
    mock_cls.assert_not_called()


def test_fetch_dedupes_filenames_before_running_sftp():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos

    sftp = MagicMock()
    sftp.open.return_value.__enter__.return_value.read.return_value = b'hello'

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), _fake_host(), None)), \
         patch(f'{FETCH_MODULE}.paramiko.SSHClient', return_value=_mock_ssh_client(sftp)):
        success, files, missing, error = fetch_instance_demos(1, ['a.dm_91', 'a.dm_91'])

    assert success is True
    assert error is None
    assert files == {'a.dm_91': b'hello'}
    assert missing == []
    sftp.open.assert_called_once()


def test_fetch_returns_bytes_for_found_files_and_lists_missing():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos

    def fake_open(path, mode):
        cm = MagicMock()
        if path.endswith('a.dm_91'):
            cm.__enter__.return_value.read.return_value = b'hello'
        else:
            raise FileNotFoundError()
        return cm

    sftp = MagicMock()
    sftp.open.side_effect = fake_open

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), _fake_host(), None)), \
         patch(f'{FETCH_MODULE}.paramiko.SSHClient', return_value=_mock_ssh_client(sftp)):
        success, files, missing, error = fetch_instance_demos(1, ['a.dm_91', 'b.dm_91'])

    assert success is True
    assert error is None
    assert files == {'a.dm_91': b'hello'}
    assert missing == ['b.dm_91']


def test_fetch_ssh_failure_returns_error_not_exception():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), _fake_host(), None)), \
         patch(f'{FETCH_MODULE}.paramiko.SSHClient') as mock_cls:
        mock_cls.return_value.connect.side_effect = paramiko.AuthenticationException('nope')
        success, files, missing, error = fetch_instance_demos(1, ['a.dm_91'])

    assert success is False
    assert files == {}
    assert error == "Failed to fetch demos from remote host."


# --- read_qlmatch_manifest / qlmatch_sidecar_name ---
#
# A pack's own filename does not reliably encode match_id/map (the
# qlx_qlmatchNameTemplate cvar can template it to include other fields), so
# has_replay/replay_name for the external API must come from the pack's own
# manifest.json rather than from string-editing the .qlmatch filename.


def test_qlmatch_sidecar_name_matches_restore_qlmatch_formula():
    from ui.task_logic.ansible_instance_demos import qlmatch_sidecar_name
    assert qlmatch_sidecar_name('20260827T170920Z', 'phrantic') == \
        '20260827T170920Z_phrantic.replay.json.gz'


def _fake_qlmatch_zip(manifest):
    import json as _json
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as zf:
        zf.writestr('manifest.json', _json.dumps(manifest))
    buf.seek(0)
    return buf


def test_manifest_rejects_non_qlmatch_filename_without_touching_ssh():
    from ui.task_logic.ansible_instance_demos import read_qlmatch_manifest
    with patch(f'{FETCH_MODULE}.paramiko.SSHClient') as mock_cls:
        success, manifest, error = read_qlmatch_manifest(1, 'a.dm_91')
    assert success is False
    assert manifest is None
    assert 'Invalid qlmatch filename' in error
    mock_cls.assert_not_called()


def test_manifest_rejects_path_traversal_without_touching_ssh():
    from ui.task_logic.ansible_instance_demos import read_qlmatch_manifest
    with patch(f'{FETCH_MODULE}.paramiko.SSHClient') as mock_cls:
        success, manifest, error = read_qlmatch_manifest(1, '../../etc/passwd.qlmatch')
    assert success is False
    assert manifest is None
    mock_cls.assert_not_called()


def test_manifest_reads_match_id_and_map_from_zip_via_seekable_sftp_handle():
    from ui.task_logic.ansible_instance_demos import read_qlmatch_manifest

    zip_bytes = _fake_qlmatch_zip({'match_id': '20260902T210633Z', 'map': 'phrantic'})
    sftp = MagicMock()
    sftp.open.return_value.__enter__.return_value = zip_bytes

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), _fake_host(), None)), \
         patch(f'{FETCH_MODULE}.paramiko.SSHClient', return_value=_mock_ssh_client(sftp)):
        success, manifest, error = read_qlmatch_manifest(1, 'duel_phrantic_Input-a3.qlmatch')

    assert success is True
    assert error is None
    assert manifest == {'match_id': '20260902T210633Z', 'map': 'phrantic'}


def test_manifest_missing_file_returns_error_not_exception():
    from ui.task_logic.ansible_instance_demos import read_qlmatch_manifest

    sftp = MagicMock()
    sftp.open.side_effect = FileNotFoundError()

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), _fake_host(), None)), \
         patch(f'{FETCH_MODULE}.paramiko.SSHClient', return_value=_mock_ssh_client(sftp)):
        success, manifest, error = read_qlmatch_manifest(1, 'a.qlmatch')

    assert success is False
    assert manifest is None
    assert 'not found' in error.lower()


def test_manifest_bad_zip_returns_error_not_exception():
    from ui.task_logic.ansible_instance_demos import read_qlmatch_manifest

    sftp = MagicMock()
    sftp.open.return_value.__enter__.return_value = io.BytesIO(b'not a zip file')

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), _fake_host(), None)), \
         patch(f'{FETCH_MODULE}.paramiko.SSHClient', return_value=_mock_ssh_client(sftp)):
        success, manifest, error = read_qlmatch_manifest(1, 'a.qlmatch')

    assert success is False
    assert manifest is None


def test_manifest_missing_match_id_or_map_returns_error():
    from ui.task_logic.ansible_instance_demos import read_qlmatch_manifest

    zip_bytes = _fake_qlmatch_zip({'match_id': '20260902T210633Z'})  # no "map"
    sftp = MagicMock()
    sftp.open.return_value.__enter__.return_value = zip_bytes

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), _fake_host(), None)), \
         patch(f'{FETCH_MODULE}.paramiko.SSHClient', return_value=_mock_ssh_client(sftp)):
        success, manifest, error = read_qlmatch_manifest(1, 'a.qlmatch')

    assert success is False
    assert manifest is None
    assert 'match_id or map' in error
