"""Validation tests for the demo-listing and demo-download endpoints.

Guards GET /api/instances/<id>/demos: missing instance/host state is
classified before any Ansible execution, a successful list is returned
sorted newest-first, and malformed ansible output degrades to an empty list
rather than a 500. Also guards GET .../demos/download and
POST .../demos/download-batch: filename validation happens before any
Ansible execution, and a missing file is a 404, not a 500.
"""
import io
import json
import os
import zipfile
from unittest.mock import MagicMock, patch

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
    with patch(f'{FETCH_MODULE}._resolve_instance', side_effect=OSError('boom')):
        success, demos, error = list_instance_demos(1)
    assert success is False
    assert demos == []
    assert error == "Failed to list demos."


def test_list_sorts_newest_first_and_drops_malformed_entries():
    from ui.task_logic.ansible_instance_demos import list_instance_demos

    process = MagicMock()
    process.communicate.return_value = (
        'ok: [host] => {\n    "msg": '
        '"[{\\"name\\": \\"old.dm_91\\", \\"size\\": 10, \\"mtime\\": 1.0}, '
        '{\\"name\\": \\"new.dm_91\\", \\"size\\": 20, \\"mtime\\": 2.0}, '
        '\\"not-a-dict\\"]"\n}\n',
        '',
    )
    process.returncode = 0

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), MagicMock(
                   ssh_key_path='/fake/key', ssh_user='ansible', ip_address='10.0.0.1'), None)), \
         patch(f'{FETCH_MODULE}.subprocess.Popen', return_value=process):
        success, demos, error = list_instance_demos(1)

    assert success is True
    assert error is None
    assert [d['name'] for d in demos] == ['new.dm_91', 'old.dm_91']


def test_list_keeps_qlmatch_entries_alongside_dm91():
    # native-demo's build_match_package() ships "{match_id}_{map}.qlmatch"
    # next to the per-POV .dm_91 files in the same demos/ directory - the
    # listing must not drop it.
    from ui.task_logic.ansible_instance_demos import list_instance_demos

    process = MagicMock()
    process.communicate.return_value = (
        'ok: [host] => {\n    "msg": '
        '"[{\\"name\\": \\"20260827T170920Z_phrantic_p0_a3_1_1.dm_91\\", '
        '\\"size\\": 10, \\"mtime\\": 1.0}, '
        '{\\"name\\": \\"20260827T170920Z_phrantic.qlmatch\\", '
        '\\"size\\": 20, \\"mtime\\": 2.0}]"\n}\n',
        '',
    )
    process.returncode = 0

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), MagicMock(
                   ssh_key_path='/fake/key', ssh_user='ansible', ip_address='10.0.0.1'), None)), \
         patch(f'{FETCH_MODULE}.subprocess.Popen', return_value=process):
        success, demos, error = list_instance_demos(1)

    assert success is True
    assert error is None
    assert [d['name'] for d in demos] == [
        '20260827T170920Z_phrantic.qlmatch',
        '20260827T170920Z_phrantic_p0_a3_1_1.dm_91',
    ]


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
# reject before ever constructing an ansible-playbook command.


def test_fetch_rejects_empty_filenames_without_touching_subprocess():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos
    with patch(f'{FETCH_MODULE}.subprocess.Popen') as mock_popen:
        success, files, missing, error = fetch_instance_demos(1, [])
    assert success is False
    assert files == {}
    assert 'non-empty list' in error
    mock_popen.assert_not_called()


def test_fetch_rejects_invalid_filename_without_touching_subprocess():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos
    with patch(f'{FETCH_MODULE}.subprocess.Popen') as mock_popen:
        success, files, missing, error = fetch_instance_demos(1, ['../../../etc/passwd'])
    assert success is False
    assert files == {}
    assert 'Invalid demo filename' in error
    mock_popen.assert_not_called()


def test_fetch_rejects_non_demo_extension_without_touching_subprocess():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos
    with patch(f'{FETCH_MODULE}.subprocess.Popen') as mock_popen:
        success, files, missing, error = fetch_instance_demos(1, ['a.zip'])
    assert success is False
    assert files == {}
    assert 'Invalid demo filename' in error
    mock_popen.assert_not_called()


