"""The helper-firewall allow-list must cover every port the instance limit allows."""

from types import SimpleNamespace

from ui.constants import GAME_UDP_PORTS, MAX_INSTANCES_PER_HOST, RCON_TCP_PORTS
from ui.task_logic.self_host_network import build_self_host_network_rules


def _host(**kwargs):
    kwargs.setdefault('provider', 'standalone')
    kwargs.setdefault('instances', [])
    kwargs.setdefault('lan_rate_uses_hook', False)
    return SimpleNamespace(**kwargs)


def test_rules_allow_every_game_port_up_to_the_limit():
    rules = build_self_host_network_rules(_host())

    assert rules['filter']['udp_accept'] == GAME_UDP_PORTS
    assert len(rules['filter']['udp_accept']) == MAX_INSTANCES_PER_HOST


def test_rules_allow_rcon_and_stats_ports_for_every_instance_slot():
    rules = build_self_host_network_rules(_host())

    assert rules['filter']['tcp_accept'] == RCON_TCP_PORTS
    assert 28895 in rules['filter']['tcp_accept']
    assert 30006 in rules['filter']['tcp_accept']


def test_lan_rate_ports_still_come_from_the_hosts_instances():
    instances = [
        SimpleNamespace(id=1, port=27965, lan_rate_enabled=True),
        SimpleNamespace(id=2, port=27966, lan_rate_enabled=False),
    ]
    rules = build_self_host_network_rules(_host(instances=instances))

    assert rules['lan_rate']['udp_ports'] == [27965]


def test_excluded_instance_is_dropped_from_lan_rate_ports():
    instances = [SimpleNamespace(id=7, port=27967, lan_rate_enabled=True)]
    rules = build_self_host_network_rules(_host(instances=instances), exclude_instance_id=7)

    assert rules['lan_rate']['udp_ports'] == []
