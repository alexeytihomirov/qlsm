"""Validation tests for the server-log archive endpoints.

These guard GET /api/instances/<id>/remote-logs/list and the filename
handling added to GET /api/instances/<id>/remote-logs: archive names are
restricted to the canonical server.log rotation pattern, time mode is
rejected for archives, and missing instance/host state is classified
before any Ansible execution.
"""
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

from flask_jwt_extended import create_access_token

from ui import db
from ui.database import create_host, create_instance
from ui.models import HostStatus, QLInstance

FETCH_MODULE = 'ui.task_logic.ansible_server_log_archives'


def _make_instance(app):
    with app.app_context():
        host = create_host(name='srvlog-host', provider='vultr', status=HostStatus.ACTIVE)
        instance = create_instance(
            name='srvlog-inst', host_id=host.id, port=27960, hostname='srvlog.host',
        )
        db.session.commit()
        token = create_access_token(identity='testuser')
        return instance.id, token


def _make_instance_with_host_details(app):
    """A host with full SSH details, so _resolve_instance succeeds and
    fetch_instance_server_log proceeds past validation into the (mocked)
    subprocess path."""
    with app.app_context():
        host = create_host(
            name='srvlog-host-full', provider='vultr', status=HostStatus.ACTIVE,
            ip_address='10.0.0.5', ssh_key_path='/fake/key', ssh_user='ansible',
        )
        instance = create_instance(
            name='srvlog-inst-full', host_id=host.id, port=27970, hostname='srvlog-full.host',
        )
        db.session.commit()
        return instance.id


def _mock_ansible_process(rc=0):
    process = MagicMock()
    process.communicate.return_value = ('', '')
    process.returncode = rc
    return process


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


def test_filename_regex_rejects_injection_even_with_match():
    from ui.task_logic.ansible_server_log_archives import SERVER_LOG_FILENAME_RE
    for payload in ('server.log; rm -rf /', 'server.log/../../etc/passwd',
                    'server.log\n', 'server.log\nrm -rf /'):
        assert not SERVER_LOG_FILENAME_RE.match(payload), payload
        assert not SERVER_LOG_FILENAME_RE.fullmatch(payload), payload


def test_sort_archives_orders_current_first_then_newest_archive_first():
    from ui.task_logic.ansible_server_log_archives import _sort_archives
    files = [
        'server.log-20260727-091500.gz',
        'server.log',
        'server.log-20260729-093000',
        'server.log-20260728-091500.gz',
    ]
    assert _sort_archives(files) == [
        'server.log',
        'server.log-20260729-093000',
        'server.log-20260728-091500.gz',
        'server.log-20260727-091500.gz',
    ]


def _get_logs(client, instance_id, token, **params):
    return client.get(
        f'/api/instances/{instance_id}/remote-logs',
        query_string=params,
        headers=_headers(token),
    )


def test_path_traversal_filename_rejected_before_task_logic(client, app):
    instance_id, token = _make_instance(app)
    with patch('ui.task_logic.ansible_server_log_archives.fetch_instance_server_log') as mock_fetch:
        resp = _get_logs(client, instance_id, token, filter_mode='lines',
                         filename='../../../../etc/passwd')
    assert resp.status_code == 400
    mock_fetch.assert_not_called()


def test_malformed_filename_rejected_before_task_logic(client, app):
    instance_id, token = _make_instance(app)
    with patch('ui.task_logic.ansible_server_log_archives.fetch_instance_server_log') as mock_fetch:
        resp = _get_logs(client, instance_id, token, filter_mode='lines',
                         filename='server.log.old')
    assert resp.status_code == 400
    mock_fetch.assert_not_called()


def test_time_mode_rejected_for_archive_filename(client, app):
    instance_id, token = _make_instance(app)
    with patch('ui.task_logic.ansible_server_log_archives.fetch_instance_server_log') as mock_fetch:
        resp = _get_logs(client, instance_id, token, filter_mode='time',
                         since='1 hour ago', filename='server.log-20260729-093000')
    assert resp.status_code == 400
    mock_fetch.assert_not_called()


@patch('ui.task_logic.ansible_server_log_archives.fetch_instance_server_log',
       return_value=(True, 'archived line', None))
def test_archive_lines_request_routed_to_archive_fetcher(mock_fetch, client, app):
    instance_id, token = _make_instance(app)
    resp = _get_logs(client, instance_id, token, filter_mode='lines', lines=250,
                     filename='server.log-20260729-093000.gz')
    assert resp.status_code == 200
    assert resp.get_json()['data']['logs'] == 'archived line'
    assert mock_fetch.call_args.kwargs['filename'] == 'server.log-20260729-093000.gz'
    assert mock_fetch.call_args.kwargs['lines'] == 250


@patch('ui.task_logic.ansible_server_log_archives.fetch_instance_server_log',
       return_value=(True, 'everything', None))
def test_all_mode_reads_current_file_not_journald(mock_fetch, client, app):
    instance_id, token = _make_instance(app)
    resp = _get_logs(client, instance_id, token, filter_mode='all')
    assert resp.status_code == 200
    assert resp.get_json()['data']['logs'] == 'everything'
    assert mock_fetch.call_args.kwargs['filename'] == 'server.log'
    assert mock_fetch.call_args.kwargs['filter_mode'] == 'all'


@patch('ui.task_logic.ansible_instance_mgmt.fetch_instance_remote_logs',
       return_value=(True, 'journald window', None))
def test_time_mode_on_current_still_uses_journald(mock_fetch, client, app):
    instance_id, token = _make_instance(app)
    resp = _get_logs(client, instance_id, token, filter_mode='time', since='1 hour ago')
    assert resp.status_code == 200
    assert resp.get_json()['data']['logs'] == 'journald window'
    mock_fetch.assert_called_once()


