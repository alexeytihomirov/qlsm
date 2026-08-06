from types import SimpleNamespace

from ui.constants import REDIS_DB_PORT_OFFSET, resolve_redis_db


def test_stored_value_wins():
    instance = SimpleNamespace(redis_db=5, port=27960)
    assert resolve_redis_db(instance) == 5


def test_null_falls_back_to_port_derivation():
    instance = SimpleNamespace(redis_db=None, port=27963)
    assert resolve_redis_db(instance) == 27963 - REDIS_DB_PORT_OFFSET
    assert resolve_redis_db(instance) == 4


def test_first_port_derives_db_one():
    """DB 0 stays reserved for QLSM, so the base game port must map to 1."""
    instance = SimpleNamespace(redis_db=None, port=27960)
    assert resolve_redis_db(instance) == 1


def test_stored_value_of_one_is_not_treated_as_missing():
    """Guards against an `if instance.redis_db:` truthiness bug."""
    instance = SimpleNamespace(redis_db=1, port=27967)
    assert resolve_redis_db(instance) == 1
