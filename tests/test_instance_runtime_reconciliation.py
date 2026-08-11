from unittest.mock import Mock

import pytest
from sqlalchemy import update
from sqlalchemy.orm import sessionmaker

from ui import db
from ui.database import create_host, create_instance
from ui.models import HostStatus, InstanceStatus, QLInstance
from ui.task_logic.service_runtime import RuntimeObservation


MESSAGE = "Confirmed service restart; pending configuration is now active. Status: running."
OLD_ID = "a" * 32
NEW_ID = "b" * 32
REPLACEMENT_ID = "c" * 32


def _observation(**changes):
    values = {
        "status": {"map": "campgrounds", "players": [], "updated": 1_786_320_010},
        "invocation_id": NEW_ID,
        "active": True,
        "service_started_at": 1_786_320_000,
    }
    values.update(changes)
    return RuntimeObservation(**values)


def _create_instance(status=InstanceStatus.UPDATED, baseline=OLD_ID):
    host = create_host(
        name="runtime-reconciliation-host",
        provider="standalone",
        status=HostStatus.ACTIVE,
    )
    instance = create_instance(
        name="runtime-reconciliation-instance",
        host_id=host.id,
        port=27960,
        hostname="Runtime reconciliation test",
    )
    instance.status = status
    instance.runtime_invocation_id = baseline
    db.session.commit()
    return instance


def _stored(instance_id):
    db.session.expire_all()
    return db.session.get(QLInstance, instance_id)


def _reconcile(instance, observation):
    from ui.task_logic.instance_runtime_reconciliation import reconcile_runtime_observations

    return reconcile_runtime_observations([instance], {"27960": observation})


def test_null_baseline_is_recorded_without_promoting_updated_instance(app):
    with app.app_context():
        instance = _create_instance(baseline=None)

        assert _reconcile(instance, _observation()) == 0

        stored = _stored(instance.id)
        assert stored.status is InstanceStatus.UPDATED
        assert stored.runtime_invocation_id == NEW_ID
        assert stored.logs is None


def test_unchanged_identity_leaves_updated_instance_untouched(app):
    with app.app_context():
        instance = _create_instance()

        assert _reconcile(instance, _observation(invocation_id=OLD_ID)) == 0

        stored = _stored(instance.id)
        assert stored.status is InstanceStatus.UPDATED
        assert stored.runtime_invocation_id == OLD_ID
        assert stored.logs is None


@pytest.mark.parametrize(
    "observation",
    [
        _observation(status=None),
        _observation(status={"updated": 1_786_320_000}),
        _observation(status={"updated": 1_786_319_999}),
        _observation(status={"updated": 1_786_320_010}, service_started_at=1_786_320_020),
        _observation(invocation_id="not-an-invocation-id"),
        _observation(active=False),
    ],
)
def test_ineligible_observation_never_changes_updated_instance(app, observation):
    with app.app_context():
        instance = _create_instance()

        assert _reconcile(instance, observation) == 0

        stored = _stored(instance.id)
        assert stored.status is InstanceStatus.UPDATED
        assert stored.runtime_invocation_id == OLD_ID
        assert stored.logs is None


def test_changed_fresh_identity_promotes_updated_instance_and_logs_once(app):
    with app.app_context():
        instance = _create_instance()

        assert _reconcile(instance, _observation()) == 1

        stored = _stored(instance.id)
        assert stored.status is InstanceStatus.RUNNING
        assert stored.runtime_invocation_id == NEW_ID
        assert stored.logs.count(MESSAGE) == 1


def test_changed_fresh_identity_only_advances_running_baseline(app):
    with app.app_context():
        instance = _create_instance(status=InstanceStatus.RUNNING)

        assert _reconcile(instance, _observation()) == 0

        stored = _stored(instance.id)
        assert stored.status is InstanceStatus.RUNNING
        assert stored.runtime_invocation_id == NEW_ID
        assert stored.logs is None


