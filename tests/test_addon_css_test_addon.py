"""The reference addon under addons/_examples/css-test-addon/ must actually work.

Same pattern as test_addon_example.py's hello-addon coverage, but this one
exists specifically to pin the backend half of the CSS-loading contract: a
tier-2 component's `ui/Panel.css` is served next to `ui/Panel.js` with no
manifest involvement, through the existing `/ui/<path:filename>` route.
"""
import os
import shutil
import tempfile

import pytest

from ui import create_app, db
from ui.addons import registry
from ui.addons.manifest import CURRENT_UI_API, read_manifest
from tests.helpers import auth_headers, make_user

EXAMPLE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, 'addons', '_examples', 'css-test-addon')
)


def test_example_addon_exists():
    assert os.path.isdir(EXAMPLE_DIR), 'the reference addon was moved or deleted'


def test_example_manifest_validates_cleanly():
    manifest, errors = read_manifest(EXAMPLE_DIR)
    assert errors == [], f'reference addon manifest is invalid: {errors}'
    assert manifest['id'] == 'css-test-addon'


def test_example_targets_the_current_ui_api():
    manifest, _ = read_manifest(EXAMPLE_DIR)
    assert manifest['ui_api'] == CURRENT_UI_API


def test_examples_directory_is_not_auto_loaded(app):
    with app.app_context():
        assert 'css-test-addon' not in registry.get_addons(app)


@pytest.fixture
def installed_app(tmp_path, monkeypatch):
    """Copied into an addon-packages volume, the way an operator would try it."""
    packages = tmp_path / 'addon-packages'
    packages.mkdir()
    shutil.copytree(EXAMPLE_DIR, packages / 'css-test-addon')

    monkeypatch.setattr(
        registry, '_candidate_dirs',
        lambda a: [(str(a.config['ADDON_PACKAGES_DIR']), 'installed')],
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
        'SERVER_NAME': 'test.server', 'RCON_ENABLED': False,
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


def test_example_addon_loads(installed_app):
    with installed_app.app_context():
        addon = registry.get_addon('css-test-addon', installed_app)
        assert addon is not None
        assert addon.loaded is True, addon.errors


def test_example_addon_serves_its_component_and_css(installed_app):
    """Both Panel.js and Panel.css must be reachable at the URL
    AddonComponentHost/ensureAddonCss compute for them --
    /api/addons/<id>/ui/<filename> -- the same asset route every tier-2
    addon's component already uses."""
    make_user(installed_app, 'operator', 'pw')
    auth = auth_headers(installed_app, 'operator')
    client = installed_app.test_client()

    js_resp = client.get('/api/addons/css-test-addon/ui/Panel.js', headers=auth)
    assert js_resp.status_code == 200
    assert b'export default function Panel' in js_resp.data

    css_resp = client.get('/api/addons/css-test-addon/ui/Panel.css', headers=auth)
    assert css_resp.status_code == 200
    assert b'.css-test-addon-panel' in css_resp.data
