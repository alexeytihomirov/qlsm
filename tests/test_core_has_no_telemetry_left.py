"""The acceptance criterion of the whole addon system, as a test.

From the design spec: "the framework is done when telemetry-relay is fully
re-expressed as an addon and there is not one telemetry-specific line left in
core." That is easy to assert and easy to let rot, so it is pinned here
rather than left as prose in a document nobody re-reads.

Deliberately narrow: it looks for the *feature's* names, not for the word
"telemetry" anywhere. ui/stats_hub.py legitimately mentions stats-hub, and
the demo stream legitimately reserves server IDs -- shared infrastructure is
allowed in core. What is not allowed is core knowing about the relay.
"""
import os
import re

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
UI_DIR = os.path.join(REPO_ROOT, 'ui')
FRONTEND_SRC = os.path.join(REPO_ROOT, 'frontend-react', 'src')
ADDONS_TREE = os.path.join(REPO_ROOT, 'addons')

# Names that only exist because the telemetry-relay feature does.
FORBIDDEN_IN_CORE = [
    'telemetry_relay_settings',
    'ansible_telemetry_relay',
    'telemetry_relay_instance',
    'configure_host_telemetry_relay',
    'enable_instance_telemetry',
    'install_telemetry_relay',
    'TelemetryRelayModal',
    'getTelemetryRelay',
]

# The addon system itself, which builds the synthetic module name every addon
# is loaded under. Machinery, not a dependency on any particular addon.
#
# There used to be a second exception here: frontend-react's bundled-component
# registry, which named the addons whose UI core compiled. That exception is
# gone -- QLSM ships no feature addon in its image any more, every addon
# brings its own pre-built component, and no file under frontend-react/src
# names an addon. The spec's "one acknowledged coupling" is closed.
ADDON_MACHINERY = os.path.join(UI_DIR, 'addons')


def _core_files():
    for base in (UI_DIR, FRONTEND_SRC):
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in ('__pycache__', 'node_modules')]
            here = os.path.abspath(root)
            if here.startswith(ADDON_MACHINERY):
                continue
            for name in files:
                if name.endswith(('.py', '.js', '.jsx')):
                    yield os.path.join(root, name)


@pytest.mark.parametrize('needle', FORBIDDEN_IN_CORE)
def test_core_does_not_mention_the_telemetry_feature(needle):
    offenders = []
    for path in _core_files():
        with open(path, encoding='utf-8') as f:
            if needle in f.read():
                offenders.append(os.path.relpath(path, REPO_ROOT))
    assert not offenders, (
        f'"{needle}" is telemetry-relay\'s, and it reappeared in core: '
        f'{offenders}. It belongs in addons/telemetry-relay/.'
    )


def test_core_never_imports_an_addon():
    """The coupling that actually matters: an import, not a mention.

    Core comments may well say "the telemetry-relay addon" -- that is how the
    shape of ui/stats_hub.py is explained, and deleting those comments to
    satisfy a grep would make the code harder to understand for no gain. What
    must never happen is core *depending* on addon code: uninstall the addon
    and core stops working.
    """
    offenders = []
    for path in _core_files():
        with open(path, encoding='utf-8') as f:
            body = f.read()
        if 'qlsm_addon_' in body:
            offenders.append((os.path.relpath(path, REPO_ROOT), 'imports an addon module'))
        for spec in re.findall(r'''from ['"](\.[^'"]+)['"]''', body):
            # Resolve the relative import for real rather than pattern-matching
            # the ../ depth: components/addons/ is core's own directory and
            # would match any "addons/" needle.
            target = os.path.normpath(os.path.join(os.path.dirname(path), spec))
            if not target.startswith(ADDONS_TREE + os.sep):
                continue
            # addons/_examples/ is reference material that ships in this repo
            # and loads nowhere -- a test may import one to prove the contract
            # it demonstrates still holds (UiKitTestAddonPanel.test.jsx). A
            # real addon is a different thing entirely: it can be uninstalled.
            if target.startswith(os.path.join(ADDONS_TREE, '_examples') + os.sep):
                continue
            offenders.append((os.path.relpath(path, REPO_ROOT),
                              f'imports addon UI: {os.path.relpath(target, REPO_ROOT)}'))
    assert not offenders, f'core depends on addon code: {offenders}'


def test_core_has_no_telemetry_endpoints():
    """The routes themselves, checked through the app rather than by grep."""
    from ui import create_app

    app = create_app({
        'TESTING': True, 'SECRET_KEY': 'x', 'JWT_SECRET_KEY': 'x',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'RCON_ENABLED': False,
    })
    core_rules = [
        str(r) for r in app.url_map.iter_rules()
        if not str(r).startswith('/api/addons/')
    ]
    assert not [r for r in core_rules if 'telemetry' in r], core_rules
    assert not [r for r in core_rules if r.endswith('/demos') or '/demos/' in r], core_rules


def test_no_feature_addon_ships_in_the_image():
    """The other half of the criterion, as far as this repo can still check it.

    Every feature addon (telemetry-relay, demo-management, demo-stream,
    qlmatch-packer) now lives in the separate qlsm-extra repo and is installed
    by the operator onto the ADDON_PACKAGES_DIR volume, so a default app has
    nowhere to load one from and cannot assert its routes exist. What this
    repo can still pin is the inverse: a stock QLSM answers the addon
    machinery's own routes and nothing feature-specific, and addons/ holds
    only documentation plus the non-loading reference examples."""
    from ui import create_app

    app = create_app({
        'TESTING': True, 'SECRET_KEY': 'x', 'JWT_SECRET_KEY': 'x',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'RCON_ENABLED': False,
    })
    rules = {str(r) for r in app.url_map.iter_rules()}
    assert '/api/addons' in rules
    assert not [r for r in rules if r.startswith('/api/addons/demo-management')]

    addons_dir = os.path.join(REPO_ROOT, 'addons')
    shipped = {
        name for name in os.listdir(addons_dir)
        if os.path.isfile(os.path.join(addons_dir, name, 'qlsm-addon.json'))
    }
    assert shipped == set(), f'a feature addon crept back into the image: {shipped}'


def test_the_external_api_moved_with_qlmatch_packer():
    """/api/v1/instances is still a core contract (no demo helpers involved),
    but the match-listing endpoints moved into the qlmatch-packer addon
    along with qlmatch_listing.py itself - uninstalling that addon now
    removes this part of the external API too, by design (see
    addons/README.md). qlmatch-packer itself lives in the separate
    qlsm-extra repo (not bundled here), so a default app never loads it and
    its route cannot be asserted from this repo -- only that core never grew
    the endpoint back."""
    from ui import create_app

    app = create_app({
        'TESTING': True, 'SECRET_KEY': 'x', 'JWT_SECRET_KEY': 'x',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'RCON_ENABLED': False,
    })
    rules = {str(r) for r in app.url_map.iter_rules()}
    assert '/api/v1/instances' in rules
    assert '/api/v1/instances/<int:instance_id>/matches' not in rules
    assert '/api/addons/demo-management/instances/<int:instance_id>/matches' not in rules