def test_fetch_accepts_qlmatch_filename():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos

    process = MagicMock()
    process.communicate.return_value = ('', '')
    process.returncode = 0

    def fake_popen(cmd, **kwargs):
        extravars_json = cmd[cmd.index('-e') + 1]
        extravars = json.loads(extravars_json)
        local_dir = extravars['local_dir']
        with open(os.path.join(local_dir, 'match.qlmatch'), 'wb') as fh:
            fh.write(b'zip-bytes')
        return process

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), MagicMock(
                   ssh_key_path='/fake/key', ssh_user='ansible', ip_address='10.0.0.1'), None)), \
         patch(f'{FETCH_MODULE}.subprocess.Popen', side_effect=fake_popen):
        success, files, missing, error = fetch_instance_demos(1, ['match.qlmatch'])

    assert success is True
    assert error is None
    assert files == {'match.qlmatch': b'zip-bytes'}
    assert missing == []


def test_fetch_rejects_batch_over_limit_without_touching_subprocess():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos, MAX_DEMO_BATCH
    with patch(f'{FETCH_MODULE}.subprocess.Popen') as mock_popen:
        success, files, missing, error = fetch_instance_demos(
            1, [f'{i}.dm_91' for i in range(MAX_DEMO_BATCH + 1)])
    assert success is False
    assert files == {}
    assert 'Cannot fetch more than' in error
    mock_popen.assert_not_called()


def test_fetch_dedupes_filenames_before_running_ansible():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos

    process = MagicMock()
    process.communicate.return_value = ('', '')
    process.returncode = 0

    captured = {}

    def fake_popen(cmd, **kwargs):
        captured['cmd'] = cmd
        return process

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), MagicMock(
                   ssh_key_path='/fake/key', ssh_user='ansible', ip_address='10.0.0.1'), None)), \
         patch(f'{FETCH_MODULE}.subprocess.Popen', side_effect=fake_popen):
        success, files, missing, error = fetch_instance_demos(1, ['a.dm_91', 'a.dm_91'])

    assert success is True
    assert error is None
    assert missing == ['a.dm_91']  # nothing was actually written to local_dir by the mock
    extravars_json = captured['cmd'][captured['cmd'].index('-e') + 1]
    assert '"a.dm_91"' in extravars_json
    assert extravars_json.count('a.dm_91') == 1


def test_fetch_returns_bytes_for_found_files_and_lists_missing():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos

    process = MagicMock()
    process.communicate.return_value = ('', '')
    process.returncode = 0

    def fake_popen(cmd, **kwargs):
        extravars_json = cmd[cmd.index('-e') + 1]
        extravars = json.loads(extravars_json)
        local_dir = extravars['local_dir']
        with open(os.path.join(local_dir, 'a.dm_91'), 'wb') as fh:
            fh.write(b'hello')
        return process

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), MagicMock(
                   ssh_key_path='/fake/key', ssh_user='ansible', ip_address='10.0.0.1'), None)), \
         patch(f'{FETCH_MODULE}.subprocess.Popen', side_effect=fake_popen):
        success, files, missing, error = fetch_instance_demos(1, ['a.dm_91', 'b.dm_91'])

    assert success is True
    assert error is None
    assert files == {'a.dm_91': b'hello'}
    assert missing == ['b.dm_91']


def test_fetch_surfaces_nonzero_rc_as_error_not_fake_success():
    from ui.task_logic.ansible_instance_demos import fetch_instance_demos

    process = MagicMock()
    process.communicate.return_value = ('', 'boom stderr')
    process.returncode = 2

    with patch(f'{FETCH_MODULE}._resolve_instance',
               return_value=(MagicMock(port=27960), MagicMock(
                   ssh_key_path='/fake/key', ssh_user='ansible', ip_address='10.0.0.1'), None)), \
         patch(f'{FETCH_MODULE}.subprocess.Popen', return_value=process):
        success, files, missing, error = fetch_instance_demos(1, ['a.dm_91'])

    assert success is False
    assert 'RC: 2' in error
