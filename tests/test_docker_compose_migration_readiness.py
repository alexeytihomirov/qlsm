from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent


def _load_compose():
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())


def test_database_consumers_wait_for_migration_owning_web_service():
    services = _load_compose()["services"]
    web = services["web"]

    assert web["environment"]["RUN_MIGRATIONS"] == "true"
    assert web["healthcheck"]

    for consumer in ("worker", "poller"):
        assert services[consumer]["depends_on"]["web"] == {
            "condition": "service_healthy"
        }


def test_worker_has_stop_grace_period():
    # RQ warm shutdown finishes the running job on SIGTERM; Docker's default
    # 10s would SIGKILL an Ansible run mid-flight.
    assert _load_compose()["services"]["worker"]["stop_grace_period"] == "5m"
