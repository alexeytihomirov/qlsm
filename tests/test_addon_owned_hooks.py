"""An addon owns its own extension points; core never carries their names.

Before this, a hook an addon dispatched had to be added to core's own
`HOOK_SCOPES` table -- so core shipped the names of features it does not
ship, and a third-party addon could not offer an extension point at all
without a core release. The manifest's `hooks` block replaces that: the addon
that *is* extended declares its points, the registry collects them from every
installed manifest before any backend runs, and `ctx.on()` validates against
that instead of a constant.

What the tests below pin is the part that is easy to get subtly wrong: which
mistakes still fail loudly, and which situations must NOT be treated as
mistakes.
"""
import json
import os
import tempfile
import textwrap

import pytest

from ui.addons import registry
from ui.addons.hooks import HOOK_SCOPES, hook_owner


def write_addon(base, addon_id, manifest=None, backend=None):
    root = os.path.join(str(base), addon_id)
    os.makedirs(root, exist_ok=True)
    payload = manifest if manifest is not None else {'id': addon_id, 'version': '1.0.0'}
    with open(os.path.join(root, 'qlsm-addon.json'), 'w', encoding='utf-8') as f:
        json.dump(payload, f)
    if backend is not None:
        with open(os.path.join(root, 'backend.py'), 'w', encoding='utf-8') as f:
            f.write(textwrap.dedent(backend))
    return root


# An addon that other addons extend: it declares two points, one a
# contribution list and one a single ungated value.
OWNER_MANIFEST = {
    'id': 'file-browser',
    'version': '1.0.0',
    'hooks': {
        'file_kinds': {'scope': 'global', 'list': True,
                       'description': 'Extra extensions to list'},
        'banner': {'scope': None, 'list': False},
    },
}


@pytest.fixture
def addon_app(tmp_path, monkeypatch):
    from ui import create_app

    packages = tmp_path / 'addon-packages'
    packages.mkdir()
    bundled = tmp_path / 'bundled'
    bundled.mkdir()

    monkeypatch.setattr(
        registry, '_candidate_dirs',
        lambda app: [(str(bundled), 'bundled'),
                     (str(app.config['ADDON_PACKAGES_DIR']), 'installed')],
    )

    db_fd, db_path = tempfile.mkstemp()
    built = []

    def _build():
        app = create_app({
            'TESTING': True,
            'SECRET_KEY': 'test-secret-key',
            'JWT_SECRET_KEY': 'test-jwt-secret-key',
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
            'RCON_ENABLED': False,
            'ADDON_PACKAGES_DIR': str(packages),
            'DRAFTS_BASE': str(tmp_path / 'drafts'),
        })
        from ui import db
        with app.app_context():
            db.create_all()
        built.append(app)
        return app

    yield _build, packages

    from ui import db
    for app in built:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
    os.close(db_fd)
    for path in (db_path, f'{db_path}-wal', f'{db_path}-shm'):
        if os.path.exists(path):
            os.unlink(path)


# ---- collection ---------------------------------------------------------

def test_core_declares_no_addon_hooks():
    """The regression this whole change exists for: core's hook table must
    only ever name core's own namespaces."""
    offenders = [name for name in HOOK_SCOPES if hook_owner(name) is not None]
    assert offenders == [], (
        f'{offenders} name an addon; an addon declares its own extension '
        f'points in its manifest instead'
    )


def test_a_declared_point_becomes_a_hook_named_after_its_owner(addon_app):
    build, packages = addon_app
    write_addon(packages, 'file-browser', manifest=OWNER_MANIFEST)
    app = build()

    declared = registry.get_declared_hooks(app)
    assert set(declared) == {'file_browser.file_kinds', 'file_browser.banner'}
    assert declared['file_browser.file_kinds']['owner'] == 'file-browser'
    assert declared['file_browser.file_kinds']['list'] is True
    assert declared['file_browser.banner']['scope'] is None


def test_an_addon_cannot_declare_a_point_in_someone_elses_namespace(addon_app):
    """The full name is built from the addon's own id, so the manifest has no
    say in the namespace -- it cannot claim core's or another addon's."""
    build, packages = addon_app
    write_addon(packages, 'squatter', manifest={
        'id': 'squatter', 'version': '1.0.0',
        'hooks': {'file_kinds': {'scope': 'global', 'list': True}},
    })
    app = build()

    assert set(registry.get_declared_hooks(app)) == {'squatter.file_kinds'}


def test_a_declaration_colliding_with_a_core_hook_is_refused(addon_app):
    """An addon whose id makes its point collide with a core hook name would
    otherwise redefine how core's own dispatch is gated."""
    build, packages = addon_app
    write_addon(packages, 'host', manifest={
        'id': 'host', 'version': '1.0.0',
        'hooks': {'setup': {'scope': 'global'}},
    })
    app = build()

    assert registry.get_declared_hooks(app) == {}
    assert any('collides with a core hook' in e
               for e in registry.get_addon('host', app).errors)


# ---- subscribing --------------------------------------------------------

