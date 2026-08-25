"""Validation tests for the demo-listing endpoint.

Guards GET /api/instances/<id>/demos: missing instance/host state is
classified before any Ansible execution, a successful list is returned
sorted newest-first, and malformed ansible output degrades to an empty list
rather than a 500.
"""
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
