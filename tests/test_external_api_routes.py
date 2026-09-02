from unittest.mock import patch

import pytest
from tests.helpers import make_user, auth_headers
from ui import db
from ui.models import ApiKey, Host, HostStatus
from ui.database import create_host, create_instance

DEMOS_MODULE = 'ui.task_logic.ansible_instance_demos'


def _generate_key(client, app):
    """Helper: generate an API key and return the plaintext."""
    make_user(app, 'admin', 'password1')
    headers = auth_headers(app, 'admin')
    resp = client.post('/api/settings/api-key', headers=headers)
    return resp.get_json()['data']['key']


def _create_test_instance(app):
    """Helper: create a host with one instance, return instance id."""
    with app.app_context():
        host = create_host(name='ext-test-host', provider='vultr',
                           status=HostStatus.ACTIVE, ip_address='10.0.0.1')
        inst = create_instance(name='ext-test-inst', host_id=host.id,
                               port=27960, hostname='test.server.com')
        inst.zmq_stats_port = 29999
        inst.zmq_stats_password = 'stats_secret'
        inst.zmq_rcon_port = 28888
        inst.zmq_rcon_password = 'rcon_secret'
        db.session.commit()
        return inst.id


# --- Authentication ---

def test_external_api_no_auth(client):
    """Missing Authorization header returns 401."""
    resp = client.get('/api/v1/instances')
    assert resp.status_code == 401
    assert 'Missing' in resp.get_json()['error']['message']


def test_external_api_invalid_key(client, app):
    """Invalid Bearer token returns 401."""
    _generate_key(client, app)
    resp = client.get('/api/v1/instances',
                      headers={'Authorization': 'Bearer bad-key'})
    assert resp.status_code == 401
    assert 'Invalid' in resp.get_json()['error']['message']


def test_external_api_valid_key(client, app):
    """Valid Bearer token returns 200 with instance data."""
    key = _generate_key(client, app)
    _create_test_instance(app)
    resp = client.get('/api/v1/instances',
                      headers={'Authorization': f'Bearer {key}'})
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert len(data) == 1
    assert data[0]['name'] == 'ext-test-inst'


def test_external_api_revoked_key(client, app):
    """Revoked key returns 401."""
    key = _generate_key(client, app)
    jwt_headers = auth_headers(app, 'admin')
    client.delete('/api/settings/api-key', headers=jwt_headers)
    resp = client.get('/api/v1/instances',
                      headers={'Authorization': f'Bearer {key}'})
    assert resp.status_code == 401


def test_external_api_regenerated_old_key_fails(client, app):
    """After regeneration, old key no longer works."""
    old_key = _generate_key(client, app)
    jwt_headers = auth_headers(app, 'admin')
    resp = client.post('/api/settings/api-key', headers=jwt_headers)
    new_key = resp.get_json()['data']['key']
    assert old_key != new_key
    # Old key should fail
    resp = client.get('/api/v1/instances',
                      headers={'Authorization': f'Bearer {old_key}'})
    assert resp.status_code == 401
    # New key should work
    resp = client.get('/api/v1/instances',
                      headers={'Authorization': f'Bearer {new_key}'})
    assert resp.status_code == 200


# --- Response field exclusion ---

def test_excludes_rcon_fields(client, app):
    """Response must not contain zmq_rcon_port or zmq_rcon_password."""
    key = _generate_key(client, app)
    _create_test_instance(app)
    resp = client.get('/api/v1/instances',
                      headers={'Authorization': f'Bearer {key}'})
    inst = resp.get_json()['data'][0]
    assert 'zmq_rcon_port' not in inst
    assert 'zmq_rcon_password' not in inst


def test_excludes_logs_and_config(client, app):
    """Response must not contain logs or config."""
    key = _generate_key(client, app)
    _create_test_instance(app)
    resp = client.get('/api/v1/instances',
                      headers={'Authorization': f'Bearer {key}'})
    inst = resp.get_json()['data'][0]
    assert 'logs' not in inst
    assert 'config' not in inst


def test_includes_zmq_stats_fields(client, app):
    """Response includes zmq_stats_port and zmq_stats_password."""
    key = _generate_key(client, app)
    _create_test_instance(app)
    resp = client.get('/api/v1/instances',
                      headers={'Authorization': f'Bearer {key}'})
    inst = resp.get_json()['data'][0]
    assert inst['zmq_stats_port'] == 29999
    assert inst['zmq_stats_password'] == 'stats_secret'


