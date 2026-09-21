"""The acceptance criterion of the whole addon system, as a test.

From the design spec: "the framework is done when telemetry-relay is fully
re-expressed as an addon and there is not one telemetry-specific line left in
core." That is easy to assert and easy to let rot, so it is pinned here
rather than left as prose in a document nobody re-reads.

Deliberately narrow: it looks for the *feature's* names, not for the word
"telemetry" anywhere. What is not allowed is core knowing about the relay.

Also covers demo-stream, which followed the exact same path afterwards: its
own core-owned settings/task-logic modules and four built-in endpoints were
deleted once this addon's endpoints fully replaced them (see
addons/README.md's "Where the line falls" -- and ui/stats_hub.py, which both
features used to share in core, is gone entirely now that each addon carries
its own private copy).
"""
import os

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
UI_DIR = os.path.join(REPO_ROOT, 'ui')
FRONTEND_SRC = os.path.join(REPO_ROOT, 'frontend-react', 'src')

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
    # Names that only exist because the demo-stream feature does.
    'demo_stream_settings',
    'demo_stream_instance',
    'enable_instance_demo_stream',
    'is_instance_demo_stream_enabled',
]

# The one acknowledged exception. bundledPanels.jsx and bundled/ are the
# bridge that lets an addon shipped *inside the image* mount a component
# QLSM's own build compiles, and naming the addon is unavoidable there. It is
# the price of not making every bundled addon ship a pre-built JS bundle; the
# way out is tier 2 (see addons/README.md), at which point this exception
# goes away. Listed explicitly so it stays visible instead of becoming a
# quietly-weakened assertion.
BRIDGE = os.path.join(FRONTEND_SRC, 'components', 'addons')
# The addon system itself, which builds the synthetic module name every addon
# is loaded under. Machinery, not a dependency on any particular addon.
ADDON_MACHINERY = os.path.join(UI_DIR, 'addons')


def _core_files():
    for base in (UI_DIR, FRONTEND_SRC):
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in ('__pycache__', 'node_modules')]
            here = os.path.abspath(root)
            if here.startswith(BRIDGE) or here.startswith(ADDON_MACHINERY):
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

    The bundled bridge is the one allowed exception (see BRIDGE above).
    """
    offenders = []
    for path in _core_files():
        with open(path, encoding='utf-8') as f:
            body = f.read()
        if 'qlsm_addon_' in body:
            offenders.append((os.path.relpath(path, REPO_ROOT), 'imports an addon module'))
        if "from '../../../../../addons/" in body or 'from "../../../../../addons/' in body:
            offenders.append((os.path.relpath(path, REPO_ROOT), 'imports addon UI'))
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
    assert not [r for r in core_rules if 'demo-stream' in r], core_rules


def test_the_telemetry_addon_still_provides_them():
    """The other half of the criterion: removed from core, present as an addon.

    telemetry-relay itself no longer ships bundled in this repo (it lives in
    the separate qlsm-extra repo, installed by the operator onto the
    ADDON_PACKAGES_DIR volume) -- so a default app has nowhere to load it
    from and cannot assert its routes exist. Same for demo-stream, which
    followed the exact same path afterwards. demo-management is the one
    addon that still ships bundled; its route is the part of this guarantee
    this repo alone can check."""
    from ui import create_app

    app = create_app({
        'TESTING': True, 'SECRET_KEY': 'x', 'JWT_SECRET_KEY': 'x',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'RCON_ENABLED': False,
    })
    rules = {str(r) for r in app.url_map.iter_rules()}
    assert '/api/addons/demo-management/instances/<int:instance_id>/demos' in rules


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
