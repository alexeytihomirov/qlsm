"""The telemetry-relay addon's own endpoints.

telemetry-relay is live in production, so this suite is mostly about the
behaviours that are *new* in the addon (one form instead of two buttons, an
up-front refusal instead of a task that fails on the host) rather than
re-testing the shared logic, which tests/test_telemetry_relay_*.py already
covers and which this addon calls rather than copies.
"""
import pytest

from ui import db
from ui.models import Host, HostStatus, InstanceStatus, QLInstance
from tests.helpers import auth_headers, make_user

ADDON = '/api/addons/telemetry-relay'


@pytest.fixture(autouse=True)
def no_redis_locks(monkeypatch):
    """The distributed lock needs Redis, which the test env does not run.

    Granting the lock rather than skipping the call keeps the endpoint's real
    code path -- acquire, mutate, queue, release -- under test; only the Redis
    round trip is replaced.
    """
    import ui.task_lock as task_lock

    monkeypatch.setattr(task_lock, 'acquire_lock', lambda *a, **kw: True)
    monkeypatch.setattr(task_lock, 'release_lock', lambda *a, **kw: True)


@pytest.fixture
def auth(app):
    make_user(app, 'relayop', 'pw')
    return auth_headers(app, 'relayop')


@pytest.fixture
def host_and_instance(app):
    with app.app_context():
        host = Host(name='germany', ip_address='10.0.0.1', provider='vultr',
                    status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.flush()
        instance = QLInstance(name='duel', port=27960, hostname='duel', host_id=host.id,
                              status=InstanceStatus.RUNNING)
        db.session.add(instance)
        db.session.commit()
        return host.id, instance.id


# ---- auth + not-found --------------------------------------------------

def test_host_panel_requires_auth(client, host_and_instance):
    host_id, _ = host_and_instance
    assert client.get(f'{ADDON}/hosts/{host_id}').status_code == 401


def test_unknown_host_is_404(client, auth):
    assert client.get(f'{ADDON}/hosts/9999', headers=auth).status_code == 404


def test_unknown_instance_is_404(client, auth):
    assert client.get(f'{ADDON}/instances/9999', headers=auth).status_code == 404


# ---- host panel --------------------------------------------------------

def test_host_panel_reports_defaults(client, auth, host_and_instance):
    host_id, _ = host_and_instance
    data = client.get(f'{ADDON}/hosts/{host_id}', headers=auth).get_json()['data']
    assert data == {'enabled': False, 'url_override': '', 'ingest_token_override': ''}


def test_overrides_round_trip_without_touching_the_relay(client, auth, host_and_instance, monkeypatch):
    """Saving with the toggle unchanged must not queue a host task -- it only
    re-pushes config, so editing a URL cannot knock a host into CONFIGURING."""
    import importlib

    relay = importlib.import_module('qlsm_addon_telemetry_relay.relay_ops')

    pushed = []
    monkeypatch.setattr(relay, 'push_relay_config_logic', lambda host_id: pushed.append(host_id))

    host_id, _ = host_and_instance
    resp = client.put(f'{ADDON}/hosts/{host_id}', headers=auth, json={
        'enabled': False,
        'url_override': 'https://hub.example/',
        'ingest_token_override': 'secret',
    })
    assert resp.status_code == 200
    assert pushed == [host_id]

    data = client.get(f'{ADDON}/hosts/{host_id}', headers=auth).get_json()['data']
    assert data['url_override'] == 'https://hub.example'   # trailing slash normalized
    assert data['ingest_token_override'] == 'secret'

    with client.application.app_context():
        assert db.session.get(Host, host_id).status == HostStatus.ACTIVE


def test_overrides_are_persisted_before_the_enable_task_is_queued(client, auth, host_and_instance, monkeypatch):
    """A relay being switched on must be configured with the values the
    operator just typed. The built-in UI had two separate buttons; collapsing
    them into one form is exactly where this would be easy to get backwards,
    so the ordering is pinned here: at the moment the task is queued, the new
    override must already be readable."""
    import ui.tasks as tasks
    from ui.stats_hub import get_host_stats_hub_url

    host_id, _ = host_and_instance
    seen = {}

    def _capture(fn, *args, **kwargs):
        seen['url_at_queue_time'] = get_host_stats_hub_url(host_id)

    monkeypatch.setattr(tasks, 'enqueue_task', _capture)

    resp = client.put(f'{ADDON}/hosts/{host_id}', headers=auth, json={
        'enabled': True,
        'url_override': 'https://new-hub.example',
        'ingest_token_override': 'fresh',
    })
    assert resp.status_code == 202
    assert seen['url_at_queue_time'] == 'https://new-hub.example'


def test_enabling_queues_a_host_task(client, auth, host_and_instance, monkeypatch):
    import ui.tasks as tasks

    queued = []
    monkeypatch.setattr(tasks, 'enqueue_task', lambda fn, *a, **kw: queued.append((fn.__name__, a)))

    host_id, _ = host_and_instance
    resp = client.put(f'{ADDON}/hosts/{host_id}', headers=auth, json={
        'enabled': True, 'url_override': '', 'ingest_token_override': '',
    })
    assert resp.status_code == 202
    assert queued and queued[0][0] == 'configure_host_relay'
    assert queued[0][1][0] == host_id


def test_enabling_is_refused_while_the_host_is_not_active(client, auth, host_and_instance):
    host_id, _ = host_and_instance
    with client.application.app_context():
        db.session.get(Host, host_id).status = HostStatus.CONFIGURING
        db.session.commit()

    resp = client.put(f'{ADDON}/hosts/{host_id}', headers=auth, json={
        'enabled': True, 'url_override': '', 'ingest_token_override': '',
    })
    assert resp.status_code == 400
    assert 'ACTIVE' in resp.get_json()['error']['message']


def test_non_string_override_is_rejected(client, auth, host_and_instance):
    host_id, _ = host_and_instance
    resp = client.put(f'{ADDON}/hosts/{host_id}', headers=auth, json={
        'enabled': False, 'url_override': 123, 'ingest_token_override': '',
    })
    assert resp.status_code == 400


# ---- global stats-hub --------------------------------------------------

def test_stats_hub_round_trips_through_the_same_keys_core_uses(client, auth):
    """One store, one reader: the addon must not create a second source of
    truth for a production credential while both code paths exist."""
    from ui.stats_hub import get_stats_hub_ingest_token, get_stats_hub_url

    resp = client.put(f'{ADDON}/stats-hub', headers=auth,
                      json={'url': 'https://hub.example/', 'ingest_token': 'ingest-abc'})
    assert resp.status_code == 200

    with client.application.app_context():
        assert get_stats_hub_url() == 'https://hub.example'
        assert get_stats_hub_ingest_token() == 'ingest-abc'

    data = client.get(f'{ADDON}/stats-hub', headers=auth).get_json()['data']
    assert data == {'url': 'https://hub.example', 'ingest_token': 'ingest-abc'}


def test_stats_hub_rejects_non_strings(client, auth):
    resp = client.put(f'{ADDON}/stats-hub', headers=auth, json={'url': None, 'ingest_token': 5})
    assert resp.status_code == 400


# ---- instance telemetry ------------------------------------------------

def test_instance_panel_reports_zero_when_never_reserved(client, auth, host_and_instance):
    _, instance_id = host_and_instance
    data = client.get(f'{ADDON}/instances/{instance_id}', headers=auth).get_json()['data']
    assert data == {'server_id': 0}


def test_enable_is_refused_when_the_host_relay_is_off(client, auth, host_and_instance):
    """Refusing here, with a reason, beats queueing a task that fails on the
    host with nothing readable in the UI."""
    _, instance_id = host_and_instance
    resp = client.post(f'{ADDON}/instances/{instance_id}/enable', headers=auth)
    assert resp.status_code == 409
    assert 'relay' in resp.get_json()['error']['message'].lower()


def test_enable_is_refused_when_stats_hub_is_unconfigured(client, auth, host_and_instance):
    from qlsm_addon_telemetry_relay.settings import set_relay_enabled

    host_id, instance_id = host_and_instance
    with client.application.app_context():
        set_relay_enabled(host_id, True)
        db.session.commit()

    resp = client.post(f'{ADDON}/instances/{instance_id}/enable', headers=auth)
    assert resp.status_code == 409
    assert 'stats-hub' in resp.get_json()['error']['message'].lower()


def test_enable_queues_the_task_once_prerequisites_are_met(client, auth, host_and_instance, monkeypatch):
    import ui.tasks as tasks
    from qlsm_addon_telemetry_relay.settings import set_relay_enabled
    from ui.stats_hub import set_stats_hub_ingest_token, set_stats_hub_url

    queued = []
    monkeypatch.setattr(tasks, 'enqueue_task', lambda fn, *a, **kw: queued.append((fn.__name__, a)))

    host_id, instance_id = host_and_instance
    with client.application.app_context():
        set_relay_enabled(host_id, True)
        set_stats_hub_url('https://hub.example')
        set_stats_hub_ingest_token('ingest-abc')
        db.session.commit()

    resp = client.post(f'{ADDON}/instances/{instance_id}/enable', headers=auth)
    assert resp.status_code == 202
    assert queued and queued[0][0] == 'enable_instance_telemetry_task'
    assert queued[0][1][0] == instance_id


def test_enable_is_refused_while_the_instance_is_busy(client, auth, host_and_instance):
    from qlsm_addon_telemetry_relay.settings import set_relay_enabled
    from ui.stats_hub import set_stats_hub_ingest_token, set_stats_hub_url

    host_id, instance_id = host_and_instance
    with client.application.app_context():
        set_relay_enabled(host_id, True)
        set_stats_hub_url('https://hub.example')
        set_stats_hub_ingest_token('ingest-abc')
        db.session.get(QLInstance, instance_id).status = InstanceStatus.DEPLOYING
        db.session.commit()

    resp = client.post(f'{ADDON}/instances/{instance_id}/enable', headers=auth)
    assert resp.status_code == 409
    assert 'busy' in resp.get_json()['error']['message'].lower()


# ---- cleanup hooks -----------------------------------------------------

def test_deleting_a_host_forgets_its_relay_settings(app, host_and_instance):
    from qlsm_addon_telemetry_relay.settings import is_relay_enabled, set_relay_enabled
    from ui.addons import registry
    from ui.stats_hub import get_host_stats_hub_url, set_host_stats_hub_url

    host_id, _ = host_and_instance
    with app.app_context():
        set_relay_enabled(host_id, True)
        set_host_stats_hub_url(host_id, 'https://hub.example')
        db.session.commit()

        registry.cleanup_scope('host', host_id, commit=True)

        assert is_relay_enabled(host_id) is False
        assert get_host_stats_hub_url(host_id) is None


def test_deleting_an_instance_forgets_its_server_id(app, host_and_instance):
    from ui.addons import registry
    from ui.stats_hub import get_instance_server_id, set_instance_server_id

    _, instance_id = host_and_instance
    with app.app_context():
        set_instance_server_id(instance_id, 42)
        db.session.commit()

        registry.cleanup_scope('instance', instance_id, commit=True)

        assert get_instance_server_id(instance_id) is None