def test_includes_host_details(client, app):
    """Response includes host_name and host_ip_address."""
    key = _generate_key(client, app)
    _create_test_instance(app)
    resp = client.get('/api/v1/instances',
                      headers={'Authorization': f'Bearer {key}'})
    inst = resp.get_json()['data'][0]
    assert inst['host_name'] == 'ext-test-host'
    assert inst['host_ip_address'] == '10.0.0.1'
    assert inst['port'] == 27960


def test_returns_all_instances(client, app):
    """Returns all instances regardless of status."""
    key = _generate_key(client, app)
    with app.app_context():
        host = create_host(name='multi-host', provider='vultr',
                           status=HostStatus.ACTIVE, ip_address='10.0.0.2')
        create_instance(name='inst-a', host_id=host.id, port=27960,
                        hostname='a.test.com')
        create_instance(name='inst-b', host_id=host.id, port=27961,
                        hostname='b.test.com')
        create_instance(name='inst-c', host_id=host.id, port=27962,
                        hostname='c.test.com')
        db.session.commit()
    resp = client.get('/api/v1/instances',
                      headers={'Authorization': f'Bearer {key}'})
    assert resp.status_code == 200
    assert len(resp.get_json()['data']) == 3


# --- Match (.qlmatch) listing and download ---

def test_matches_list_no_auth(client, app):
    """Missing Authorization header returns 401 before touching task logic."""
    instance_id = _create_test_instance(app)
    with patch(f'{DEMOS_MODULE}.list_instance_demos') as mock_list:
        resp = client.get(f'/api/v1/instances/{instance_id}/matches')
    assert resp.status_code == 401
    mock_list.assert_not_called()


def test_matches_list_missing_instance_returns_404(client, app):
    key = _generate_key(client, app)
    with patch(f'{DEMOS_MODULE}.list_instance_demos') as mock_list:
        resp = client.get('/api/v1/instances/999999/matches',
                          headers={'Authorization': f'Bearer {key}'})
    assert resp.status_code == 404
    mock_list.assert_not_called()


def _fake_manifest_read(manifests):
    """Build a read_qlmatch_manifest side_effect from {filename: (match_id, map)}."""
    def _read(instance_id, filename):
        if filename not in manifests:
            return False, None, 'no manifest'
        match_id, map_name = manifests[filename]
        return True, {'match_id': match_id, 'map': map_name}, None
    return _read


@patch(f'{DEMOS_MODULE}.read_qlmatch_manifest', side_effect=_fake_manifest_read({
    # Pack filename is templated (qlx_qlmatchNameTemplate) and does NOT
    # share a base name with its sidecar - has_replay must come from the
    # pack's manifest.json (match_id/map), not from editing this filename.
    'duel_phrantic_Input-a3.qlmatch': ('20260827T170920Z', 'phrantic'),
    'nopair.qlmatch': ('20260827T180000Z', 'phrantic'),
}))
@patch(f'{DEMOS_MODULE}.list_instance_demos', return_value=(
    True,
    [
        {'name': '20260827T170920Z_phrantic.replay.json.gz', 'size': 30, 'mtime': 3.0},
        {'name': 'duel_phrantic_Input-a3.qlmatch', 'size': 20, 'mtime': 2.0},
        {'name': 'nopair.qlmatch', 'size': 10, 'mtime': 1.0},
        {'name': '20260827T170920Z_phrantic_p0_a3_1_1.dm_91', 'size': 5, 'mtime': 2.5},
    ],
    None,
))
def test_matches_list_filters_to_qlmatch_and_flags_replay(mock_list, mock_manifest, client, app):
    key = _generate_key(client, app)
    instance_id = _create_test_instance(app)
    resp = client.get(f'/api/v1/instances/{instance_id}/matches',
                      headers={'Authorization': f'Bearer {key}'})
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['instance_name'] == 'ext-test-inst'
    matches = {m['name']: m for m in data['matches']}
    assert set(matches) == {'duel_phrantic_Input-a3.qlmatch', 'nopair.qlmatch'}
    assert matches['duel_phrantic_Input-a3.qlmatch']['has_replay'] is True
    assert matches['duel_phrantic_Input-a3.qlmatch']['replay_name'] == \
        '20260827T170920Z_phrantic.replay.json.gz'
    assert matches['nopair.qlmatch']['has_replay'] is False
    assert matches['nopair.qlmatch']['replay_name'] is None
    mock_list.assert_called_once_with(instance_id)