def test_changed_fresh_identity_never_overwrites_task_owned_status(app):
    with app.app_context():
        instance = _create_instance(status=InstanceStatus.RESTARTING)

        assert _reconcile(instance, _observation()) == 0

        stored = _stored(instance.id)
        assert stored.status is InstanceStatus.RESTARTING
        assert stored.runtime_invocation_id == OLD_ID
        assert stored.logs is None


def test_commit_failure_rolls_back_and_allows_a_later_retry(app, monkeypatch):
    with app.app_context():
        instance = _create_instance()
        original_commit = db.session.commit
        commit = Mock(side_effect=RuntimeError("database unavailable"))
        monkeypatch.setattr(db.session, "commit", commit)

        assert _reconcile(instance, _observation()) == 0

        stored = _stored(instance.id)
        assert stored.status is InstanceStatus.UPDATED
        assert stored.runtime_invocation_id == OLD_ID
        assert stored.logs is None

        monkeypatch.setattr(db.session, "commit", original_commit)
        assert _reconcile(instance, _observation()) == 1
        assert _stored(instance.id).status is InstanceStatus.RUNNING


def _replace_after_snapshot(snapshot, values):
    session_class = sessionmaker(bind=db.engine)

    def stale_snapshot(instance_id):
        with session_class() as other_session:
            other_session.execute(
                update(QLInstance).where(QLInstance.id == instance_id).values(**values)
            )
            other_session.commit()
        return snapshot

    return stale_snapshot


@pytest.mark.parametrize(
    "task_status",
    [
        InstanceStatus.DEPLOYING,
        InstanceStatus.DELETING,
        InstanceStatus.STOPPING,
        InstanceStatus.STARTING,
        InstanceStatus.RESTARTING,
        InstanceStatus.CONFIGURING,
    ],
)
def test_lost_promotion_race_preserves_every_task_owned_transition(app, monkeypatch, task_status):
    with app.app_context():
        from ui.task_logic import instance_runtime_reconciliation as reconciliation

        instance = _create_instance()
        snapshot = reconciliation.RuntimeSnapshot(instance.id, InstanceStatus.UPDATED, OLD_ID)
        monkeypatch.setattr(
            reconciliation,
            "_read_runtime_snapshot",
            _replace_after_snapshot(snapshot, {"status": task_status}),
        )

        assert _reconcile(instance, _observation()) == 0

        stored = _stored(instance.id)
        assert stored.status is task_status
        assert stored.runtime_invocation_id == OLD_ID
        assert stored.logs is None


def test_lost_promotion_race_preserves_replaced_baseline(app, monkeypatch):
    with app.app_context():
        from ui.task_logic import instance_runtime_reconciliation as reconciliation

        instance = _create_instance()
        snapshot = reconciliation.RuntimeSnapshot(instance.id, InstanceStatus.UPDATED, OLD_ID)
        monkeypatch.setattr(
            reconciliation,
            "_read_runtime_snapshot",
            _replace_after_snapshot(snapshot, {"runtime_invocation_id": REPLACEMENT_ID}),
        )

        assert _reconcile(instance, _observation()) == 0

        stored = _stored(instance.id)
        assert stored.status is InstanceStatus.UPDATED
        assert stored.runtime_invocation_id == REPLACEMENT_ID
        assert stored.logs is None


def test_lost_running_baseline_race_preserves_replaced_baseline(app, monkeypatch):
    with app.app_context():
        from ui.task_logic import instance_runtime_reconciliation as reconciliation

        instance = _create_instance(status=InstanceStatus.RUNNING)
        snapshot = reconciliation.RuntimeSnapshot(instance.id, InstanceStatus.RUNNING, OLD_ID)
        monkeypatch.setattr(
            reconciliation,
            "_read_runtime_snapshot",
            _replace_after_snapshot(snapshot, {"runtime_invocation_id": REPLACEMENT_ID}),
        )

        assert _reconcile(instance, _observation()) == 0

        stored = _stored(instance.id)
        assert stored.status is InstanceStatus.RUNNING
        assert stored.runtime_invocation_id == REPLACEMENT_ID
        assert stored.logs is None
