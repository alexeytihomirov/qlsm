"""Host setup must hand Ansible the same firewall port lists the backend enforces.

Ansible's `-e key=value` form always yields a STRING, and it splits the argument
on whitespace -- `-e 'game_udp_ports=[27960, 27961]'` arrives as the string
"[27960," . A Jinja `{% for p in game_udp_ports %}` over that iterates characters
and renders garbage firewall rules. Only a single JSON-object argument
(`-e '{"game_udp_ports": [...]}'`) reaches the playbook as a real list, so these
tests pin both the native list values and the JSON-object wire format.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

from ui.constants import GAME_UDP_PORTS, RCON_TCP_PORTS
from ui.task_logic.standalone_host_setup import (
    _run_setup_playbook,
    _setup_playbook_extra_vars,
)


def _host(provider='standalone'):
    return SimpleNamespace(
        provider=provider, ssh_port=22, timezone=None,
        engine_flavor='minqlx', engine_source='build', engine_artifact_url=None,
    )


def test_standalone_extra_vars_include_the_derived_game_ports():
    extra_vars = _setup_playbook_extra_vars(_host())

    assert extra_vars['game_udp_ports'] == GAME_UDP_PORTS
    assert isinstance(extra_vars['game_udp_ports'], list)


def test_standalone_extra_vars_include_the_derived_rcon_ports():
    extra_vars = _setup_playbook_extra_vars(_host())

    assert extra_vars['rcon_tcp_ports'] == RCON_TCP_PORTS
    assert isinstance(extra_vars['rcon_tcp_ports'], list)


def test_existing_standalone_extra_vars_are_preserved():
    extra_vars = _setup_playbook_extra_vars(_host())

    assert extra_vars['is_standalone'] == 'true'
    assert extra_vars['firewall_mode'] == 'helper'
    assert extra_vars['ssh_port'] == '22'


def test_self_provider_still_disables_host_redis():
    extra_vars = _setup_playbook_extra_vars(_host(provider='self'))

    assert extra_vars['use_host_redis'] == 'false'


def _captured_argv(host):
    """Run _run_setup_playbook with the subprocess stubbed, return its argv."""
    with patch('ui.task_logic.standalone_host_setup.subprocess.Popen') as popen, \
            patch('ui.task_logic.ansible_runner._stream_output', return_value=('', '')), \
            patch('ui.task_logic.standalone_host_setup.append_log'):
        popen.return_value.returncode = 0
        _run_setup_playbook(host, '/tmp/inventory.yml')
    return popen.call_args[0][0]


def test_setup_playbook_passes_extra_vars_as_one_json_object():
    """`-e key=value` would stringify (and space-split) the port lists."""
    argv = _captured_argv(_host())

    json_args = [
        argv[index + 1]
        for index, token in enumerate(argv)
        if token == '-e' and argv[index + 1].lstrip().startswith('{')
    ]
    assert len(json_args) == 1, f"expected exactly one JSON -e argument, got argv={argv}"

    payload = json.loads(json_args[0])
    assert payload['game_udp_ports'] == GAME_UDP_PORTS
    assert payload['rcon_tcp_ports'] == RCON_TCP_PORTS
    assert payload['firewall_mode'] == 'helper'


def test_no_extra_var_uses_the_bare_key_equals_list_form():
    """Regression guard: the bare form silently becomes a string."""
    argv = _captured_argv(_host())

    for index, token in enumerate(argv):
        if token == '-e':
            value = argv[index + 1]
            assert not value.startswith('game_udp_ports='), value
            assert not value.startswith('rcon_tcp_ports='), value
