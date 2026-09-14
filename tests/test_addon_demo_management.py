"""The demo-management addon's own endpoints.

The security-relevant filename validation lives in
ui/task_logic/ansible_instance_demos.py, which this addon calls rather than
copies -- tests/test_demos_validation.py covers it. What is tested here is
the addon's own wiring: auth, argument checking, and that a download really
comes back as a file rather than JSON (the table panel saves a blob, so a
JSON body would silently produce a corrupt "download").
"""
import io
import zipfile
from unittest.mock import patch

import pytest

from ui import db
from ui.models import Host, HostStatus, InstanceStatus, QLInstance
from tests.helpers import auth_headers, make_user

ADDON = '/api/addons/demo-management'

DEMOS = [
    {'name': '2026-09-14_duel_aerowalk.dm_91', 'size': 4718592, 'mtime': 1757800000},
    {'name': '2026-09-13_ca_toxicity.dm_91', 'size': 12058624, 'mtime': 1757700000},
]


@pytest.fixture
def auth(app):
    make_user(app, 'demoop', 'pw')
    return auth_headers(app, 'demoop')


@pytest.fixture
def instance_id(app):
    with app.app_context():
        host = Host(name='germany', ip_address='10.0.0.1', provider='vultr',
                    status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.flush()
        instance = QLInstance(name='duel srv', port=27960, hostname='duel', host_id=host.id,
                              status=InstanceStatus.RUNNING)
        db.session.add(instance)
        db.session.commit()
        return instance.id


# ---- auth + not-found --------------------------------------------------

def test_listing_requires_auth(client, instance_id):
    assert client.get(f'{ADDON}/instances/{instance_id}/demos').status_code == 401


def test_unknown_instance_is_404(client, auth):
    assert client.get(f'{ADDON}/instances/9999/demos', headers=auth).status_code == 404


# ---- listing -----------------------------------------------------------

def test_listing_returns_rows_under_the_key_the_manifest_declares(client, auth, instance_id):
    """The manifest says `rows: "demos"`; if the payload key ever changed the
    table would silently render empty."""
    with patch('ui.task_logic.ansible_instance_demos.list_instance_demos',
               return_value=(True, DEMOS, None)):
        resp = client.get(f'{ADDON}/instances/{instance_id}/demos', headers=auth)

    assert resp.status_code == 200
    body = resp.get_json()['data']
    assert [d['name'] for d in body['demos']] == [d['name'] for d in DEMOS]
    assert body['instance_name'] == 'duel srv'


def test_listing_surfaces_a_backend_failure(client, auth, instance_id):
    with patch('ui.task_logic.ansible_instance_demos.list_instance_demos',
               return_value=(False, None, 'ssh down')):
        resp = client.get(f'{ADDON}/instances/{instance_id}/demos', headers=auth)

    assert resp.status_code == 500
    assert resp.get_json()['error']['message'] == 'ssh down'


# ---- single download ---------------------------------------------------

def test_download_returns_a_file_not_json(client, auth, instance_id):
    name = DEMOS[0]['name']
    with patch('ui.task_logic.ansible_instance_demos.fetch_instance_demos',
               return_value=(True, {name: b'DEMOBYTES'}, [], None)):
        resp = client.get(f'{ADDON}/instances/{instance_id}/demos/download',
                          query_string={'filename': name}, headers=auth)

    assert resp.status_code == 200
    assert resp.data == b'DEMOBYTES'
    # The panel reads the filename off this header before saving the blob.
    assert name in resp.headers['Content-Disposition']


def test_download_without_a_filename_is_400(client, auth, instance_id):
    resp = client.get(f'{ADDON}/instances/{instance_id}/demos/download', headers=auth)
    assert resp.status_code == 400


def test_download_of_a_missing_file_is_404(client, auth, instance_id):
    name = DEMOS[0]['name']
    with patch('ui.task_logic.ansible_instance_demos.fetch_instance_demos',
               return_value=(True, {}, [name], None)):
        resp = client.get(f'{ADDON}/instances/{instance_id}/demos/download',
                          query_string={'filename': name}, headers=auth)
    assert resp.status_code == 404


# ---- batch download ----------------------------------------------------

def test_batch_zips_the_selection(client, auth, instance_id):
    names = [d['name'] for d in DEMOS]
    with patch('ui.task_logic.ansible_instance_demos.fetch_instance_demos',
               return_value=(True, {names[0]: b'AAA', names[1]: b'BBB'}, [], None)):
        resp = client.post(f'{ADDON}/instances/{instance_id}/demos/download-batch',
                           headers=auth, json={'filenames': names})

    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        assert sorted(zf.namelist()) == sorted(names)
        assert zf.read(names[0]) == b'AAA'


def test_the_manifest_mounts_the_built_in_demos_screen(client, auth, instance_id):
    """Since the parity fix this addon mounts QLSM's own Demos modal rather
    than a generic table, so there is no `selection_key` to keep in step -- the
    modal posts `filenames` directly, which is what this endpoint reads. The
    manifest is asserted here so a future switch back to a declarative panel
    cannot silently drop that agreement."""
    import json
    import os

    manifest_path = os.path.join(
        os.path.dirname(__file__), os.pardir, 'addons', 'demo-management', 'qlsm-addon.json')
    with open(manifest_path, encoding='utf-8') as f:
        manifest = json.load(f)

    entry = manifest['ui']['instance_menu'][0]
    assert entry['component'] == 'bundled:demos-modal'
    assert entry['renders'] == 'modal'
    assert not manifest['ui'].get('panels'), (
        'a declarative panel reappeared -- it must declare '
        'selection_key: "filenames" to match this endpoint'
    )


def test_batch_rejects_an_empty_selection(client, auth, instance_id):
    resp = client.post(f'{ADDON}/instances/{instance_id}/demos/download-batch',
                       headers=auth, json={'filenames': []})
    assert resp.status_code == 400


def test_batch_rejects_a_non_list(client, auth, instance_id):
    resp = client.post(f'{ADDON}/instances/{instance_id}/demos/download-batch',
                       headers=auth, json={'filenames': 'one.dm_91'})
    assert resp.status_code == 400


def test_batch_is_404_when_nothing_was_found(client, auth, instance_id):
    with patch('ui.task_logic.ansible_instance_demos.fetch_instance_demos',
               return_value=(True, {}, ['a.dm_91'], None)):
        resp = client.post(f'{ADDON}/instances/{instance_id}/demos/download-batch',
                           headers=auth, json={'filenames': ['a.dm_91']})
    assert resp.status_code == 404


def test_zip_name_is_sanitized_from_the_instance_name(client, auth, instance_id):
    """The instance name goes into a filename, so spaces and punctuation must
    not survive into the Content-Disposition header."""
    with patch('ui.task_logic.ansible_instance_demos.fetch_instance_demos',
               return_value=(True, {'a.dm_91': b'A'}, [], None)):
        resp = client.post(f'{ADDON}/instances/{instance_id}/demos/download-batch',
                           headers=auth, json={'filenames': ['a.dm_91']})

    assert 'duel-srv-demos.zip' in resp.headers['Content-Disposition']
