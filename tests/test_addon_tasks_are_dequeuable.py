"""An addon's RQ task must be resolvable by the worker.

This is the load-bearing assumption behind moving a feature's background work
out of ui/tasks.py and into an addon. RQ stores a job as the dotted path
`<module>.<function>` and re-imports it in the worker process. An addon's
backend is loaded from a file path under a synthetic module name
(`qlsm_addon_<id>`), which normal import machinery cannot find on disk -- so
the only reason this works is that the registry leaves that module in
sys.modules, and `flask rq worker` builds the app (and therefore loads
addons) before RQ ever resolves a job.

If this ever stops holding, every addon-owned task silently fails to dequeue
with "No module named qlsm_addon_...", which is exactly the failure mode you
do not want to discover on a production host.
"""
import json
import os
import sys
import tempfile
import textwrap

import pytest

from ui import create_app, db
from ui.addons import registry

ADDON_ID = 'task-owner'
MODULE_NAME = 'qlsm_addon_task_owner'

BACKEND = '''
    def register(ctx):
        @ctx.task(timeout=30, lock_scope='host')
        def do_the_thing(host_id):
            return f'did it for {host_id}'
'''


@pytest.fixture
def app_with_task_addon(tmp_path, monkeypatch):
    packages = tmp_path / 'addon-packages'
    root = packages / ADDON_ID
    root.mkdir(parents=True)
    (root / 'qlsm-addon.json').write_text(
        json.dumps({'id': ADDON_ID, 'version': '1.0.0'}), encoding='utf-8')
    (root / 'backend.py').write_text(textwrap.dedent(BACKEND), encoding='utf-8')

    monkeypatch.setattr(
        registry, '_candidate_dirs',
        lambda a: [(str(a.config['ADDON_PACKAGES_DIR']), 'installed')],
    )

    db_fd, db_path = tempfile.mkstemp()
    app = create_app({
        'TESTING': True, 'SECRET_KEY': 'x', 'JWT_SECRET_KEY': 'x',
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'SERVER_NAME': 'test.server', 'RCON_ENABLED': False,
        'ADDON_PACKAGES_DIR': str(packages),
    })
    with app.app_context():
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    sys.modules.pop(MODULE_NAME, None)
    os.close(db_fd)
    for path in (db_path, f'{db_path}-wal', f'{db_path}-shm'):
        if os.path.exists(path):
            os.unlink(path)


def test_the_addon_registered_its_task(app_with_task_addon):
    addon = registry.get_addon(ADDON_ID, app_with_task_addon)
    assert addon.loaded is True, addon.errors
    assert 'do_the_thing' in addon.ctx.tasks


def test_the_addon_module_stays_importable_by_name(app_with_task_addon):
    """The whole mechanism rests on this: the module was loaded from a file
    path, so only its presence in sys.modules makes it importable later."""
    import importlib

    assert MODULE_NAME in sys.modules
    assert importlib.import_module(MODULE_NAME) is sys.modules[MODULE_NAME]


def test_rq_can_resolve_the_task_the_way_a_worker_would(app_with_task_addon):
    """The actual check: RQ's own resolver, on the dotted path RQ would have
    stored, must hand back a callable."""
    from rq.utils import import_attribute

    addon = registry.get_addon(ADDON_ID, app_with_task_addon)
    job = addon.ctx.tasks['do_the_thing']
    dotted = f'{job.__module__}.{job.__name__}'

    assert job.__module__ == MODULE_NAME, (
        'the task no longer reports the addon module -- RQ would store a path '
        'the worker cannot resolve'
    )
    assert callable(import_attribute(dotted))


def test_the_task_carries_the_rq_helper_enqueue_task_needs(app_with_task_addon):
    """ui.tasks.enqueue_task reads `.helper` off the decorated function; an
    addon task that lacks it cannot be enqueued at all."""
    addon = registry.get_addon(ADDON_ID, app_with_task_addon)
    job = addon.ctx.tasks['do_the_thing']
    assert hasattr(job, 'helper')
    assert hasattr(job.helper, 'queue_name')
