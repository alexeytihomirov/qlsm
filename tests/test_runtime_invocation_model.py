from ui import db
from ui.database import create_host, create_instance
from ui.models import HostStatus, QLInstance
from ui.task_logic.backup_db_export import serialize_database


def test_runtime_invocation_id_is_persisted_but_not_public_or_backed_up(app):
    with app.app_context():
        host = create_host(
            name="runtime-id-host",
            provider="standalone",
            status=HostStatus.ACTIVE,
        )
        instance = create_instance(
            name="runtime-id-instance",
            host_id=host.id,
            port=27960,
            hostname="Runtime ID Test",
        )
        instance.runtime_invocation_id = "a" * 32
        db.session.commit()
        instance_id = instance.id
        db.session.expunge_all()

        stored = db.session.get(QLInstance, instance_id)
        assert stored.runtime_invocation_id == "a" * 32
        assert "runtime_invocation_id" not in stored.to_dict()

        exported = serialize_database()
        assert "runtime_invocation_id" not in exported["instances"][0]
