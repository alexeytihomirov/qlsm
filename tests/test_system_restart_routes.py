"""POST /api/system/restart -- who may ask, and where asking is safe at all."""
import os
import tempfile

import pytest

from ui import create_app, db
from tests.helpers import auth_headers, make_user


@pytest.fixture
def ctx(tmp_path):
    stamp = tmp_path / 'data' / '.restart-stamp'

    db_fd, db_path = tempfile.mkstemp()
    app = create_app({
        'TESTING': True, 'SECRET_KEY': 'x', 'JWT_SECRET_KEY': 'x',
        'JWT_COOKIE_CSRF_PROTECT': False, 'JWT_TOKEN_LOCATION': ['headers', 'cookies'],
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'SERVER_NAME': 'test.server', 'RCON_ENABLED': False,
        'RESTART_STAMP_FILE': str(stamp),
    })
    with app.app_context():
        db.create_all()
    make_user(app, 'operator', 'pw')
    headers = auth_headers(app, 'operator')

    yield app, app.test_client(), headers, stamp

    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    os.close(db_fd)
    for path in (db_path, f'{db_path}-wal', f'{db_path}-shm'):
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture
def supervised(monkeypatch):
    """Pretend entrypoint.sh started us, i.e. something will restart the process."""
    monkeypatch.setenv('QLSM_SUPERVISED', '1')


@pytest.fixture
def unsupervised(monkeypatch):
    """A run-dev.sh style launch: killing the process would simply end qlsm."""
    monkeypatch.delenv('QLSM_SUPERVISED', raising=False)


def test_restart_requires_authentication(ctx, supervised):
    _, client, _, stamp = ctx
    response = client.post('/api/system/restart')
    assert response.status_code == 401
    assert not stamp.exists()


def test_system_info_requires_authentication(ctx, supervised):
    _, client, _, _ = ctx
    assert client.get('/api/system/info').status_code == 401


def test_restart_stamps_the_file(ctx, supervised):
    _, client, headers, stamp = ctx
    response = client.post('/api/system/restart', headers=headers)
    assert response.status_code == 202
    assert stamp.exists()


def test_restart_updates_mtime_on_repeat(ctx, supervised):
    """The watcher only ever compares mtimes, so a second request must move it."""
    _, client, headers, stamp = ctx
    assert client.post('/api/system/restart', headers=headers).status_code == 202
    first = stamp.stat().st_mtime_ns
    os.utime(stamp, ns=(first - 5_000_000_000, first - 5_000_000_000))

    assert client.post('/api/system/restart', headers=headers).status_code == 202
    assert stamp.stat().st_mtime_ns > first - 5_000_000_000


def test_restart_refused_without_a_supervisor(ctx, unsupervised):
    _, client, headers, stamp = ctx
    response = client.post('/api/system/restart', headers=headers)
    assert response.status_code == 409
    assert 'supervisor' in response.get_json()['error']['message']
    assert not stamp.exists()


def test_system_info_reports_capability(ctx, monkeypatch):
    _, client, headers, _ = ctx

    monkeypatch.delenv('QLSM_SUPERVISED', raising=False)
    assert client.get('/api/system/info', headers=headers).get_json()['data'] == {
        'restart_supported': False}

    monkeypatch.setenv('QLSM_SUPERVISED', '1')
    assert client.get('/api/system/info', headers=headers).get_json()['data'] == {
        'restart_supported': True}