def test_one_addon_contributes_to_anothers_point(addon_app):
    build, packages = addon_app
    write_addon(packages, 'file-browser', manifest=OWNER_MANIFEST, backend="""
        def register(ctx):
            pass
    """)
    write_addon(packages, 'packer', manifest={'id': 'packer', 'version': '1.0.0'}, backend="""
        def register(ctx):
            @ctx.on('file_browser.file_kinds')
            def kinds():
                return ['qlmatch', 'replay.json.gz']
    """)
    app = build()

    with app.app_context():
        registry.get_addon('packer').ctx.settings.set_enabled('global', 0, True)
        assert registry.dispatch('file_browser.file_kinds', 0) == [
            'qlmatch', 'replay.json.gz',
        ]


def test_load_order_does_not_decide_whether_a_subscription_validates(addon_app):
    """Addons load alphabetically, so a contributor sorted before its owner
    would see an empty table if declarations were collected as backends ran.
    They are collected from the manifests first, before any of them."""
    build, packages = addon_app
    write_addon(packages, 'zzz-owner', manifest={
        'id': 'zzz-owner', 'version': '1.0.0',
        'hooks': {'point': {'scope': 'global', 'list': True}},
    })
    write_addon(packages, 'aaa-contributor', manifest={
        'id': 'aaa-contributor', 'version': '1.0.0'}, backend="""
        def register(ctx):
            @ctx.on('zzz_owner.point')
            def contribute():
                return ['ok']
    """)
    app = build()

    contributor = registry.get_addon('aaa-contributor', app)
    assert contributor.loaded is True
    assert contributor.errors == []


def test_subscribing_to_an_uninstalled_addons_point_is_not_an_error(addon_app):
    """An optional integration must not become a hard dependency: an addon
    that extends another still loads when that other one is absent, and its
    handler simply never fires."""
    build, packages = addon_app
    write_addon(packages, 'packer', manifest={'id': 'packer', 'version': '1.0.0'}, backend="""
        def register(ctx):
            @ctx.on('file_browser.file_kinds')
            def kinds():
                return ['qlmatch']
    """)
    app = build()

    packer = registry.get_addon('packer', app)
    assert packer.loaded is True
    assert packer.errors == []


def test_a_typo_in_an_installed_owners_point_still_fails_loudly(addon_app):
    """The protection that must survive: when the owner *is* installed, we
    know exactly which points exist, so a misspelt one is a typo and the
    addon fails visibly instead of subscribing to nothing."""
    build, packages = addon_app
    write_addon(packages, 'file-browser', manifest=OWNER_MANIFEST)
    write_addon(packages, 'packer', manifest={'id': 'packer', 'version': '1.0.0'}, backend="""
        def register(ctx):
            ctx.on('file_browser.file_knids', lambda: None)
    """)
    app = build()

    packer = registry.get_addon('packer', app)
    assert packer.loaded is False
    assert any('declares no extension point' in e for e in packer.errors)


# ---- dispatching --------------------------------------------------------

def test_a_declared_points_scope_gates_it(addon_app):
    """A contribution from an addon switched off globally must not appear."""
    build, packages = addon_app
    write_addon(packages, 'file-browser', manifest=OWNER_MANIFEST)
    write_addon(packages, 'packer', manifest={'id': 'packer', 'version': '1.0.0'}, backend="""
        def register(ctx):
            @ctx.on('file_browser.file_kinds')
            def kinds():
                return ['qlmatch']
    """)
    app = build()

    with app.app_context():
        assert registry.dispatch('file_browser.file_kinds', 0) == []
        registry.get_addon('packer').ctx.settings.set_enabled('global', 0, True)
        assert registry.dispatch('file_browser.file_kinds', 0) == ['qlmatch']


def test_an_ungated_point_fires_for_a_disabled_addon(addon_app):
    """`"scope": null` means "always", the same as core's own ungated hooks."""
    build, packages = addon_app
    write_addon(packages, 'file-browser', manifest=OWNER_MANIFEST)
    write_addon(packages, 'packer', manifest={'id': 'packer', 'version': '1.0.0'}, backend="""
        def register(ctx):
            @ctx.on('file_browser.banner')
            def banner():
                return 'hello'
    """)
    app = build()

    with app.app_context():
        assert registry.dispatch('file_browser.banner', 0) == ['hello']


def test_dispatching_an_undeclared_addon_point_degrades_instead_of_500ing(addon_app):
    """The mixed-version case: an addon's code dispatches a point its own
    manifest does not declare (an old package on a new core, or the other way
    round). Raising here would turn a listing endpoint into a 500; having no
    contributors is the honest answer, loudly logged."""
    build, packages = addon_app
    write_addon(packages, 'file-browser', manifest={
        'id': 'file-browser', 'version': '1.0.0'})
    app = build()

    with app.app_context():
        assert registry.dispatch('file_browser.file_kinds', 0) == []


def test_dispatching_an_unknown_core_hook_still_raises(addon_app):
    """Core mistyping its own hook is a bug in core, not a degradation."""
    build, _ = addon_app
    app = build()

    with app.app_context():
        with pytest.raises(ValueError, match='unknown core hook'):
            registry.dispatch('instance.lunch_args', 0)
