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
# **Every name here must have a real dispatch call site.** They did not at
# first: the whole set was declared in phase 1 and nothing called it until
# phase 6, so addons could subscribe to hooks that never fired -- the
# reference addon subscribed to instance.launch_args and would have been
# silently ignored. tests/test_addon_hooks_are_wired.py now fails if a hook
# is declared without a call site, so the contract cannot rot back. Most call
# sites live in core (ui/). The exception is an addon-owned extension point
# (see demo_management.file_kinds below), which is dispatched from inside the
# addon that defines it -- and since every addon now lives outside this repo,
# that call site is unreachable from here. Those names are listed explicitly
# in the wiring test's OUT_OF_TREE set rather than silently skipped.
#
# Core still owns the *registry* of valid hook names even for those: ctx.on()
# rejects anything not listed here at addon load time, so a typo in an addon
# fails loudly instead of subscribing to nothing.
HOOK_SCOPES = {
    # host lifecycle
    'host.setup': 'host',      # ansible_host_setup.py, contributes extra-vars
    # Fires after a successful host provisioning/update-plugins playbook run,
    # so an addon can rsync its own host-side payload (e.g. qlmatch-packer's
    # Node runtime). Ungated (None, not 'host'): staging a payload a plugin
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
    # Addon-owned extension point (dispatched by the demo-management addon
    # itself, which lives in the qlsm-extra repo, not by core):
    # demo-management only recognises raw .dm_91 by default; another
    # addon contributes additional filename extensions it wants listed and
    # downloadable alongside it (e.g. qlmatch-packer adds "qlmatch",
    # "replay.json.gz", "packer.log"). Gated at 'global' scope, the same
    # whole-addon on/off switch the Addons page toggle uses -- turning
    # qlmatch-packer off there also stops its files showing up in Demos,
    # consistent with "hidden from host/instance menus until switched on".
    'demo_management.file_kinds': 'global',
    # Addon-owned extension point (dispatched by the demo-management addon,
    # not by core), same "global" gate as file_kinds. Consumer passes (instance_id, demos)
    # -- the current flat file list it already built -- and a contributor
    # returns fully-resolved groups: [{group_id, label, member_names,
    # addon_id, actions: [{id, label, icon, danger, action: {route, method,
    # confirm}}]}]. This differs from the `match_actions` shape sketched in
    # addons/README.md's cross-addon-UI-contribution writeup (a per-row
    # `match(demo)` predicate) because grouping genuinely needs whole-list
    # context and its own I/O (qlmatch-packer opens one SFTP session to read
    # every .qlmatch's manifest.json, the only place match_id/map live) --
    # a per-row Python predicate could not do that without either re-opening
    # SFTP per row or leaking a live session across the hook boundary. A
    # `match(demo)` callable also cannot survive the hook's result reaching
    # the browser as JSON, unlike this hook's plain, JSON-safe group dicts.
    # `route` is relative to the CONTRIBUTING addon's own
    # /api/addons/<addon_id>/ prefix (`addon_id` on the group says which),
    # not demo-management's -- the consumer is a hand-built React component,
    # not a declarative panel, so nothing resolves that prefix for it.
    'demo_management.match_groups': 'global',
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
    'demo_management.file_kinds',
    'demo_management.match_groups',
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
