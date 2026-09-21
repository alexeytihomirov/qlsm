"""Every declared lifecycle hook must actually be dispatched somewhere real.

This exists because of a real miss: the whole hook set was declared in phase
1 and core never called any of it until phase 6. Addons could subscribe to
`instance.launch_args` and be silently ignored -- including the repo's own
reference addon. A hook nobody calls is worse than no hook, because it reads
like a working contract.

The check is deliberately crude (a text scan for the hook name under `ui/`
plus `addons/`, excluding `ui/addons` itself -- where HOOK_SCOPES is
declared, so the declaration line can never count as its own wiring). Most
hooks are dispatched by core (`ui/`); a few are addon-owned extension points
dispatched by the addon that defines them (e.g. demo_management.file_kinds,
dispatched from inside addons/demo-management -- see the comment on it in
hooks.py), which is why `addons/` is in scope too. A precise call-graph
analysis would be more correct and far more brittle; what matters is that
adding a name to HOOK_SCOPES without wiring it fails the suite.
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


@pytest.mark.parametrize('hook', sorted(HOOK_SCOPES))
def test_every_declared_hook_is_referenced_by_core(hook):
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


def test_unwired_hooks_are_not_declared():
    """The two hooks deliberately left out stay out until they have a call
    site -- see the comment under HOOK_SCOPES for why each one is hard."""
    assert 'instance.config_sync' not in HOOK_SCOPES
    assert 'instance.status' not in HOOK_SCOPES
