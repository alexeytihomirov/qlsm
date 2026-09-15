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
#
# **Every name here must have a real dispatch call site in core.** They did
# not at first: the whole set was declared in phase 1 and nothing called it
# until phase 6, so addons could subscribe to hooks that never fired -- the
# reference addon subscribed to instance.launch_args and would have been
# silently ignored. tests/test_addon_hooks_are_wired.py now fails if a hook
# is declared without a call site, so the contract cannot rot back.
HOOK_SCOPES = {
    # host lifecycle
    'host.setup': 'host',      # ansible_host_setup.py, contributes extra-vars
    'host.delete': None,       # cleanup must run even for a disabled addon
    # instance deploy contributions, all in ansible_instance_mgmt.py
    'instance.launch_args': 'instance',
    'instance.plugins': 'instance',
    'instance.ld_preload': 'instance',
    # Fires after a successful instance config apply, with the instance id.
    # Ungated: an addon may need to mirror state out of a server.cfg the
    # operator edited by hand, which by definition happens without anyone
    # flipping an enable switch.
    'instance.config_applied': None,
    'instance.delete': None,   # cleanup must run even for a disabled addon
    # backup: one hook, not two -- backup_files.backup_file_trees() feeds both
    # the export and the restore, so a tree contributed once is handled in
    # both directions.
    'backup.export': None,
}

# Deliberately NOT declared until something needs them, because a hook nobody
# calls is worse than no hook at all:
#   instance.config_sync -- the natural call site (_sync_configs_to_disk) takes
#     a directory, not an instance, so there is nothing sensible to pass yet.
#   instance.status -- the poller runs per host over SSH with a hard deadline;
#     letting addon code run inside that budget needs its own design.

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
