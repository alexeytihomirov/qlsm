"""Global constants shared by the backend, the Ansible firewall vars and the API.

The per-host instance limit is deliberately a single number here. Everything that
depends on it -- the instance-count gate, the available-port pool, the iptables
allow-lists and the ZMQ port math -- derives from these values rather than
repeating literal port lists, so the layers cannot drift apart.
"""

# Maximum number of QLDS instances that may run on a single host.
#
# Bounded by the Redis DB index used for per-instance state, which
# ui/task_logic/server_status_poll.py derives as (game_port - REDIS_DB_PORT_OFFSET). Redis ships
# with 16 databases by default, so the hard ceiling is 15 instances. 8 leaves
# comfortable headroom.
MAX_INSTANCES_PER_HOST = 8

# First game port; instance N listens on BASE_GAME_PORT + N.
BASE_GAME_PORT = 27960

# Per-instance Redis DB index is (game_port - REDIS_DB_PORT_OFFSET), so the
# first instance lands on DB 1 and DB 0 stays free for QLSM's own state.
REDIS_DB_PORT_OFFSET = BASE_GAME_PORT - 1

# ZMQ RCON and stats ports are derived deterministically from the game port,
# matching ui/task_logic/zmq_utils.ensure_zmq_rcon_setup().
ZMQ_RCON_BASE_PORT = 28888
ZMQ_STATS_BASE_PORT = 29999

GAME_UDP_PORTS = [BASE_GAME_PORT + offset for offset in range(MAX_INSTANCES_PER_HOST)]
ZMQ_RCON_PORTS = [ZMQ_RCON_BASE_PORT + offset for offset in range(MAX_INSTANCES_PER_HOST)]
ZMQ_STATS_PORTS = [ZMQ_STATS_BASE_PORT + offset for offset in range(MAX_INSTANCES_PER_HOST)]

# Every TCP port the firewall must accept for instance management.
RCON_TCP_PORTS = ZMQ_RCON_PORTS + ZMQ_STATS_PORTS


def resolve_redis_db(instance):
    """The Redis logical DB an instance stores its minqlx state in.

    A NULL ``redis_db`` means the instance predates explicit DB selection, so it
    keeps the historical port-derived value. Every caller must go through this
    function -- the derivation used to be duplicated across the Ansible arg
    builder and the status poller, which is how they could drift apart.
    """
    if instance.redis_db is not None:
        return int(instance.redis_db)
    return int(instance.port) - REDIS_DB_PORT_OFFSET