def test_lines_out_of_range_rejected_before_task_logic(client, app):
    instance_id, token = _make_instance(app)
    with patch('ui.task_logic.ansible_server_log_archives.fetch_instance_server_log') as mock_fetch:
        assert _get_logs(client, instance_id, token, filter_mode='lines', lines=9).status_code == 400
        assert _get_logs(client, instance_id, token, filter_mode='lines', lines=10001).status_code == 400
    mock_fetch.assert_not_called()


# Direct coverage of fetch_instance_server_log itself, rather than through the
# route with the function mocked out. The four guard clauses below return
# before ever constructing an ansible-playbook command, so they need no
# subprocess mocking. The three "resolved" tests below them do need it, since
# they exercise the local-temp-file read path past _resolve_instance.


def test_fetch_rejects_invalid_filename_without_touching_subprocess():
    from ui.task_logic.ansible_server_log_archives import fetch_instance_server_log
    with patch(f'{FETCH_MODULE}.subprocess.Popen') as mock_popen:
        success, logs, error = fetch_instance_server_log(1, filename='../../../etc/passwd')
    assert success is False
    assert error == "Invalid server log filename."
    mock_popen.assert_not_called()


def test_fetch_rejects_invalid_filter_mode_without_touching_subprocess():
    from ui.task_logic.ansible_server_log_archives import fetch_instance_server_log
    with patch(f'{FETCH_MODULE}.subprocess.Popen') as mock_popen:
        success, logs, error = fetch_instance_server_log(1, filter_mode='time')
    assert success is False
    assert error == "filter_mode must be 'lines' or 'all'"
    mock_popen.assert_not_called()


def test_fetch_rejects_non_integer_lines_without_touching_subprocess():
    from ui.task_logic.ansible_server_log_archives import fetch_instance_server_log
    with patch(f'{FETCH_MODULE}.subprocess.Popen') as mock_popen:
        success, logs, error = fetch_instance_server_log(1, lines='500')
    assert success is False
    assert error == "lines must be an integer"
    mock_popen.assert_not_called()


def test_fetch_rejects_out_of_range_lines_without_touching_subprocess():
    from ui.task_logic.ansible_server_log_archives import fetch_instance_server_log
    with patch(f'{FETCH_MODULE}.subprocess.Popen') as mock_popen:
        assert fetch_instance_server_log(1, lines=9)[0] is False
        assert fetch_instance_server_log(1, lines=10001)[0] is False
    mock_popen.assert_not_called()


def test_fetch_returns_not_found_message_when_temp_file_absent(app):
    instance_id = _make_instance_with_host_details(app)
    from ui.task_logic.ansible_server_log_archives import fetch_instance_server_log

    real_dir = tempfile.mkdtemp(prefix='qlsm-serverlog-test-')
    try:
        with app.app_context(), \
             patch(f'{FETCH_MODULE}.subprocess.Popen', return_value=_mock_ansible_process()), \
             patch('tempfile.mkdtemp', return_value=real_dir), \
             patch('shutil.rmtree'):
            success, logs, error = fetch_instance_server_log(instance_id)
    finally:
        shutil.rmtree(real_dir, ignore_errors=True)

    assert success is True
    assert logs == "-- Server log file not found --"
    assert error is None


def test_fetch_returns_no_entries_message_when_file_is_empty(app):
    instance_id = _make_instance_with_host_details(app)
    from ui.task_logic.ansible_server_log_archives import fetch_instance_server_log

    real_dir = tempfile.mkdtemp(prefix='qlsm-serverlog-test-')
    with open(os.path.join(real_dir, 'server-log.txt'), 'w') as fh:
        fh.write('   \n')
    try:
        with app.app_context(), \
             patch(f'{FETCH_MODULE}.subprocess.Popen', return_value=_mock_ansible_process()), \
             patch('tempfile.mkdtemp', return_value=real_dir), \
             patch('shutil.rmtree'):
            success, logs, error = fetch_instance_server_log(instance_id)
    finally:
        shutil.rmtree(real_dir, ignore_errors=True)

    assert success is True
    assert logs == "-- No entries --"
    assert error is None


def test_fetch_returns_file_contents_when_present(app):
    instance_id = _make_instance_with_host_details(app)
    from ui.task_logic.ansible_server_log_archives import fetch_instance_server_log

    real_dir = tempfile.mkdtemp(prefix='qlsm-serverlog-test-')
    with open(os.path.join(real_dir, 'server-log.txt'), 'w') as fh:
        fh.write('line one\nline two\n')
    try:
        with app.app_context(), \
             patch(f'{FETCH_MODULE}.subprocess.Popen', return_value=_mock_ansible_process()), \
             patch('tempfile.mkdtemp', return_value=real_dir), \
             patch('shutil.rmtree'):
            success, logs, error = fetch_instance_server_log(instance_id, filter_mode='all')
    finally:
        shutil.rmtree(real_dir, ignore_errors=True)

    assert success is True
    assert logs == 'line one\nline two\n'
    assert error is None


def test_fetch_surfaces_nonzero_rc_as_error_not_fake_success(app):
    instance_id = _make_instance_with_host_details(app)
    from ui.task_logic.ansible_server_log_archives import fetch_instance_server_log

    with app.app_context(), \
         patch(f'{FETCH_MODULE}.subprocess.Popen', return_value=_mock_ansible_process(rc=2)):
        success, logs, error = fetch_instance_server_log(instance_id)

    assert success is False
    assert 'RC: 2' in error
