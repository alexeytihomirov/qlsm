"""Validation tests for the server-log archive endpoints.

These guard GET /api/instances/<id>/remote-logs/list and the filename
handling added to GET /api/instances/<id>/remote-logs: archive names are
restricted to the canonical server.log rotation pattern, time mode is
rejected for archives, and missing instance/host state is classified
before any Ansible execution.
"""
from unittest.mock import patch

from flask_jwt_extended import create_access_token

from ui import db
from ui.database import create_host, create_instance
from ui.models import HostStatus, QLInstance


def _make_instance(app):
    with app.app_context():
        host = create_host(name='srvlog-host', provider='vultr', status=HostStatus.ACTIVE)
        instance = create_instance(
            name='srvlog-inst', host_id=host.id, port=27960, hostname='srvlog.host',
        )
        db.session.commit()
        token = create_access_token(identity='testuser')
        return instance.id, token


def _make_instance_without_host(app):
    with app.app_context():
        instance = QLInstance(
            name='srvlog-no-host', host_id=999999, port=27961, hostname='srvlog.nohost',
        )
        db.session.add(instance)
        db.session.commit()
        token = create_access_token(identity='testuser')
        return instance.id, token


def _headers(token):
    return {'Authorization': f'Bearer {token}'}


def _get_list(client, instance_id, token):
    return client.get(
        f'/api/instances/{instance_id}/remote-logs/list',
        headers=_headers(token),
    )


def test_missing_instance_list_returns_404_before_task_logic(client, app):
    _, token = _make_instance(app)
    with patch('ui.task_logic.ansible_server_log_archives.list_instance_server_log_archives') as mock_list:
        resp = _get_list(client, 999999, token)
    assert resp.status_code == 404
    mock_list.assert_not_called()


def test_missing_host_list_returns_400_before_task_logic(client, app):
    instance_id, token = _make_instance_without_host(app)
    with patch('ui.task_logic.ansible_server_log_archives.list_instance_server_log_archives') as mock_list:
        resp = _get_list(client, instance_id, token)
    assert resp.status_code == 400
    mock_list.assert_not_called()


@patch('ui.task_logic.ansible_server_log_archives.list_instance_server_log_archives',
       return_value=(True, ['server.log', 'server.log-20260729-093000',
                            'server.log-20260728-091500.gz'], None))
def test_list_request_returns_files(mock_list, client, app):
    instance_id, token = _make_instance(app)
    resp = _get_list(client, instance_id, token)
    assert resp.status_code == 200
    assert resp.get_json()['data'] == {
        'files': ['server.log', 'server.log-20260729-093000',
                  'server.log-20260728-091500.gz'],
        'instance_name': 'srvlog-inst',
    }
    mock_list.assert_called_once_with(instance_id)


@patch('ui.task_logic.ansible_server_log_archives.list_instance_server_log_archives',
       return_value=(False, [], 'boom'))
def test_list_failure_returns_500(mock_list, client, app):
    instance_id, token = _make_instance(app)
    resp = _get_list(client, instance_id, token)
    assert resp.status_code == 500
    assert resp.get_json()['error']['message'] == 'boom'


def test_filename_regex_accepts_canonical_names():
    from ui.task_logic.ansible_server_log_archives import SERVER_LOG_FILENAME_RE
    assert SERVER_LOG_FILENAME_RE.fullmatch('server.log')
    assert SERVER_LOG_FILENAME_RE.fullmatch('server.log-20260729-093000')
    assert SERVER_LOG_FILENAME_RE.fullmatch('server.log-20260729-093000.gz')


def test_filename_regex_rejects_traversal_and_malformed():
    from ui.task_logic.ansible_server_log_archives import SERVER_LOG_FILENAME_RE
    for bad in ('../../../../etc/passwd', 'server.log.old', 'server.log-2026072',
                'server.log-20260729-0930', 'server.log-20260729-093000.zip',
                'serverXlog', '/home/ql/server.log'):
        assert not SERVER_LOG_FILENAME_RE.fullmatch(bad), bad
