"""Every declared lifecycle hook must actually be dispatched somewhere real.

A hook declared but never dispatched reads like a working contract: an addon
subscribes to `instance.launch_args` and is silently ignored. That is worse
than no hook at all, so the declaration and the call site are pinned together
here.

The check is deliberately crude (a text scan for the hook name under `ui/`
plus `addons/`, excluding `ui/addons` itself -- where HOOK_SCOPES is
declared, so the declaration line can never count as its own wiring). A
precise call-graph analysis would be more correct and far more brittle; what
matters is that adding a name to HOOK_SCOPES without wiring it fails the
suite.

Hooks core dispatches itself are checked that way. Addon-owned extension
points (see hooks.py) are dispatched by the addon whose surface they extend,
so no call site for them exists in this repo and they are listed in
OUT_OF_TREE instead. That list is itself pinned by a test, so it cannot
quietly absorb a core hook nobody wired.
"""
import os

import pytest

from ui.addons.hooks import HOOK_SCOPES

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
UI_DIR = os.path.join(REPO_ROOT, 'ui')
ADDONS_DIR = os.path.join(REPO_ROOT, 'addons')
ADDON_PACKAGE = os.path.join(UI_DIR, 'addons')


def _core_sources():
    """Every .py under ui/ (except the addon package that declares the
    hooks) plus every .py under addons/ (where an addon-owned hook is
    legitimately dispatched)."""
    for base, skip in ((UI_DIR, ADDON_PACKAGE), (ADDONS_DIR, None)):
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            if skip and os.path.abspath(root).startswith(skip):
                continue
            for name in files:
                if name.endswith('.py'):
                    yield os.path.join(root, name)


CORE_TEXT = None


def _core_text():
    global CORE_TEXT
    if CORE_TEXT is None:
        chunks = []
        for path in _core_sources():
            with open(path, encoding='utf-8') as f:
                chunks.append(f.read())
        CORE_TEXT = '\n'.join(chunks)
    return CORE_TEXT


# The delete hooks are never named literally in core: cleanup_scope(scope, id)
# builds "<scope>.delete" itself, so core says cleanup_scope('host', ...).
# Spelled out rather than loosening the check, so the indirection stays
# visible instead of quietly making the test weaker.
INDIRECT = {
    'host.delete': "cleanup_scope('host'",
    'instance.delete': "cleanup_scope('instance'",
}

# Addon-owned extension points: declared here because core owns the registry
# of valid hook names (ctx.on() rejects anything not in HOOK_SCOPES at addon
# load time), but dispatched from the addon that consumes the contribution.
# There is no call site in this repo to find, and adding a fake one would be
# worse than an explicit exemption.
OUT_OF_TREE = {
    'demo_management.file_kinds',
    'demo_management.match_groups',
    'player_ranks.providers',
}


@pytest.mark.parametrize('hook', sorted(HOOK_SCOPES))
def test_every_declared_hook_is_referenced_by_core(hook):
    if hook in OUT_OF_TREE:
        pytest.skip('addon-owned hook, dispatched from an addon outside this repo')
    text = _core_text()
    needles = [f"'{hook}'", f'"{hook}"']
    if hook in INDIRECT:
        needles.append(INDIRECT[hook])
    assert any(n in text for n in needles), (
        f'hook "{hook}" is declared in HOOK_SCOPES but nothing under ui/ or '
        f'addons/ dispatches it -- an addon subscribing to it would be silently ignored'
    )


def test_core_dispatches_through_the_registry_at_all():
    """Guards the guard: if dispatch/cleanup_scope stopped being imported by
    core entirely, every hook above could still 'pass' on a stray string."""
    text = _core_text()
    assert 'from ui.addons import dispatch' in text
    assert 'from ui.addons import cleanup_scope' in text


def test_out_of_tree_exemptions_stay_addon_owned():
    """The exemption list is only for hooks an addon dispatches, and every
    name on it must still be declared -- otherwise it is a stale entry that
    would silently excuse a future core hook with the same name."""
    for hook in OUT_OF_TREE:
        assert hook in HOOK_SCOPES, f'{hook} is exempted but no longer declared'
    assert OUT_OF_TREE == {
        'demo_management.file_kinds', 'demo_management.match_groups', 'player_ranks.providers',
    }, (
        'a new out-of-tree exemption was added -- make sure it really is an '
        'addon-owned hook and not a core hook nobody wired'
    )


def test_unwired_hooks_are_not_declared():
    """The two hooks deliberately left out stay out until they have a call
    site -- see the comment under HOOK_SCOPES for why each one is hard."""
    assert 'instance.config_sync' not in HOOK_SCOPES
    assert 'instance.status' not in HOOK_SCOPES
