"""The reference addon under addons/_examples/ must actually work.

It is documentation people copy from, so a manifest that drifted out of sync
with the validator would teach the wrong thing. These tests load it the same
way the registry would.
"""
import os
import shutil

import pytest

from ui.addons import registry
from ui.addons.manifest import CURRENT_UI_API, read_manifest

EXAMPLE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, 'addons', '_examples', 'hello-addon')
)


def test_example_addon_exists():
    assert os.path.isdir(EXAMPLE_DIR), 'the reference addon was moved or deleted'


def test_example_manifest_validates_cleanly():
    manifest, errors = read_manifest(EXAMPLE_DIR)
    assert errors == [], f'reference addon manifest is invalid: {errors}'
    assert manifest['id'] == 'hello-addon'


def test_example_declares_every_mount_point():
    """If a mount point is added to the system, the reference addon should
    grow an example of it -- that is what keeps this file useful."""
    manifest, _ = read_manifest(EXAMPLE_DIR)
    ui = manifest['ui']
    for point in ('host_menu', 'instance_menu', 'instance_tabs', 'settings_section', 'page'):
        assert ui.get(point), f'reference addon does not demonstrate {point}'


def test_example_covers_both_panel_kinds():
    manifest, _ = read_manifest(EXAMPLE_DIR)
    kinds = {p.get('kind') for p in manifest['ui']['panels'].values()}
    assert {'form', 'table'} <= kinds


def test_example_targets_the_current_ui_api():
    manifest, _ = read_manifest(EXAMPLE_DIR)
    assert manifest['ui_api'] == CURRENT_UI_API


def test_examples_directory_is_not_auto_loaded(app):
    """`addons/_examples/` holds no manifest of its own, so the scanner skips
    it -- the reference addon must never appear in a production menu."""
    with app.app_context():
        assert 'hello-addon' not in registry.get_addons(app)


def test_example_addon_loads_when_installed(tmp_path, monkeypatch):
    """Copied into an addon-packages volume, it must load and register."""
    import tempfile

    from ui import create_app, db

    packages = tmp_path / 'addon-packages'
    packages.mkdir()
    shutil.copytree(EXAMPLE_DIR, packages / 'hello-addon')

    monkeypatch.setattr(
        registry, '_candidate_dirs',
        lambda a: [(str(a.config['ADDON_PACKAGES_DIR']), 'installed')],
    )

    db_fd, db_path = tempfile.mkstemp()
    app = create_app({
        'TESTING': True, 'SECRET_KEY': 'x', 'JWT_SECRET_KEY': 'x',
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'SERVER_NAME': 'test.server', 'RCON_ENABLED': False,
        'ADDON_PACKAGES_DIR': str(packages),
    })
    try:
        with app.app_context():
            db.create_all()
        addon = registry.get_addon('hello-addon', app)
        assert addon is not None
        assert addon.loaded is True, addon.errors
        assert addon.errors == []

        # its blueprint really mounted under the addon prefix
        rules = {str(r) for r in app.url_map.iter_rules()}
        assert '/api/addons/hello-addon/files' in rules
        assert '/api/addons/hello-addon/status' in rules

        # and its lifecycle hook registered against a known hook name
        assert 'instance.launch_args' in addon.ctx.handlers
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        os.close(db_fd)
        for path in (db_path, f'{db_path}-wal', f'{db_path}-shm'):
            if os.path.exists(path):
                os.unlink(path)
