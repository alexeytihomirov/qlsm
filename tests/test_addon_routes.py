"""Core-owned addon endpoints: catalog, state read/write, tier-2 asset serving."""
import json
import os
import tempfile
import textwrap

import pytest

from ui import create_app, db
from ui.addons import registry
from ui.models import Host, HostStatus
from tests.helpers import auth_headers, make_user

MANIFEST = {
    'id': 'sample-addon',
    'version': '1.0.0',
    'name': 'Sample Addon',
    'scopes': ['global', 'host'],
    'settings': {
        'global': [{'key': 'stats_hub_url', 'type': 'string', 'default': ''}],
        'host': [{'key': 'timeout_sec', 'type': 'number', 'default': 2, 'min': 1, 'max': 30}],
    },
}


@pytest.fixture
def addon_app(tmp_path, monkeypatch):
    packages = tmp_path / 'addon-packages'
    root = packages / 'sample-addon' / 'ui'
    root.mkdir(parents=True)
    (packages / 'sample-addon' / 'qlsm-addon.json').write_text(
        json.dumps(MANIFEST), encoding='utf-8')
    (packages / 'sample-addon' / 'backend.py').write_text(
        textwrap.dedent('''
            def register(ctx):
                pass
        '''), encoding='utf-8')
    (root / 'panel.js').write_text('export default () => null;', encoding='utf-8')
    (packages / 'sample-addon' / 'secrets.txt').write_text('do not serve me', encoding='utf-8')

    bundled = tmp_path / 'bundled'
    bundled.mkdir()
    monkeypatch.setattr(
        registry, '_candidate_dirs',
        lambda app: [(str(bundled), 'bundled'), (str(app.config['ADDON_PACKAGES_DIR']), 'installed')],
    )

    db_fd, db_path = tempfile.mkstemp()
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'test-secret-key',
        'JWT_SECRET_KEY': 'test-jwt-secret-key',
        'JWT_COOKIE_CSRF_PROTECT': False,
        'JWT_TOKEN_LOCATION': ['headers', 'cookies'],
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'SERVER_NAME': 'test.server',
        'RCON_ENABLED': False,
        'ADDON_PACKAGES_DIR': str(packages),
    })
    with app.app_context():
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    os.close(db_fd)
    for path in (db_path, f'{db_path}-wal', f'{db_path}-shm'):
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture
def auth(addon_app):
    make_user(addon_app, 'operator', 'pw')
    return auth_headers(addon_app, 'operator')


