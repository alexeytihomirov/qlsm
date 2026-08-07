from unittest.mock import MagicMock, patch

from ui.database import create_host
from ui.models import HostStatus, QLInstance
from tests.helpers import auth_headers


def _payload(host_id, **overrides):
    payload = {
        'name': 'redis-db-instance',
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


def _active_host(app, name='redis-db-host'):
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
def test_omitted_redis_db_stores_null(mock_lock, mock_enqueue, client, app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host_id = _active_host(app)

    response = client.post(
        '/api/instances/', json=_payload(host_id), headers=auth_headers(app, 'testuser')
    )

    assert response.status_code == 201
    with app.app_context():
        assert QLInstance.query.filter_by(name='redis-db-instance').one().redis_db is None


@patch('ui.routes.instance_routes.enqueue_task', return_value=MagicMock(id='job-1'))
@patch('ui.routes.instance_routes.acquire_lock', return_value=True)
def test_explicit_redis_db_is_stored(mock_lock, mock_enqueue, client, app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host_id = _active_host(app)

    response = client.post(
        '/api/instances/',
        json=_payload(host_id, redis_db=5),
        headers=auth_headers(app, 'testuser'),
    )

    assert response.status_code == 201
    with app.app_context():
        assert QLInstance.query.filter_by(name='redis-db-instance').one().redis_db == 5


@patch('ui.routes.instance_routes.enqueue_task')
def test_redis_db_zero_is_rejected(mock_enqueue, client, app, tmp_path, monkeypatch):
    """DB 0 is reserved for QLSM's own state."""
    monkeypatch.chdir(tmp_path)
    host_id = _active_host(app)

    response = client.post(
        '/api/instances/',
        json=_payload(host_id, redis_db=0),
        headers=auth_headers(app, 'testuser'),
    )

    assert response.status_code == 400
    assert 'Redis DB' in response.get_json()['error']['message']
    mock_enqueue.assert_not_called()


@patch('ui.routes.instance_routes.enqueue_task')
def test_redis_db_above_max_is_rejected(mock_enqueue, client, app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host_id = _active_host(app)

    response = client.post(
        '/api/instances/',
        json=_payload(host_id, redis_db=9),
        headers=auth_headers(app, 'testuser'),
    )

    assert response.status_code == 400
    mock_enqueue.assert_not_called()


@patch('ui.routes.instance_routes.enqueue_task')
def test_non_integer_redis_db_is_rejected(mock_enqueue, client, app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host_id = _active_host(app)

    response = client.post(
        '/api/instances/',
        json=_payload(host_id, redis_db='abc'),
        headers=auth_headers(app, 'testuser'),
    )

    assert response.status_code == 400
    mock_enqueue.assert_not_called()


@patch('ui.routes.instance_routes.enqueue_task', return_value=MagicMock(id='job-1'))
@patch('ui.routes.instance_routes.acquire_lock', return_value=True)
def test_duplicate_redis_db_on_same_host_is_allowed(
    mock_lock, mock_enqueue, client, app, tmp_path, monkeypatch
):
    """Sharing a DB is a deliberate choice, not an error."""
    monkeypatch.chdir(tmp_path)
    host_id = _active_host(app)

    first = client.post(
        '/api/instances/',
        json=_payload(host_id, redis_db=3),
        headers=auth_headers(app, 'testuser'),
    )
    assert first.status_code == 201

    second = client.post(
        '/api/instances/',
        json=_payload(host_id, name='second-instance', port=27961, redis_db=3),
        headers=auth_headers(app, 'testuser'),
    )
    assert second.status_code == 201
