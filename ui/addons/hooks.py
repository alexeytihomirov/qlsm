"""Core's own lifecycle hook names and the scope each one fires at.

Every hook here generalizes an integration point core already had before the
addon system existed. New hooks get added when a real addon needs them -- not
speculatively, since every hook is a call site in core that has to be
maintained forever.

`HOOK_SCOPES` is what makes "enabled" mean something: a hook is only dispatched
to addons that are effectively enabled at that hook's scope. An addon switched
off for one instance contributes nothing to that instance's launch args, with
no per-addon `if enabled:` check to forget.

**This table is core's, and only core's.** An addon that wants to be extended
by other addons declares its own extension points in its manifest's `hooks`
block; the registry collects those at load time and validates subscriptions
against them (see `ui/addons/registry.py`). Nothing about a feature that lives
in an addon belongs in this file -- that was the whole point of the addon
system, and a name here would quietly make core depend on an addon it does not
ship.
"""

# hook name -> the scope whose enable state gates it, or None for "always"
#
# **Every name here must have a real dispatch call site in core**, or an addon
# can subscribe to a hook that never fires and be silently ignored -- the worst
# failure mode a plugin system has. tests/test_addon_hooks_are_wired.py fails
# if a hook is declared here without a call site under ui/.
HOOK_SCOPES = {
    # host lifecycle
    'host.setup': 'host',      # ansible_host_setup.py, contributes extra-vars
    # Fires after a successful host provisioning/update-plugins playbook run,
    # so an addon can rsync its own host-side payload (a language runtime one
    # of its plugins needs, a helper binary). Ungated (None, not 'host'): staging a payload a plugin
    # depends on is not the same thing as the addon's UI panel being enabled
    # for that host, and gating it on that toggle would silently stop the
    # payload deploying on hosts where nobody thought to flip it.
    'host.payload_sync': None,
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

# The namespaces core owns. A name in one of these is core's business, so a
# typo in it is a bug in core or in an addon subscribing to a core hook, and
# must fail loudly. Anything else is an addon's own namespace -- see
# validate_hook_name() for why those are treated differently.
CORE_NAMESPACES = frozenset(name.split('.', 1)[0] for name in HOOK_SCOPES)


class UnknownHookError(ValueError):
    """Raised at registration time, not dispatch time.

    Deliberate: a typo'd hook name that only surfaced at dispatch would look
    like "my addon silently does nothing", which is the worst failure mode a
    plugin system can have.
    """


def hook_owner(name):
    """The addon id that would own `name`, or None for a core hook.

    "file_browser.file_kinds" -> "file-browser". The reverse of how a
    manifest's `hooks` block builds its full names, and the only place that
    mapping is spelled out.
    """
    namespace = str(name).split('.', 1)[0]
    if namespace in CORE_NAMESPACES:
        return None
    return namespace.replace('_', '-')


def validate_hook_name(name, declared=None):
    """Check a subscription. Returns True if the hook will ever be dispatched.

    `declared` is {hook name: spec} for the extension points the installed
    addons declare in their manifests; the registry passes it in.

    Three outcomes, and the difference matters:

    * A core hook, or a point an installed addon declared -> fine.
    * A name in a core namespace that core does not have, or a point an
      *installed* addon does not declare -> `UnknownHookError`. Both are
      typos, and both are catchable, so both fail loudly at load time.
    * A point of an addon that is not installed -> accepted, returns False.
      This is not a typo we can prove, and treating it as one would be wrong:
      an addon that extends another legitimately ships whether or not the
      operator installed the one it extends, and refusing to load it would
      turn an optional integration into a hard dependency. The subscription
      simply never fires, and the caller logs that it is dormant.
    """
    declared = declared or {}
    if name in HOOK_SCOPES or name in declared:
        return True

    owner = hook_owner(name)
    if owner is None:
        raise UnknownHookError(
            f'unknown core hook "{name}"; core hooks: {", ".join(sorted(HOOK_SCOPES))}'
        )
    if any(hook_owner(d) == owner for d in declared):
        points = sorted(d for d in declared if hook_owner(d) == owner)
        raise UnknownHookError(
            f'addon "{owner}" is installed but declares no extension point '
            f'"{name}"; it declares: {", ".join(points)}'
        )
    return False