@pytest.fixture
def host_id(addon_app):
    with addon_app.app_context():
        host = Host(name='germany', ip_address='10.0.0.1', provider='vultr',
                    status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.commit()
        return host.id


# ---- auth -------------------------------------------------------------

def test_catalog_requires_auth(addon_app):
    assert addon_app.test_client().get('/api/addons').status_code == 401


def test_state_requires_auth(addon_app):
    assert addon_app.test_client().get('/api/addons/sample-addon/state').status_code == 401


# ---- catalog ----------------------------------------------------------

def test_catalog_lists_the_installed_addon(addon_app, auth):
    resp = addon_app.test_client().get('/api/addons', headers=auth)
    assert resp.status_code == 200
    addons = resp.get_json()['data']['addons']
    assert [a['id'] for a in addons] == ['sample-addon']
    assert addons[0]['name'] == 'Sample Addon'
    assert addons[0]['source'] == 'installed'
    assert addons[0]['loaded'] is True


def test_catalog_exposes_the_settings_schema(addon_app, auth):
    resp = addon_app.test_client().get('/api/addons', headers=auth)
    schema = resp.get_json()['data']['addons'][0]['settings_schema']
    assert schema['host'][0]['key'] == 'timeout_sec'


# ---- state ------------------------------------------------------------

def test_unknown_addon_is_404(addon_app, auth):
    resp = addon_app.test_client().get('/api/addons/nope/state', headers=auth)
    assert resp.status_code == 404


def test_state_defaults_before_anything_is_stored(addon_app, auth, host_id):
    resp = addon_app.test_client().get(
        f'/api/addons/sample-addon/state?scope=host&scope_id={host_id}', headers=auth)
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['settings'] == {'timeout_sec': 2}
    assert data['enabled'] is False
    assert data['effective'] is False


def test_unknown_scope_is_400(addon_app, auth):
    resp = addon_app.test_client().get(
        '/api/addons/sample-addon/state?scope=galaxy', headers=auth)
    assert resp.status_code == 400


def test_non_integer_scope_id_is_400(addon_app, auth):
    resp = addon_app.test_client().get(
        '/api/addons/sample-addon/state?scope=host&scope_id=abc', headers=auth)
    assert resp.status_code == 400


def test_put_stores_settings(addon_app, auth, host_id):
    client = addon_app.test_client()
    resp = client.put(f'/api/addons/sample-addon/state?scope=host&scope_id={host_id}',
                      json={'settings': {'timeout_sec': 9}}, headers=auth)
    assert resp.status_code == 200
    assert resp.get_json()['data']['settings']['timeout_sec'] == 9

    again = client.get(f'/api/addons/sample-addon/state?scope=host&scope_id={host_id}',
                       headers=auth)
    assert again.get_json()['data']['settings']['timeout_sec'] == 9


def test_put_rejects_an_out_of_range_value(addon_app, auth, host_id):
    resp = addon_app.test_client().put(
        f'/api/addons/sample-addon/state?scope=host&scope_id={host_id}',
        json={'settings': {'timeout_sec': 99}}, headers=auth)
    assert resp.status_code == 400


def test_put_rejects_an_undeclared_key(addon_app, auth, host_id):
    resp = addon_app.test_client().put(
        f'/api/addons/sample-addon/state?scope=host&scope_id={host_id}',
        json={'settings': {'timeuot_sec': 5}}, headers=auth)
    assert resp.status_code == 400


def test_rejected_write_leaves_nothing_behind(addon_app, auth, host_id):
    """A 400 must not half-apply -- the enable flag in the same body is rolled back too."""
    client = addon_app.test_client()
    client.put(f'/api/addons/sample-addon/state?scope=host&scope_id={host_id}',
               json={'enabled': True, 'settings': {'timeout_sec': 999}}, headers=auth)
    state = client.get(f'/api/addons/sample-addon/state?scope=host&scope_id={host_id}',
                       headers=auth).get_json()['data']
    assert state['enabled'] is False
    assert state['settings']['timeout_sec'] == 2


def test_effective_state_follows_the_layer_rule(addon_app, auth, host_id):
    client = addon_app.test_client()
    client.put(f'/api/addons/sample-addon/state?scope=host&scope_id={host_id}',
               json={'enabled': True}, headers=auth)
    state = client.get(f'/api/addons/sample-addon/state?scope=host&scope_id={host_id}',
                       headers=auth).get_json()['data']
    assert state['enabled'] is True       # this layer's own switch
    assert state['effective'] is False    # global is still off

    client.put('/api/addons/sample-addon/state?scope=global', json={'enabled': True},
               headers=auth)
    state = client.get(f'/api/addons/sample-addon/state?scope=host&scope_id={host_id}',
                       headers=auth).get_json()['data']
    assert state['effective'] is True


# ---- tier-2 assets ----------------------------------------------------

def test_ui_asset_is_served(addon_app, auth):
    resp = addon_app.test_client().get('/api/addons/sample-addon/ui/panel.js', headers=auth)
    assert resp.status_code == 200
    assert b'export default' in resp.data


def test_non_js_asset_is_refused(addon_app, auth):
    """The addon dir also holds backend.py and playbooks; this route must
    never become a way to read them over HTTP."""
    resp = addon_app.test_client().get('/api/addons/sample-addon/ui/../secrets.txt',
                                       headers=auth)
    assert resp.status_code in (400, 403, 404)


def test_traversal_out_of_the_ui_dir_is_refused(addon_app, auth):
    resp = addon_app.test_client().get('/api/addons/sample-addon/ui/../backend.py',
                                       headers=auth)
    assert resp.status_code in (400, 403, 404)


def test_missing_asset_is_404(addon_app, auth):
    resp = addon_app.test_client().get('/api/addons/sample-addon/ui/nope.js', headers=auth)
    assert resp.status_code == 404
