from unittest.mock import MagicMock, patch

from ui.database import create_host
from ui.models import HostStatus, QLInstance
from tests.helpers import auth_headers


def _payload(host_id, **overrides):
    payload = {
        'name': 'zmq-pwd-instance',
        'host_id': host_id,
        'port': 27960,
        'hostname': 'test.hostname',
        'configs': {
            'server.cfg': '',
            'mappool.txt': '',
            'access.txt': '',
            'workshop.txt': '',
        },
    }
    payload.update(overrides)
    return payload


def _active_host(app, name='zmq-pwd-host'):
    with app.app_context():
        host = create_host(
            name=name,
            provider='standalone',
            status=HostStatus.ACTIVE,
            os_type='debian',
        )
        return host.id


@patch('ui.routes.instance_routes.enqueue_task', return_value=MagicMock(id='job-1'))
@patch('ui.routes.instance_routes.acquire_lock', return_value=True)
def test_omitted_passwords_store_null(mock_lock, mock_enqueue, client, app, tmp_path, monkeypatch):
    """Default behavior: deploy-time generation still owns the passwords."""
    monkeypatch.chdir(tmp_path)
    host_id = _active_host(app)

    response = client.post(
        '/api/instances/', json=_payload(host_id), headers=auth_headers(app, 'testuser')
    )

    assert response.status_code == 201
    with app.app_context():
        instance = QLInstance.query.filter_by(name='zmq-pwd-instance').one()
        assert instance.zmq_stats_password is None
        assert instance.zmq_rcon_password is None


@patch('ui.routes.instance_routes.enqueue_task', return_value=MagicMock(id='job-1'))
@patch('ui.routes.instance_routes.acquire_lock', return_value=True)
def test_manual_passwords_are_stored(mock_lock, mock_enqueue, client, app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host_id = _active_host(app)

    response = client.post(
        '/api/instances/',
        json=_payload(
            host_id,
            zmq_stats_password='Kp3-xR_9vT=2wQ',
            zmq_rcon_password='aB7_zQ2-mN4kLp',
        ),
        headers=auth_headers(app, 'testuser'),
    )

    assert response.status_code == 201
    with app.app_context():
        instance = QLInstance.query.filter_by(name='zmq-pwd-instance').one()
        assert instance.zmq_stats_password == 'Kp3-xR_9vT=2wQ'
        assert instance.zmq_rcon_password == 'aB7_zQ2-mN4kLp'


@patch('ui.routes.instance_routes.enqueue_task', return_value=MagicMock(id='job-1'))
@patch('ui.routes.instance_routes.acquire_lock', return_value=True)
def test_identical_passwords_are_allowed(mock_lock, mock_enqueue, client, app, tmp_path, monkeypatch):
    """Separate sockets; forcing them apart buys nothing."""
    monkeypatch.chdir(tmp_path)
    host_id = _active_host(app)

    response = client.post(
        '/api/instances/',
        json=_payload(host_id, zmq_stats_password='SameValue-01', zmq_rcon_password='SameValue-01'),
        headers=auth_headers(app, 'testuser'),
    )

    assert response.status_code == 201


@patch('ui.routes.instance_routes.enqueue_task')
def test_invalid_charset_is_rejected(mock_enqueue, client, app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host_id = _active_host(app)

    response = client.post(
        '/api/instances/',
        json=_payload(host_id, zmq_stats_password='p@ssw0rd!!', zmq_rcon_password='aB7_zQ2-mN4kLp'),
        headers=auth_headers(app, 'testuser'),
    )

    assert response.status_code == 400
    assert 'ZMQ Stats Password' in response.get_json()['error']['message']
    mock_enqueue.assert_not_called()


@patch('ui.routes.instance_routes.enqueue_task')
def test_too_short_password_is_rejected(mock_enqueue, client, app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host_id = _active_host(app)

    response = client.post(
        '/api/instances/',
        json=_payload(host_id, zmq_stats_password='Kp3-xR_9vT=2wQ', zmq_rcon_password='short1'),
        headers=auth_headers(app, 'testuser'),
    )

    assert response.status_code == 400
    assert 'ZMQ RCON Password' in response.get_json()['error']['message']
    mock_enqueue.assert_not_called()


@patch('ui.routes.instance_routes.enqueue_task')
def test_too_long_password_is_rejected(mock_enqueue, client, app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host_id = _active_host(app)

    response = client.post(
        '/api/instances/',
        json=_payload(host_id, zmq_stats_password='a' * 65, zmq_rcon_password='aB7_zQ2-mN4kLp'),
        headers=auth_headers(app, 'testuser'),
    )

    assert response.status_code == 400
    mock_enqueue.assert_not_called()


@patch('ui.routes.instance_routes.enqueue_task')
def test_only_stats_password_supplied_is_rejected(mock_enqueue, client, app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host_id = _active_host(app)

    response = client.post(
        '/api/instances/',
        json=_payload(host_id, zmq_stats_password='Kp3-xR_9vT=2wQ'),
        headers=auth_headers(app, 'testuser'),
    )

    assert response.status_code == 400
    assert 'ZMQ RCON Password' in response.get_json()['error']['message']
    mock_enqueue.assert_not_called()


@patch('ui.routes.instance_routes.enqueue_task')
def test_only_rcon_password_supplied_is_rejected(mock_enqueue, client, app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host_id = _active_host(app)

    response = client.post(
        '/api/instances/',
        json=_payload(host_id, zmq_rcon_password='aB7_zQ2-mN4kLp'),
        headers=auth_headers(app, 'testuser'),
    )

    assert response.status_code == 400
    assert 'ZMQ Stats Password' in response.get_json()['error']['message']
    mock_enqueue.assert_not_called()


@patch('ui.routes.instance_routes.enqueue_task')
def test_non_string_password_is_rejected(mock_enqueue, client, app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host_id = _active_host(app)

    response = client.post(
        '/api/instances/',
        json=_payload(host_id, zmq_stats_password=12345678, zmq_rcon_password='aB7_zQ2-mN4kLp'),
        headers=auth_headers(app, 'testuser'),
    )

    assert response.status_code == 400
    mock_enqueue.assert_not_called()
