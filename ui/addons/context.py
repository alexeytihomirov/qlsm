"""AddonContext -- the only surface an addon's backend.py talks to.

An addon never imports core modules directly if it can help it: everything it
is allowed to do goes through this object, which means core can change its
internals without breaking every installed addon, and the set of things an
addon *can* do stays readable in one file.

Addons run in-process with qlsm's full authority (DB, SSH keys, cloud API
key). This context is an ergonomics and consistency boundary, not a security
one -- see section 8.3 of the design spec. Nothing here should be mistaken for
a sandbox.
"""
import logging
import os
from functools import wraps

from ui.addons.hooks import validate_hook_name
from ui.addons.settings import AddonSettings


class AddonContext:
    """Handed to `register(ctx)` in an addon's backend.py."""

    def __init__(self, addon_id, manifest, root_dir):
        self.addon_id = addon_id
        self.manifest = manifest
        self.root_dir = root_dir
        self.settings = AddonSettings(addon_id, manifest)
        self.logger = logging.getLogger(f'qlsm.addon.{addon_id}')

        # Filled in by register(), consumed by the registry.
        self.blueprints = []
        self.tasks = {}
        self.handlers = {}   # hook name -> [callable]

    # ---- paths --------------------------------------------------------

    def path(self, *parts):
        """A path inside this addon's own directory.

        Refuses to escape it: an addon asking for '../../terraform/ssh-keys'
        is either buggy or hostile, and either way core should not help.
        """
        target = os.path.abspath(os.path.join(self.root_dir, *parts))
        root = os.path.abspath(self.root_dir)
        if target != root and not target.startswith(root + os.sep):
            raise ValueError(f'path escapes addon directory: {os.path.join(*parts)}')
        return target

    @property
    def playbooks_dir(self):
        return self.path('playbooks')

    @property
    def assets_dir(self):
        return self.path('assets')

    @property
    def plugins_dir(self):
        return self.path('plugins')

    @property
    def ui_dir(self):
        return self.path('ui')

    # ---- registration -------------------------------------------------

    def blueprint(self, bp):
        """Register a Flask blueprint, mounted under /api/addons/<id>/.

        The prefix is applied by the registry, not by the addon, so an addon
        cannot mount itself anywhere else -- including on top of a core route.
        """
        self.blueprints.append(bp)
        return bp

    def task(self, func=None, *, timeout=300, lock_scope=None):
        """Register an RQ task.

        Wraps the addon's function the same way core's own tasks in
        ui/tasks.py are wrapped: app context, then a try/finally that releases
        the distributed lock. Doing it here rather than trusting the addon is
        deliberate -- a task that forgets to release its lock wedges every
        later operation on that host or instance until Redis expires the key.

        `lock_scope` is 'host' or 'instance'; when set, the wrapped task takes
        the matching id as its first positional argument and an optional
        `lock_token` kwarg, exactly like core's tasks do.
        """
        def decorator(fn):
            from ui import rq
            from ui.task_context import with_app_context

            @wraps(fn)
            def with_lock_release(*args, lock_token=None, **kwargs):
                try:
                    return fn(*args, **kwargs)
                finally:
                    if lock_token and lock_scope:
                        from ui.task_lock import release_lock
                        release_lock(lock_scope, args[0], lock_token)

            job = rq.job(timeout=timeout)(with_app_context(with_lock_release))
            self.tasks[fn.__name__] = job
            return job

        return decorator(func) if func is not None else decorator

    def on(self, hook, func=None):
        """Subscribe to a lifecycle hook. Unknown names raise immediately."""
        validate_hook_name(hook)

        def decorator(fn):
            self.handlers.setdefault(hook, []).append(fn)
            return fn

        return decorator(func) if func is not None else decorator
