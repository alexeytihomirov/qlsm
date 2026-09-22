import json
from unittest.mock import Mock

from ui import job_events


def test_publish_job_event_serializes_payload(monkeypatch):
    fake = Mock()
    monkeypatch.setattr(job_events, "get_redis_client", lambda: fake)

    job_events.publish_job_event(
        "sample-addon.rebuild", "success", "Rebuilt sidecar for demo1.pack",
        instance_id=5, filename="demo1.pack",
    )

    fake.publish.assert_called_once()
    channel, raw = fake.publish.call_args[0]
    assert channel == job_events.JOB_EVENTS_CHANNEL
    payload = json.loads(raw)
    assert payload == {
        "source": "sample-addon.rebuild",
        "status": "success",
        "message": "Rebuilt sidecar for demo1.pack",
        "instance_id": 5,
        "filename": "demo1.pack",
    }


def test_publish_job_event_never_raises_on_redis_failure(monkeypatch, caplog):
    fake = Mock()
    fake.publish.side_effect = OSError("redis unreachable")
    monkeypatch.setattr(job_events, "get_redis_client", lambda: fake)

    job_events.publish_job_event("source", "error", "message")  # must not raise
