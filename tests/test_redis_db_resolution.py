from unittest.mock import MagicMock

import pytest

from ui import create_app
from ui.models import Host, QLInstance


@pytest.fixture(scope='module')
def test_app():
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    with app.app_context():
        yield app


def _make_instance(port=27960, redis_db=None):
    host = MagicMock(spec=Host)
    host.provider = 'vultr'
    host.redis_unix_socket = False
    host.lan_rate_uses_hook = False
    instance = MagicMock(spec=QLInstance)
    instance.host = host
    instance.port = port
    instance.redis_db = redis_db
    instance.hostname = 'Test Server'
    instance.lan_rate_enabled = False
    instance.qlx_plugins = None
    instance.zmq_rcon_port = 28888
    instance.zmq_rcon_password = 'rconpw'
    instance.zmq_stats_port = 29999
    instance.zmq_stats_password = 'statspw'
    return instance


def test_null_redis_db_keeps_port_derived_value(test_app):
    """Backward-compat guard: a pre-existing instance must emit the same DB as before."""
    from ui.task_logic.ansible_instance_mgmt import _build_qlds_args_string
    args = _build_qlds_args_string(_make_instance(port=27963, redis_db=None))
    assert '+set qlx_redisDatabase 4' in args


def test_explicit_redis_db_overrides_the_port_derivation(test_app):
    from ui.task_logic.ansible_instance_mgmt import _build_qlds_args_string
    args = _build_qlds_args_string(_make_instance(port=27963, redis_db=7))
    assert '+set qlx_redisDatabase 7' in args
    assert '+set qlx_redisDatabase 4' not in args


def test_qlds_args_are_byte_identical_when_redis_db_is_null(test_app):
    """The whole arg string -- not just the redis flag -- must be unchanged."""
    from ui.task_logic.ansible_instance_mgmt import _build_qlds_args_string
    from ui.constants import REDIS_DB_PORT_OFFSET

    instance = _make_instance(port=27962, redis_db=None)
    args = _build_qlds_args_string(instance)
    expected_db = 27962 - REDIS_DB_PORT_OFFSET
    assert f'+set qlx_redisDatabase {expected_db}' in args
    assert '+set net_port 27962' in args
    assert '+set fs_homepath /home/ql/qlds-27962' in args


def _make_host():
    host = MagicMock(spec=Host)
    host.provider = 'vultr'
    host.ip_address = '10.0.0.1'
    host.ssh_key_path = '/tmp/key'
    host.ssh_port = 22
    host.ssh_user = 'ql'
    return host


def test_status_poll_uses_stored_redis_db(test_app):
    from ui.task_logic.server_status_poll import _build_ssh_command
    host = _make_host()
    command = _build_ssh_command(host, [_make_instance(port=27961, redis_db=6)])
    assert '(27961, 6)' in ' '.join(command)


def test_status_poll_falls_back_to_port_derivation(test_app):
    from ui.task_logic.server_status_poll import _build_ssh_command
    host = _make_host()
    command = _build_ssh_command(host, [_make_instance(port=27961, redis_db=None)])
    assert '(27961, 2)' in ' '.join(command)
