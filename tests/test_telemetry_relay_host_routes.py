import pytest
from unittest.mock import patch

from tests.helpers import make_user, auth_headers
from ui.database import create_host
from ui.models import HostStatus
from ui.telemetry_relay_settings import (
    get_host_stats_hub_ingest_token,
    get_host_stats_hub_url,
    set_relay_enabled,
    set_stats_hub_ingest_token,
    set_stats_hub_url,
)
from ui import db

DEFAULT_USER = 'relayadmin'
DEFAULT_PASS = 'relayadminp1'


@pytest.fixture(autouse=True)
def setup_user(app):
    make_user(app, DEFAULT_USER, DEFAULT_PASS)


def _headers(app):
    return auth_headers(app, DEFAULT_USER)


# --- GET/PUT /api/hosts/<id>/telemetry-relay/stats-hub ---

def test_get_stats_hub_override_defaults_to_global(client, app):
    with app.app_context():
        host = create_host(name='relay-h1', provider='vultr', status=HostStatus.ACTIVE)
        set_stats_hub_url('https://hub.example.com')
        set_stats_hub_ingest_token('global-token')
        db.session.commit()
        host_id = host.id

    resp = client.get(f'/api/hosts/{host_id}/telemetry-relay/stats-hub', headers=_headers(app))
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['url_override'] is None
    assert data['ingest_token_override'] is None
    assert data['effective_url'] == 'https://hub.example.com'
    assert data['effective_ingest_token'] == 'global-token'


def test_put_stats_hub_override_sets_and_returns_effective_values(client, app):
    with app.app_context():
        host = create_host(name='relay-h2', provider='vultr', status=HostStatus.ACTIVE)
        set_stats_hub_url('https://hub.example.com')
        set_stats_hub_ingest_token('global-token')
        db.session.commit()
        host_id = host.id

    with patch('ui.task_logic.ansible_telemetry_relay.push_relay_config_logic', return_value=True) as mock_push:
        resp = client.put(
            f'/api/hosts/{host_id}/telemetry-relay/stats-hub',
            headers=_headers(app),
            json={'url_override': 'https://hub-eu.example.com', 'ingest_token_override': 'host-token'},
        )
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['url_override'] == 'https://hub-eu.example.com'
    assert data['ingest_token_override'] == 'host-token'
    assert data['effective_url'] == 'https://hub-eu.example.com'
    assert data['effective_ingest_token'] == 'host-token'
    mock_push.assert_called_once_with(host_id)

    with app.app_context():
        assert get_host_stats_hub_url(host_id) == 'https://hub-eu.example.com'
        assert get_host_stats_hub_ingest_token(host_id) == 'host-token'


def test_put_stats_hub_override_clears_with_empty_string(client, app):
    with app.app_context():
        host = create_host(name='relay-h3', provider='vultr', status=HostStatus.ACTIVE)
        host_id = host.id

    with patch('ui.task_logic.ansible_telemetry_relay.push_relay_config_logic', return_value=True):
        client.put(
            f'/api/hosts/{host_id}/telemetry-relay/stats-hub',
            headers=_headers(app),
            json={'url_override': 'https://hub-eu.example.com', 'ingest_token_override': 'host-token'},
        )
        resp = client.put(
            f'/api/hosts/{host_id}/telemetry-relay/stats-hub',
            headers=_headers(app),
            json={'url_override': '', 'ingest_token_override': ''},
        )
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['url_override'] is None
    assert data['ingest_token_override'] is None


def test_put_stats_hub_override_rejects_non_string(client, app):
    with app.app_context():
        host = create_host(name='relay-h4', provider='vultr', status=HostStatus.ACTIVE)
        host_id = host.id

    resp = client.put(
        f'/api/hosts/{host_id}/telemetry-relay/stats-hub',
        headers=_headers(app),
        json={'url_override': 123, 'ingest_token_override': 'x'},
    )
    assert resp.status_code == 400


def test_get_stats_hub_override_host_not_found(client, app):
    resp = client.get('/api/hosts/999999/telemetry-relay/stats-hub', headers=_headers(app))
    assert resp.status_code == 404


# --- GET /api/hosts/<id>/telemetry-relay/status ---

def test_relay_status_disabled_skips_probe(client, app):
    with app.app_context():
        host = create_host(name='relay-h5', provider='vultr', status=HostStatus.ACTIVE)
        host_id = host.id

    with patch('ui.task_logic.ansible_telemetry_relay.run_host_ansible_adhoc') as mock_adhoc:
        resp = client.get(f'/api/hosts/{host_id}/telemetry-relay/status', headers=_headers(app))
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['enabled'] is False
    assert data['reachable'] is False
    assert data['routed_instances'] == []
    mock_adhoc.assert_not_called()


def test_relay_status_enabled_reports_health_and_instances(client, app):
    with app.app_context():
        host = create_host(name='relay-h6', provider='vultr', status=HostStatus.ACTIVE)
        set_relay_enabled(host.id, True)
        db.session.commit()
        host_id = host.id

    health_json = '{"ok": true, "service": "ql-telemetry-relay", "enabled": true, "routes": 0}'
    with patch(
        'ui.task_logic.ansible_telemetry_relay.run_host_ansible_adhoc',
        return_value=(True, health_json, ''),
    ):
        resp = client.get(f'/api/hosts/{host_id}/telemetry-relay/status', headers=_headers(app))
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['enabled'] is True
    assert data['reachable'] is True
    assert data['health']['service'] == 'ql-telemetry-relay'


def test_relay_status_unreachable_reports_error(client, app):
    with app.app_context():
        host = create_host(name='relay-h7', provider='vultr', status=HostStatus.ACTIVE)
        set_relay_enabled(host.id, True)
        db.session.commit()
        host_id = host.id

    with patch(
        'ui.task_logic.ansible_telemetry_relay.run_host_ansible_adhoc',
        return_value=(False, '', 'ssh: connect to host timed out'),
    ):
        resp = client.get(f'/api/hosts/{host_id}/telemetry-relay/status', headers=_headers(app))
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['reachable'] is False
    assert 'timed out' in data['error']


def test_relay_status_host_not_found(client, app):
    resp = client.get('/api/hosts/999999/telemetry-relay/status', headers=_headers(app))
    assert resp.status_code == 404
