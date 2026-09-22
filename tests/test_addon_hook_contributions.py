"""Hooks change the deploy only when an addon asks them to.

Two properties, and the first matters more: with nothing contributing, every
wired hook must leave core's output byte-identical to what it produced before
the hook existed. An addon system that quietly perturbs a deploy on an
install with no addons would be worse than no addon system.
"""
from unittest.mock import patch

import pytest

from ui import db
from ui.models import Host, HostStatus, InstanceStatus, QLInstance
from ui.task_logic.ansible_instance_mgmt import (
    _build_ld_preload_paths, _build_qlds_args_string,
)


@pytest.fixture
def instance(app):
    with app.app_context():
        host = Host(name='germany', ip_address='10.0.0.1', provider='vultr',
                    status=HostStatus.ACTIVE, runtime='minqlx')
        db.session.add(host)
        db.session.flush()
        inst = QLInstance(
            name='duel', port=27960, hostname='duel', host_id=host.id,
            status=InstanceStatus.RUNNING, zmq_rcon_port=28960, zmq_rcon_password='a',
            zmq_stats_port=29960, zmq_stats_password='b', qlx_plugins='motd',
        )
        db.session.add(inst)
        db.session.commit()
        yield inst


# ---- the no-addon baseline --------------------------------------------

def test_launch_args_are_unchanged_when_nothing_contributes(app, instance):
    with app.app_context():
        with patch('ui.addons.dispatch', return_value=[]) as dispatched:
            args = _build_qlds_args_string(instance)
        assert dispatched.called            # the hook really is wired
    assert '+set qlx_plugins' in args
    assert args.strip().endswith('"')       # nothing appended after the plugin list


def test_ld_preload_is_empty_when_nothing_contributes(app, instance):
    with app.app_context():
        with patch('ui.addons.dispatch', return_value=[]):
            assert _build_ld_preload_paths(instance) == ''


def test_a_failing_registry_cannot_break_a_deploy(app, instance):
    """An addon system that is broken, missing or mid-upgrade must degrade to
    'no contributions', never to a failed deploy."""
    with app.app_context():
        with patch('ui.addons.dispatch', side_effect=RuntimeError('registry exploded')):
            args = _build_qlds_args_string(instance)
            assert _build_ld_preload_paths(instance) == ''
    assert '+set qlx_plugins' in args


# ---- contributions actually land --------------------------------------

def test_a_contributed_cvar_is_appended(app, instance):
    def fake(hook, *a, **kw):
        return ['+set qlx_addonThing 1'] if hook == 'instance.launch_args' else []

    with app.app_context():
        with patch('ui.addons.dispatch', side_effect=fake):
            args = _build_qlds_args_string(instance)
    assert args.endswith('+set qlx_addonThing 1')


def test_a_contributed_plugin_joins_the_qlx_plugins_list(app, instance):
    def fake(hook, *a, **kw):
        return ['my_addon_plugin'] if hook == 'instance.plugins' else []

    with app.app_context():
        with patch('ui.addons.dispatch', side_effect=fake):
            args = _build_qlds_args_string(instance)
    assert 'my_addon_plugin' in args
    assert 'motd' in args      # the operator's own selection survives


def test_a_contributed_plugin_cannot_duplicate_a_system_plugin(app, instance):
    from ui.task_logic.ansible_instance_mgmt import SYSTEM_PLUGINS

    def fake(hook, *a, **kw):
        return [SYSTEM_PLUGINS[0]] if hook == 'instance.plugins' else []

    with app.app_context():
        with patch('ui.addons.dispatch', side_effect=fake):
            args = _build_qlds_args_string(instance)
    plugin_list = args.split('+set qlx_plugins "')[1].split('"')[0]
    assert plugin_list.split(', ').count(SYSTEM_PLUGINS[0]) == 1


def test_a_contributed_preload_path_is_appended(app, instance):
    def fake(hook, *a, **kw):
        return ['/home/ql/qlds-27960/addon/thing.so'] if hook == 'instance.ld_preload' else []

    with app.app_context():
        with patch('ui.addons.dispatch', side_effect=fake):
            assert _build_ld_preload_paths(instance) == '/home/ql/qlds-27960/addon/thing.so'


# ---- host setup extra-vars --------------------------------------------

def test_host_setup_extravars_ignore_keys_core_owns(app):
    """An addon must not be able to change the runtime or the firewall pool a
    host is built with by returning a same-named extra-var."""
    from ui.task_logic.ansible_host_setup import _RESERVED_SETUP_VARS

    assert {'runtime', 'game_udp_ports', 'rcon_tcp_ports', 'host_timezone'} <= _RESERVED_SETUP_VARS


def test_host_setup_contributions_are_dicts_only(app):
    from ui.task_logic.ansible_host_setup import _addon_host_setup_extravars

    host = Host(id=1, name='h', provider='vultr', status=HostStatus.ACTIVE)
    with app.app_context():
        with patch('ui.addons.dispatch', return_value=['not a dict', {}, {'ok': 1}]):
            assert _addon_host_setup_extravars(host) == [{'ok': 1}]


def test_host_setup_survives_a_broken_registry(app):
    from ui.task_logic.ansible_host_setup import _addon_host_setup_extravars

    host = Host(id=1, name='h', provider='vultr', status=HostStatus.ACTIVE)
    with app.app_context():
        with patch('ui.addons.dispatch', side_effect=RuntimeError('boom')):
            assert _addon_host_setup_extravars(host) == []


# ---- backup trees ------------------------------------------------------

def test_addon_backup_trees_are_namespaced(app):
    from ui.task_logic.backup_files import _addon_contributed_trees

    with app.app_context():
        with patch('ui.addons.dispatch', return_value=[('mine', '/tmp/mine')]):
            trees = _addon_contributed_trees()
    assert trees == [('addon/mine', '/tmp/mine', None)]


def test_an_addon_cannot_escape_its_backup_namespace(app):
    from ui.task_logic.backup_files import _addon_contributed_trees

    with app.app_context():
        with patch('ui.addons.dispatch', return_value=[('../configs', '/tmp/x')]):
            trees = _addon_contributed_trees()
    assert trees[0][0] == 'addon/configs'


def test_broken_backup_contributions_are_dropped(app):
    from ui.task_logic.backup_files import _addon_contributed_trees

    with app.app_context():
        with patch('ui.addons.dispatch', return_value=[None, 42, ('', '/tmp/x'), ('ok', '')]):
            assert _addon_contributed_trees() == []