@patch(f'{DEMOS_MODULE}.list_instance_demos', return_value=(False, [], 'boom'))
def test_matches_list_failure_returns_500(mock_list, client, app):
    key = _generate_key(client, app)
    instance_id = _create_test_instance(app)
    resp = client.get(f'/api/v1/instances/{instance_id}/matches',
                      headers={'Authorization': f'Bearer {key}'})
    assert resp.status_code == 500
    assert resp.get_json()['error']['message'] == 'boom'


def test_match_download_no_auth(client, app):
    instance_id = _create_test_instance(app)
    with patch(f'{DEMOS_MODULE}.fetch_instance_demos') as mock_fetch:
        resp = client.get(f'/api/v1/instances/{instance_id}/matches/download',
                          query_string={'filename': 'a.qlmatch'})
    assert resp.status_code == 401
    mock_fetch.assert_not_called()


@patch(f'{DEMOS_MODULE}.fetch_instance_demos', return_value=(True, {'a.qlmatch': b'zip-bytes'}, [], None))
def test_match_download_returns_file_bytes(mock_fetch, client, app):
    key = _generate_key(client, app)
    instance_id = _create_test_instance(app)
    resp = client.get(f'/api/v1/instances/{instance_id}/matches/download',
                      query_string={'filename': 'a.qlmatch'},
                      headers={'Authorization': f'Bearer {key}'})
    assert resp.status_code == 200
    assert resp.data == b'zip-bytes'
    assert resp.mimetype == 'application/octet-stream'
    mock_fetch.assert_called_once_with(instance_id, ['a.qlmatch'])


def test_match_download_wrong_suffix_rejected_before_task_logic(client, app):
    key = _generate_key(client, app)
    instance_id = _create_test_instance(app)
    with patch(f'{DEMOS_MODULE}.fetch_instance_demos') as mock_fetch:
        resp = client.get(f'/api/v1/instances/{instance_id}/matches/download',
                          query_string={'filename': 'a.replay.json.gz'},
                          headers={'Authorization': f'Bearer {key}'})
    assert resp.status_code == 400
    mock_fetch.assert_not_called()


@patch(f'{DEMOS_MODULE}.fetch_instance_demos', return_value=(True, {}, ['a.qlmatch'], None))
def test_match_download_missing_file_returns_404(mock_fetch, client, app):
    key = _generate_key(client, app)
    instance_id = _create_test_instance(app)
    resp = client.get(f'/api/v1/instances/{instance_id}/matches/download',
                      query_string={'filename': 'a.qlmatch'},
                      headers={'Authorization': f'Bearer {key}'})
    assert resp.status_code == 404


@patch(f'{DEMOS_MODULE}.fetch_instance_demos', return_value=(True, {'a.replay.json.gz': b'gz-bytes'}, [], None))
def test_match_replay_download_returns_file_bytes(mock_fetch, client, app):
    key = _generate_key(client, app)
    instance_id = _create_test_instance(app)
    resp = client.get(f'/api/v1/instances/{instance_id}/matches/replay',
                      query_string={'filename': 'a.replay.json.gz'},
                      headers={'Authorization': f'Bearer {key}'})
    assert resp.status_code == 200
    assert resp.data == b'gz-bytes'
    mock_fetch.assert_called_once_with(instance_id, ['a.replay.json.gz'])


def test_match_replay_download_wrong_suffix_rejected_before_task_logic(client, app):
    key = _generate_key(client, app)
    instance_id = _create_test_instance(app)
    with patch(f'{DEMOS_MODULE}.fetch_instance_demos') as mock_fetch:
        resp = client.get(f'/api/v1/instances/{instance_id}/matches/replay',
                          query_string={'filename': 'a.qlmatch'},
                          headers={'Authorization': f'Bearer {key}'})
    assert resp.status_code == 400
    mock_fetch.assert_not_called()
