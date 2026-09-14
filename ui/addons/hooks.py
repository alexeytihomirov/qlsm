"""Lifecycle hook names and the scope each one fires at.

Every hook here generalizes an integration point core already had before the
addon system existed (see the table in the design spec, section 4.2). New hooks
get added when a real port needs them -- not speculatively, since every hook is
a call site in core that has to be maintained forever.

`HOOK_SCOPES` is what makes "enabled" mean something: a hook is only dispatched
to addons that are effectively enabled at that hook's scope. An addon switched
off for one instance contributes nothing to that instance's launch args, with
no per-addon `if enabled:` check to forget.
"""

# hook name -> the scope whose enable state gates it, or None for "always"
HOOK_SCOPES = {
    # host lifecycle
    'host.setup': 'host',
    'host.delete': None,       # cleanup must run even for a disabled addon
    # instance deploy contributions
    'instance.launch_args': 'instance',
    'instance.plugins': 'instance',
    'instance.ld_preload': 'instance',
    'instance.config_sync': 'instance',
    'instance.status': 'instance',
    'instance.delete': None,   # cleanup must run even for a disabled addon
    # backup
    'backup.export': None,
    'backup.import': None,
}

# Hooks whose results core concatenates into one list (contribution hooks).
# Everything else is fire-and-forget; its return value is ignored.
LIST_HOOKS = frozenset({
    'instance.launch_args',
    'instance.plugins',
    'instance.ld_preload',
    'backup.export',
})


class UnknownHookError(ValueError):
    """Raised at registration time, not dispatch time.

    Deliberate: a typo'd hook name that only surfaced at dispatch would look
    like "my addon silently does nothing", which is the worst failure mode a
    plugin system can have.
    """


def validate_hook_name(name):
    if name not in HOOK_SCOPES:
        raise UnknownHookError(
            f'unknown hook "{name}"; known hooks: {", ".join(sorted(HOOK_SCOPES))}'
        )
    return name
