"""Install / uninstall endpoints and the pending-restart reconciliation."""
import io
import json
import os
import tempfile
import zipfile

import pytest

from ui import create_app, db
from ui.addons import registry
from tests.helpers import auth_headers, make_user

MANIFEST = {'id': 'uploaded-addon', 'version': '1.0.0', 'name': 'Uploaded'}


def zip_bytes(manifest=None, extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('qlsm-addon.json', json.dumps(manifest or MANIFEST))
        for name, content in (extra or {}).items():
            zf.writestr(name, content)
    return buf.getvalue()


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    """App whose addon sources are two temp dirs we control."""
    packages = tmp_path / 'addon-packages'
    packages.mkdir()
    bundled = tmp_path / 'bundled'
    bundled.mkdir()
    (bundled / 'built-in-addon').mkdir()
    (bundled / 'built-in-addon' / 'qlsm-addon.json').write_text(
        json.dumps({'id': 'built-in-addon', 'version': '1.0.0'}), encoding='utf-8')

    monkeypatch.setattr(
        registry, '_candidate_dirs',
        lambda a: [(str(bundled), 'bundled'), (str(a.config['ADDON_PACKAGES_DIR']), 'installed')],
    )

    db_fd, db_path = tempfile.mkstemp()
    app = create_app({
        'TESTING': True, 'SECRET_KEY': 'x', 'JWT_SECRET_KEY': 'x',
        'JWT_COOKIE_CSRF_PROTECT': False, 'JWT_TOKEN_LOCATION': ['headers', 'cookies'],
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'SERVER_NAME': 'test.server', 'RCON_ENABLED': False,
        'ADDON_PACKAGES_DIR': str(packages),
    })
    with app.app_context():
        db.create_all()
    make_user(app, 'installer', 'pw')
    headers = auth_headers(app, 'installer')

    yield app, app.test_client(), headers, str(packages)

    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    os.close(db_fd)
    for path in (db_path, f'{db_path}-wal', f'{db_path}-shm'):
        if os.path.exists(path):
            os.unlink(path)


def upload(client, headers, blob, filename='addon.zip'):
    return client.post('/api/addons/install', headers=headers,
                       data={'file': (io.BytesIO(blob), filename)},
                       content_type='multipart/form-data')


# ---- auth --------------------------------------------------------------

def test_install_requires_auth(ctx):
    _, client, _, _ = ctx
    resp = client.post('/api/addons/install', data={}, content_type='multipart/form-data')
    assert resp.status_code == 401


def test_uninstall_requires_auth(ctx):
    _, client, _, _ = ctx
    assert client.delete('/api/addons/uploaded-addon').status_code == 401


# ---- install -----------------------------------------------------------

def test_install_writes_the_package_and_reports_pending_restart(ctx):
    _, client, headers, packages = ctx
    resp = upload(client, headers, zip_bytes())
    assert resp.status_code == 201
    body = resp.get_json()
    assert body['data']['id'] == 'uploaded-addon'
    assert body['data']['pending_restart'] is True
    assert 'Restart' in body['message']
    assert os.path.isfile(os.path.join(packages, 'uploaded-addon', 'qlsm-addon.json'))


def test_install_without_a_file_is_400(ctx):
    _, client, headers, _ = ctx
    resp = client.post('/api/addons/install', headers=headers, data={},
                       content_type='multipart/form-data')
    assert resp.status_code == 400


def test_a_malformed_archive_is_400_not_500(ctx):
    _, client, headers, _ = ctx
    resp = upload(client, headers, b'not a zip at all')
    assert resp.status_code == 400
    assert 'zip' in resp.get_json()['error']['message'].lower()


def test_a_traversing_archive_is_400(ctx):
    _, client, headers, packages = ctx
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('qlsm-addon.json', json.dumps(MANIFEST))
        zf.writestr('../escaped.txt', 'pwned')
    resp = upload(client, headers, buf.getvalue())
    assert resp.status_code == 400
    assert not os.path.exists(os.path.join(os.path.dirname(packages), 'escaped.txt'))


# ---- catalog reconciliation -------------------------------------------

def test_a_freshly_installed_addon_is_listed_as_pending_not_active(ctx):
    """It is on disk but this process never imported it -- claiming it is
    active would give the operator an addon whose endpoints 404."""
    _, client, headers, _ = ctx
    upload(client, headers, zip_bytes())

    addons = client.get('/api/addons', headers=headers).get_json()['data']['addons']
    entry = next(a for a in addons if a['id'] == 'uploaded-addon')
    assert entry['pending_restart'] is True
    assert entry['pending_action'] == 'install'
    assert entry['loaded'] is False


def test_a_loaded_addon_is_not_pending(ctx):
    _, client, headers, _ = ctx
    addons = client.get('/api/addons', headers=headers).get_json()['data']['addons']
    entry = next(a for a in addons if a['id'] == 'built-in-addon')
    assert entry['pending_restart'] is False
    assert entry['loaded'] is True


def test_an_addon_updated_in_place_is_pending_restart(tmp_path):
    """Same id present on the volume before and after, just newer bytes --
    scan_installed_ids() alone can't tell that apart from a no-op, only a
    version comparison can. Regression for the update reminder silently
    disappearing right after install-addon writes the new version."""
    packages = tmp_path / 'addon-packages'
    packages.mkdir()
    (packages / 'installed-addon').mkdir()
    (packages / 'installed-addon' / 'qlsm-addon.json').write_text(
        json.dumps({'id': 'installed-addon', 'version': '1.0.0'}), encoding='utf-8')

    db_fd, db_path = tempfile.mkstemp()
    app = create_app({
        'TESTING': True, 'SECRET_KEY': 'x', 'JWT_SECRET_KEY': 'x',
        'JWT_COOKIE_CSRF_PROTECT': False, 'JWT_TOKEN_LOCATION': ['headers', 'cookies'],
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'SERVER_NAME': 'test.server', 'RCON_ENABLED': False,
        'ADDON_PACKAGES_DIR': str(packages),
    })
    with app.app_context():
        db.create_all()
    make_user(app, 'installer', 'pw')
    headers = auth_headers(app, 'installer')
    client = app.test_client()

    try:
        addons = client.get('/api/addons', headers=headers).get_json()['data']['addons']
        entry = next(a for a in addons if a['id'] == 'installed-addon')
        assert entry['pending_restart'] is False
        assert entry['loaded'] is True

        (packages / 'installed-addon' / 'qlsm-addon.json').write_text(
            json.dumps({'id': 'installed-addon', 'version': '2.0.0'}), encoding='utf-8')

        addons = client.get('/api/addons', headers=headers).get_json()['data']['addons']
        entry = next(a for a in addons if a['id'] == 'installed-addon')
        assert entry['pending_restart'] is True
        assert entry['pending_action'] == 'update'
        assert entry['loaded'] is True  # still running the old code, just flagged
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        os.close(db_fd)
        for path in (db_path, f'{db_path}-wal', f'{db_path}-shm'):
            if os.path.exists(path):
                os.unlink(path)


def test_install_then_uninstall_returns_the_catalog_to_normal(ctx):
    _, client, headers, _ = ctx
    upload(client, headers, zip_bytes())
    assert client.delete('/api/addons/uploaded-addon', headers=headers).status_code == 200

    addons = client.get('/api/addons', headers=headers).get_json()['data']['addons']
    assert [a['id'] for a in addons] == ['built-in-addon']


# ---- uninstall ---------------------------------------------------------

def test_uninstall_removes_an_installed_package(ctx):
    _, client, headers, packages = ctx
    upload(client, headers, zip_bytes())
    resp = client.delete('/api/addons/uploaded-addon', headers=headers)
    assert resp.status_code == 200
    assert not os.path.exists(os.path.join(packages, 'uploaded-addon'))


def test_uninstall_refuses_a_bundled_addon(ctx):
    """It lives in the image: deleting it would leave this container
    inconsistent and it would return on the next deploy anyway."""
    _, client, headers, _ = ctx
    resp = client.delete('/api/addons/built-in-addon', headers=headers)
    assert resp.status_code == 400
    assert 'ships with QLSM' in resp.get_json()['error']['message']


def test_uninstall_of_an_unknown_addon_is_404(ctx):
    _, client, headers, _ = ctx
    assert client.delete('/api/addons/never-heard-of-it', headers=headers).status_code == 404


def test_uninstall_keeps_addon_state_rows(ctx):
    """Reinstalling the same addon should find its settings again."""
    app, client, headers, _ = ctx
    from ui.models import AddonState

    upload(client, headers, zip_bytes())
    with app.app_context():
        db.session.add(AddonState(addon_id='uploaded-addon', scope='global', scope_id=0,
                                  enabled=True, settings_json='{"kept": 1}'))
        db.session.commit()

    client.delete('/api/addons/uploaded-addon', headers=headers)

    with app.app_context():
        row = AddonState.query.filter_by(addon_id='uploaded-addon').one()
        assert row.settings == {'kept': 1}
