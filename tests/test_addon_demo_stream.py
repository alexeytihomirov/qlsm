"""The demo-stream addon's endpoints.

This port *adds* a UI rather than reproducing one -- the built-in feature has
four endpoints and no frontend at all -- so there is no parity risk, and what
is worth testing is that the addon refuses clearly instead of queueing work
that dies out of sight.
"""
import pytest

from ui import db
from ui.models import Host, HostStatus, InstanceStatus, QLInstance
from tests.helpers import auth_headers, make_user

ADDON = '/api/addons/demo-stream'


@pytest.fixture(autouse=True)
def no_redis_locks(monkeypatch):
    import ui.task_lock as task_lock

    monkeypatch.setattr(task_lock, 'acquire_lock', lambda *a, **kw: True)
    monkeypatch.setattr(task_lock, 'release_lock', lambda *a, **kw: True)


@pytest.fixture
def auth(app):
    make_user(app, 'streamop', 'pw')
    return auth_headers(app, 'streamop')


@pytest.fixture
def instance_id(app):
    with app.app_context():
        host = Host(name='germany', ip_address='10.0.0.1', provider='vultr',
                    status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.flush()
        instance = QLInstance(name='duel', port=27960, hostname='duel', host_id=host.id,
                              status=InstanceStatus.RUNNING)
        db.session.add(instance)
        db.session.commit()
        return instance.id


# ---- auth + not-found --------------------------------------------------

def test_relay_requires_auth(client):
    assert client.get(f'{ADDON}/relay').status_code == 401


def test_unknown_instance_is_404(client, auth):
    assert client.get(f'{ADDON}/instances/9999', headers=auth).status_code == 404


# ---- relay settings ----------------------------------------------------

def test_relay_round_trips_through_the_keys_core_uses(client, auth):
    """One store: the addon and the built-in Settings endpoint must not be
    able to disagree about where the relay is while both exist."""
    from ui.demo_stream_settings import get_relay_host, get_relay_port

    resp = client.put(f'{ADDON}/relay', headers=auth, json={'host': 'stats.example', 'port': '7788'})
    assert resp.status_code == 200

    with client.application.app_context():
        assert get_relay_host() == 'stats.example'
        assert get_relay_port() == '7788'

    assert client.get(f'{ADDON}/relay', headers=auth).get_json()['data'] == {
        'host': 'stats.example', 'port': '7788',
    }


def test_relay_rejects_a_non_numeric_port(client, auth):
    resp = client.put(f'{ADDON}/relay', headers=auth, json={'host': 'h', 'port': 'seven'})
    assert resp.status_code == 400


def test_relay_rejects_non_strings(client, auth):
    resp = client.put(f'{ADDON}/relay', headers=auth, json={'host': 5, 'port': '1'})
    assert resp.status_code == 400


def test_relay_can_be_cleared(client, auth):
    client.put(f'{ADDON}/relay', headers=auth, json={'host': 'h', 'port': '1'})
    client.put(f'{ADDON}/relay', headers=auth, json={'host': '', 'port': ''})
    assert client.get(f'{ADDON}/relay', headers=auth).get_json()['data'] == {'host': '', 'port': ''}


# ---- instance panel ----------------------------------------------------

def test_instance_reports_not_streaming_by_default(client, auth, instance_id):
    data = client.get(f'{ADDON}/instances/{instance_id}', headers=auth).get_json()['data']
    assert data == {'enabled': False}


def test_status_says_the_relay_is_unset_before_anything_else(client, auth, instance_id):
    """The operator's actual first question is "why can't I turn this on"."""
    data = client.get(f'{ADDON}/instances/{instance_id}/status', headers=auth).get_json()['data']
    assert data['ok'] is False
    assert 'Relay address not set' in data['label']


def test_enable_is_refused_until_the_relay_is_configured(client, auth, instance_id):
    resp = client.post(f'{ADDON}/instances/{instance_id}/enable', headers=auth)
    assert resp.status_code == 409
    assert 'relay' in resp.get_json()['error']['message'].lower()


def test_enable_queues_the_task_once_the_relay_is_set(client, auth, instance_id, monkeypatch):
    import ui.tasks as tasks
    from ui.demo_stream_settings import set_relay_host, set_relay_port

    queued = []
    monkeypatch.setattr(tasks, 'enqueue_task', lambda fn, *a, **kw: queued.append((fn.__name__, a)))

    with client.application.app_context():
        set_relay_host('stats.example')
        set_relay_port('7788')
        db.session.commit()

    resp = client.post(f'{ADDON}/instances/{instance_id}/enable', headers=auth)
    assert resp.status_code == 202
    assert queued and queued[0][0] == 'enable_instance_demo_stream_task'
    assert queued[0][1][0] == instance_id


def test_enable_is_refused_while_the_instance_is_busy(client, auth, instance_id):
    from ui.demo_stream_settings import set_relay_host, set_relay_port

    with client.application.app_context():
        set_relay_host('stats.example')
        set_relay_port('7788')
        db.session.get(QLInstance, instance_id).status = InstanceStatus.DEPLOYING
        db.session.commit()

    resp = client.post(f'{ADDON}/instances/{instance_id}/enable', headers=auth)
    assert resp.status_code == 409
    assert 'busy' in resp.get_json()['error']['message'].lower()


def test_turning_it_off_says_it_is_unsupported_rather_than_doing_nothing(client, auth, instance_id):
    """The built-in feature has no disable path. A toggle that silently
    no-ops is worse than one that explains itself."""
    resp = client.post(f'{ADDON}/instances/{instance_id}/enable', headers=auth,
                       json={'enabled': False})
    assert resp.status_code == 400
    assert 'not supported' in resp.get_json()['error']['message'].lower()


# ---- cleanup -----------------------------------------------------------

def test_deleting_an_instance_forgets_its_stream_state(app, instance_id):
    from ui.addons import registry
    from ui.demo_stream_settings import (
        get_instance_demo_stream_token, is_instance_demo_stream_enabled,
        set_instance_demo_stream_enabled, set_instance_demo_stream_token,
    )

    with app.app_context():
        set_instance_demo_stream_enabled(instance_id, True)
        set_instance_demo_stream_token(instance_id, 'tok')
        db.session.commit()

        registry.cleanup_scope('instance', instance_id, commit=True)

        assert is_instance_demo_stream_enabled(instance_id) is False
        assert get_instance_demo_stream_token(instance_id) is None
