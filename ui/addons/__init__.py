"""qlsm addon system.

Public surface for core call sites. Core should import from here, not from the
submodules, so the internals can move without a repo-wide rename.

Design: docs/superpowers/specs/2026-09-14-qlsm-addon-system-design.md (monorepo).
"""
from ui.addons.context import AddonContext
from ui.addons.hooks import HOOK_SCOPES, LIST_HOOKS, UnknownHookError
from ui.addons.manifest import CURRENT_UI_API, MANIFEST_FILENAME, read_manifest, validate_manifest
from ui.addons.registry import (
    catalog,
    cleanup_scope,
    dispatch,
    get_addon,
    get_addons,
    init_app,
)
from ui.addons.settings import AddonSettings, AddonSettingsError

__all__ = [
    'AddonContext',
    'AddonSettings',
    'AddonSettingsError',
    'CURRENT_UI_API',
    'HOOK_SCOPES',
    'LIST_HOOKS',
    'MANIFEST_FILENAME',
    'UnknownHookError',
    'catalog',
    'cleanup_scope',
    'dispatch',
    'get_addon',
    'get_addons',
    'init_app',
    'read_manifest',
    'validate_manifest',
]
