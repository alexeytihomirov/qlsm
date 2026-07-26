"""Consistency tests for the global per-host instance limit constants."""

from ui.constants import (
    BASE_GAME_PORT,
    GAME_UDP_PORTS,
    MAX_INSTANCES_PER_HOST,
    RCON_TCP_PORTS,
    ZMQ_RCON_BASE_PORT,
    ZMQ_RCON_PORTS,
    ZMQ_STATS_BASE_PORT,
    ZMQ_STATS_PORTS,
)


def test_max_instances_per_host_is_eight():
    assert MAX_INSTANCES_PER_HOST == 8


def test_game_udp_ports_are_contiguous_from_base():
    assert GAME_UDP_PORTS == list(range(27960, 27968))
    assert len(GAME_UDP_PORTS) == MAX_INSTANCES_PER_HOST
    assert GAME_UDP_PORTS[0] == BASE_GAME_PORT


def test_zmq_port_lists_match_the_deterministic_offset_formula():
    for index, game_port in enumerate(GAME_UDP_PORTS):
        assert ZMQ_RCON_PORTS[index] == ZMQ_RCON_BASE_PORT + (game_port - BASE_GAME_PORT)
        assert ZMQ_STATS_PORTS[index] == ZMQ_STATS_BASE_PORT + (game_port - BASE_GAME_PORT)


def test_rcon_tcp_ports_is_rcon_plus_stats_without_overlap():
    assert RCON_TCP_PORTS == ZMQ_RCON_PORTS + ZMQ_STATS_PORTS
    assert len(set(RCON_TCP_PORTS)) == MAX_INSTANCES_PER_HOST * 2


def test_redis_db_index_stays_within_the_default_sixteen_databases():
    # server_status_poll derives the Redis DB index as (port - 27959).
    assert max(port - 27959 for port in GAME_UDP_PORTS) < 16
