import json

import pytest
from tests.helpers import make_user, auth_headers
from ui.models import PluginRepository
from ui import db
import ui.plugin_repositories as plugin_repositories
import ui.routes.plugin_repository_routes as plugin_repository_routes
from ui.plugin_repositories import PluginRepositoryError


PLUGIN_LIST = [
    {'filename': 'balance2.py', 'label': 'Balance', 'description': None,
     'runtime': 'minqlx', 'version': None, 'sha256': None,
     'requires_qlsm_version': None},
]

ADDON_LIST = [
    {'id': 'demo-addon', 'zip': 'demo-addon.zip', 'label': 'Demo', 'description': None,
     'version': '1.2.0', 'sha256': None, 'requires_qlsm_version': None},
]


def _patch_fetch(monkeypatch, plugins=None, addons=None, error=None):
    def fake_fetch_manifest(url):
        if error:
            raise PluginRepositoryError(error)
        return {
            'plugins': plugins if plugins is not None else list(PLUGIN_LIST),
            'addons': addons if addons is not None else [],
        }
    monkeypatch.setattr(plugin_repository_routes, 'fetch_manifest', fake_fetch_manifest)


def _seeded_repo(name, url, plugins=None, addons=None):
    """A PluginRepository as it looks right after a real sync -- unlike a bare
    db.session.add(), this populates manifest_json, which to_dict()['plugins']
    (and the download route's lookup) reads from. Creating a repo without this
    and then asserting on its plugin list is the bug three of these tests
    originally had (caught by CI, not locally -- see commit history)."""
    repo = PluginRepository(name=name, url=url)
    repo.manifest_json = json.dumps({
        'plugins': plugins if plugins is not None else list(PLUGIN_LIST),
        'addons': addons if addons is not None else [],
    })
    db.session.add(repo)
    db.session.commit()
    return repo


# --- GET /api/plugin-repositories/ ---

def test_list_repositories_authenticated(client, app, monkeypatch):
    _patch_fetch(monkeypatch)
    make_user(app, 'listuser1', 'password123')
    headers = auth_headers(app, 'listuser1')
    with app.app_context():
        db.session.add(PluginRepository(name='Repo A', url='https://example.com/a'))
        db.session.commit()
    response = client.get('/api/plugin-repositories/', headers=headers)
    assert response.status_code == 200
    data = response.get_json()['data']
    assert len(data) == 1
    assert data[0]['name'] == 'Repo A'
    # Never synced -- manifest_json is unset, so the plugin list is empty.
    assert data[0]['plugins'] == []


def test_list_repositories_unauthenticated(client, app):
    response = client.get('/api/plugin-repositories/')
    assert response.status_code == 401


# --- POST /api/plugin-repositories/ ---

def test_create_repository_syncs_immediately(client, app, monkeypatch):
    _patch_fetch(monkeypatch)
    make_user(app, 'creator', 'creatorpass')
    headers = auth_headers(app, 'creator')
    response = client.post('/api/plugin-repositories/', headers=headers, json={
        'name': 'My Repo', 'url': 'https://example.com/repo',
    })
    assert response.status_code == 201
    data = response.get_json()['data']
    assert data['name'] == 'My Repo'
    assert data['last_synced_at'] is not None
    assert data['last_sync_error'] is None
    assert [p['filename'] for p in data['plugins']] == ['balance2.py']


def test_create_repository_stores_sync_error_but_still_creates(client, app, monkeypatch):
    _patch_fetch(monkeypatch, error='boom')
    make_user(app, 'creator2', 'creatorpass')
    headers = auth_headers(app, 'creator2')
    response = client.post('/api/plugin-repositories/', headers=headers, json={
        'name': 'Broken Repo', 'url': 'https://example.com/broken',
    })
    assert response.status_code == 201
    data = response.get_json()['data']
    assert data['last_sync_error'] == 'boom'
    assert data['plugins'] == []


def test_create_repository_rejects_bad_url(client, app):
    make_user(app, 'creator3', 'creatorpass')
    headers = auth_headers(app, 'creator3')
    response = client.post('/api/plugin-repositories/', headers=headers, json={
        'name': 'Bad', 'url': 'not-a-url',
    })
    assert response.status_code == 400


def test_create_repository_rejects_duplicate_name(client, app, monkeypatch):
    _patch_fetch(monkeypatch)
    make_user(app, 'creator4', 'creatorpass')
    headers = auth_headers(app, 'creator4')
    client.post('/api/plugin-repositories/', headers=headers, json={
        'name': 'Dup', 'url': 'https://example.com/a',
    })
    response = client.post('/api/plugin-repositories/', headers=headers, json={
        'name': 'Dup', 'url': 'https://example.com/b',
    })
    assert response.status_code == 409


def test_create_repository_rejects_duplicate_name_ignoring_case(client, app, monkeypatch):
    _patch_fetch(monkeypatch)
    make_user(app, 'creator5', 'creatorpass')
    headers = auth_headers(app, 'creator5')
    client.post('/api/plugin-repositories/', headers=headers, json={
        'name': 'Dup', 'url': 'https://example.com/a',
    })
    response = client.post('/api/plugin-repositories/', headers=headers, json={
        'name': 'dup', 'url': 'https://example.com/b',
    })
    assert response.status_code == 409


def test_create_repository_rejects_duplicate_url_ignoring_trailing_slash(client, app, monkeypatch):
    _patch_fetch(monkeypatch)
    make_user(app, 'creator6', 'creatorpass')
    headers = auth_headers(app, 'creator6')
    client.post('/api/plugin-repositories/', headers=headers, json={
        'name': 'First', 'url': 'https://example.com/a',
    })
    response = client.post('/api/plugin-repositories/', headers=headers, json={
        'name': 'Second', 'url': 'https://example.com/a/',
    })
    assert response.status_code == 409
    assert "'First'" in response.get_json()['error']['message']


# --- POST /api/plugin-repositories/<id>/sync ---

def test_sync_updates_plugin_list(client, app, monkeypatch):
    _patch_fetch(monkeypatch)
    make_user(app, 'syncuser', 'password123')
    headers = auth_headers(app, 'syncuser')
    with app.app_context():
        repo = PluginRepository(name='Repo B', url='https://example.com/b')
        db.session.add(repo)
        db.session.commit()
        repo_id = repo.id

    _patch_fetch(monkeypatch, plugins=[
        {'filename': 'new_plugin.py', 'label': None, 'description': None,
         'runtime': None, 'requires_qlsm_version': None},
    ])
    response = client.post(f'/api/plugin-repositories/{repo_id}/sync', headers=headers)
    assert response.status_code == 200
    assert [p['filename'] for p in response.get_json()['data']['plugins']] == ['new_plugin.py']


def test_sync_missing_repo_404(client, app):
    make_user(app, 'syncuser2', 'password123')
    headers = auth_headers(app, 'syncuser2')
    response = client.post('/api/plugin-repositories/9999/sync', headers=headers)
    assert response.status_code == 404


def test_sync_reports_fetch_failure(client, app, monkeypatch):
    _patch_fetch(monkeypatch)
    make_user(app, 'syncuser3', 'password123')
    headers = auth_headers(app, 'syncuser3')
    with app.app_context():
        repo = PluginRepository(name='Repo C', url='https://example.com/c')
        db.session.add(repo)
        db.session.commit()
        repo_id = repo.id

    _patch_fetch(monkeypatch, error='unreachable')
    response = client.post(f'/api/plugin-repositories/{repo_id}/sync', headers=headers)
    assert response.status_code == 422
    assert response.get_json()['error']['message'] == 'unreachable'


def test_sync_resolves_a_github_url_whose_first_sync_failed(client, app, monkeypatch):
    """Adding a github.com repo before its manifest is pushed used to strand it.

    Resolution to the raw base only ran inside the create-time sync, so when
    that sync failed the stored URL stayed the github.com HTML address and
    every later sync re-fetched it forever -- delete-and-re-add was the only
    way out. Sync now retries the resolution for an unresolved github URL.
    """
    make_user(app, 'ghuser', 'password123')
    headers = auth_headers(app, 'ghuser')

    # First sync fails: the operator added the repo before pushing the manifest.
    _patch_fetch(monkeypatch, error='404')
    response = client.post(
        '/api/plugin-repositories/',
        headers=headers,
        json={'name': 'GH Repo', 'url': 'https://github.com/owner/repo'},
    )
    assert response.status_code == 201
    repo_id = response.get_json()['data']['id']
    with app.app_context():
        stranded = db.session.get(PluginRepository, repo_id)
        assert stranded.url == 'https://github.com/owner/repo'
        assert stranded.display_url is None

    # The manifest is now there; syncing must resolve rather than re-fetch HTML.
    _patch_fetch(monkeypatch, plugins=[
        {'filename': 'later.py', 'label': None, 'description': None,
         'runtime': None, 'requires_qlsm_version': None},
    ])
    response = client.post(f'/api/plugin-repositories/{repo_id}/sync', headers=headers)
    assert response.status_code == 200
    assert [p['filename'] for p in response.get_json()['data']['plugins']] == ['later.py']

    with app.app_context():
        fixed = db.session.get(PluginRepository, repo_id)
        assert fixed.url == 'https://raw.githubusercontent.com/owner/repo/main/'
        # What the operator typed is kept for display once it was rewritten.
        assert fixed.display_url == 'https://github.com/owner/repo'


# --- DELETE /api/plugin-repositories/<id> ---

def test_delete_repository(client, app, monkeypatch):
    _patch_fetch(monkeypatch)
    make_user(app, 'deluser', 'password123')
    headers = auth_headers(app, 'deluser')
    with app.app_context():
        repo = PluginRepository(name='Repo D', url='https://example.com/d')
        db.session.add(repo)
        db.session.commit()
        repo_id = repo.id

    response = client.delete(f'/api/plugin-repositories/{repo_id}', headers=headers)
    assert response.status_code == 200
    with app.app_context():
        assert db.session.get(PluginRepository, repo_id) is None


# --- POST /api/plugin-repositories/<id>/download ---

def test_download_uses_the_manifests_own_runtime(client, app, monkeypatch):
    _patch_fetch(monkeypatch, error='offline')
    make_user(app, 'dlruntime', 'password123')
    headers = auth_headers(app, 'dlruntime')
    with app.app_context():
        repo = _seeded_repo('Repo E', 'https://example.com/e')
        repo_id = repo.id

    calls = []
    monkeypatch.setattr(
        plugin_repository_routes, 'download_plugin',
        lambda base_url, filename, runtime, overwrite=False, inline_manifest=None: calls.append((base_url, filename, runtime)),
    )
    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['balance2.py']},
    )
    assert response.status_code == 200
    assert response.get_json()['downloaded'] == ['balance2.py']
    assert calls == [('https://example.com/e', 'balance2.py', 'minqlx')]


def test_download_requires_a_runtime_when_manifest_has_none(client, app, monkeypatch):
    _patch_fetch(monkeypatch, error='offline')
    make_user(app, 'dlnoruntime', 'password123')
    headers = auth_headers(app, 'dlnoruntime')
    with app.app_context():
        repo = _seeded_repo('Repo F', 'https://example.com/f', plugins=[
            {'filename': 'no_runtime.py', 'label': None, 'description': None,
             'runtime': None, 'requires_qlsm_version': None},
        ])
        repo_id = repo.id

    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['no_runtime.py']},
    )
    assert response.status_code == 422
    assert response.get_json()['downloaded'] == []
    assert response.get_json()['errors'][0]['filename'] == 'no_runtime.py'


def test_download_picked_runtime_does_not_override_declared_runtime(client, app, monkeypatch):
    _patch_fetch(monkeypatch, error='offline')
    make_user(app, 'dloverride', 'password123')
    headers = auth_headers(app, 'dloverride')
    with app.app_context():
        # One entry declares minqlx, the other declares nothing; a per-file
        # pick must only fill in the missing one.
        repo = _seeded_repo('Repo G', 'https://example.com/g', plugins=[
            {'filename': 'balance2.py', 'label': None, 'description': None,
             'runtime': 'minqlx', 'requires_qlsm_version': None},
            {'filename': 'no_runtime.py', 'label': None, 'description': None,
             'runtime': None, 'requires_qlsm_version': None},
        ])
        repo_id = repo.id

    calls = []
    monkeypatch.setattr(
        plugin_repository_routes, 'download_plugin',
        lambda base_url, filename, runtime, overwrite=False, inline_manifest=None: calls.append((base_url, filename, runtime)),
    )
    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={
            'filenames': ['balance2.py', 'no_runtime.py'],
            'runtimes': {'balance2.py': 'minqlxtended', 'no_runtime.py': 'minqlxtended'},
        },
    )
    assert response.status_code == 200
    assert calls == [
        ('https://example.com/g', 'balance2.py', 'minqlx'),
        ('https://example.com/g', 'no_runtime.py', 'minqlxtended'),
    ]


def test_download_rejects_an_unknown_picked_runtime(client, app):
    make_user(app, 'dlbadpick', 'password123')
    headers = auth_headers(app, 'dlbadpick')
    with app.app_context():
        repo = _seeded_repo('Repo H', 'https://example.com/h')
        repo_id = repo.id

    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['balance2.py'], 'runtimes': {'balance2.py': 'quake3'}},
    )
    assert response.status_code == 400


def test_download_partial_failure_returns_207(client, app, monkeypatch):
    _patch_fetch(monkeypatch, error='offline')
    make_user(app, 'dlpartial', 'password123')
    headers = auth_headers(app, 'dlpartial')
    with app.app_context():
        repo = _seeded_repo('Repo H', 'https://example.com/h', plugins=[
            {'filename': 'ok.py', 'label': None, 'description': None,
             'runtime': 'minqlx', 'requires_qlsm_version': None},
            {'filename': 'bad.py', 'label': None, 'description': None,
             'runtime': 'minqlx', 'requires_qlsm_version': None},
        ])
        repo_id = repo.id

    def fake_download(base_url, filename, runtime, overwrite=False, inline_manifest=None):
        if filename == 'bad.py':
            raise PluginRepositoryError('download failed')

    monkeypatch.setattr(plugin_repository_routes, 'download_plugin', fake_download)
    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['ok.py', 'bad.py']},
    )
    assert response.status_code == 207
    body = response.get_json()
    assert body['downloaded'] == ['ok.py']
    assert body['errors'][0]['filename'] == 'bad.py'


def test_download_surfaces_the_exists_code_and_overwrite_retries(client, app, monkeypatch):
    _patch_fetch(monkeypatch, error='offline')
    make_user(app, 'dloverwrite', 'password123')
    headers = auth_headers(app, 'dloverwrite')
    with app.app_context():
        repo = _seeded_repo('Repo I', 'https://example.com/i')
        repo_id = repo.id

    def fake_download(base_url, filename, runtime, overwrite=False, inline_manifest=None):
        if not overwrite:
            raise PluginRepositoryError(f'{filename} already exists in the local pool.', code='exists')

    monkeypatch.setattr(plugin_repository_routes, 'download_plugin', fake_download)

    blocked = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['balance2.py']},
    )
    assert blocked.status_code == 409
    assert blocked.get_json()['errors'][0]['code'] == 'exists'

    retried = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['balance2.py'], 'overwrite': True},
    )
    assert retried.status_code == 200
    assert retried.get_json()['downloaded'] == ['balance2.py']


def test_download_mixed_exists_and_other_failure_returns_422(client, app, monkeypatch):
    """409 is only for "everything already exists": any other failure in the
    batch has no overwrite fix, so the whole response is a plain 422."""
    _patch_fetch(monkeypatch, error='offline')
    make_user(app, 'dlmixed', 'password123')
    headers = auth_headers(app, 'dlmixed')
    with app.app_context():
        repo = _seeded_repo('Repo M', 'https://example.com/m', plugins=[
            {'filename': 'dup.py', 'label': None, 'description': None,
             'runtime': 'minqlx', 'requires_qlsm_version': None},
            {'filename': 'bad.py', 'label': None, 'description': None,
             'runtime': 'minqlx', 'requires_qlsm_version': None},
        ])
        repo_id = repo.id

    def fake_download(base_url, filename, runtime, overwrite=False, inline_manifest=None):
        if filename == 'dup.py':
            raise PluginRepositoryError('dup.py already exists in the local pool.', code='exists')
        raise PluginRepositoryError('download failed')

    monkeypatch.setattr(plugin_repository_routes, 'download_plugin', fake_download)
    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['dup.py', 'bad.py']},
    )
    assert response.status_code == 422
    codes = {e['filename']: e.get('code') for e in response.get_json()['errors']}
    assert codes == {'dup.py': 'exists', 'bad.py': None}


HELPER_PLUGIN_LIST = [
    {'filename': 'chat_rcon.py', 'label': 'Chat RCON', 'description': None,
     'runtime': 'minqlx', 'version': None, 'sha256': None,
     'requires_qlsm_version': None, 'depends_on': ['chat_rcon_acl.py']},
    {'filename': 'chat_rcon_acl.py', 'label': 'helper', 'description': None,
     'runtime': 'minqlx', 'version': None, 'sha256': None,
     'requires_qlsm_version': None, 'depends_on': []},
]


def test_download_pulls_in_a_declared_helper(client, app, monkeypatch):
    _patch_fetch(monkeypatch, error='offline')
    make_user(app, 'dldeps', 'password123')
    headers = auth_headers(app, 'dldeps')
    with app.app_context():
        repo = _seeded_repo('Repo Deps', 'https://example.com/deps', plugins=HELPER_PLUGIN_LIST)
        repo_id = repo.id

    calls = []
    monkeypatch.setattr(
        plugin_repository_routes, 'download_plugin',
        lambda base_url, filename, runtime, overwrite=False, inline_manifest=None: calls.append(filename),
    )
    monkeypatch.setattr(
        plugin_repository_routes, 'plugin_update_status', lambda entry: 'not_installed')
    monkeypatch.setattr(plugin_repository_routes, 'push_pool_to_hosts',
                        lambda runtimes: {'queued': [], 'skipped': []})

    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['chat_rcon.py']},
    )
    assert response.status_code == 200
    body = response.get_json()
    # Helper written first, so the pool never holds a plugin without it.
    assert calls == ['chat_rcon_acl.py', 'chat_rcon.py']
    assert body['downloaded'] == ['chat_rcon_acl.py', 'chat_rcon.py']
    assert body['auto_added'] == ['chat_rcon_acl.py']


def test_download_gives_a_runtimeless_helper_its_pullers_runtime(client, app, monkeypatch):
    """A helper has to land in the same pool as the plugin importing it, so an
    entry with no runtime of its own inherits the puller's instead of being
    rejected for a runtime the operator was never shown a picker for."""
    _patch_fetch(monkeypatch, error='offline')
    make_user(app, 'dldepsruntime', 'password123')
    headers = auth_headers(app, 'dldepsruntime')
    with app.app_context():
        repo = _seeded_repo('Repo Deps5', 'https://example.com/deps5', plugins=[
            {'filename': 'top.py', 'label': None, 'description': None,
             'runtime': None, 'version': None, 'sha256': None,
             'requires_qlsm_version': None, 'depends_on': ['helper.py']},
            {'filename': 'helper.py', 'label': None, 'description': None,
             'runtime': None, 'version': None, 'sha256': None,
             'requires_qlsm_version': None, 'depends_on': []},
        ])
        repo_id = repo.id

    calls = []
    monkeypatch.setattr(
        plugin_repository_routes, 'download_plugin',
        lambda base_url, filename, runtime, overwrite=False, inline_manifest=None: calls.append((filename, runtime)),
    )
    monkeypatch.setattr(
        plugin_repository_routes, 'plugin_update_status', lambda entry: 'not_installed')
    monkeypatch.setattr(plugin_repository_routes, 'push_pool_to_hosts',
                        lambda runtimes: {'queued': [], 'skipped': []})

    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['top.py'], 'runtimes': {'top.py': 'minqlxtended'}},
    )
    assert response.status_code == 200
    assert calls == [('helper.py', 'minqlxtended'), ('top.py', 'minqlxtended')]


def test_download_skips_an_auto_added_helper_already_up_to_date(client, app, monkeypatch):
    _patch_fetch(monkeypatch, error='offline')
    make_user(app, 'dldepsuptodate', 'password123')
    headers = auth_headers(app, 'dldepsuptodate')
    with app.app_context():
        repo = _seeded_repo('Repo Deps2', 'https://example.com/deps2', plugins=HELPER_PLUGIN_LIST)
        repo_id = repo.id

    calls = []
    monkeypatch.setattr(
        plugin_repository_routes, 'download_plugin',
        lambda base_url, filename, runtime, overwrite=False, inline_manifest=None: calls.append(filename),
    )
    monkeypatch.setattr(
        plugin_repository_routes, 'plugin_update_status',
        lambda entry: 'up_to_date' if entry['filename'] == 'chat_rcon_acl.py' else 'not_installed',
    )
    monkeypatch.setattr(plugin_repository_routes, 'push_pool_to_hosts',
                        lambda runtimes: {'queued': [], 'skipped': []})

    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['chat_rcon.py']},
    )
    assert response.status_code == 200
    body = response.get_json()
    # No overwrite prompt for a helper the operator never picked and that
    # already matches this repository's copy.
    assert calls == ['chat_rcon.py']
    assert body['downloaded'] == ['chat_rcon.py']
    assert body['skipped'] == ['chat_rcon_acl.py']


def test_download_a_skipped_helper_does_not_turn_an_exists_error_into_success(client, app, monkeypatch):
    """The picked plugin already being in the pool is still an overwrite
    prompt, even though its helper was silently skipped as already current."""
    _patch_fetch(monkeypatch, error='offline')
    make_user(app, 'dldepsexists', 'password123')
    headers = auth_headers(app, 'dldepsexists')
    with app.app_context():
        repo = _seeded_repo('Repo Deps6', 'https://example.com/deps6', plugins=HELPER_PLUGIN_LIST)
        repo_id = repo.id

    def fake_download(base_url, filename, runtime, overwrite=False, inline_manifest=None):
        raise PluginRepositoryError(f'{filename} already exists in the local pool.', code='exists')

    monkeypatch.setattr(plugin_repository_routes, 'download_plugin', fake_download)
    monkeypatch.setattr(
        plugin_repository_routes, 'plugin_update_status',
        lambda entry: 'up_to_date' if entry['filename'] == 'chat_rcon_acl.py' else 'update_available',
    )

    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['chat_rcon.py']},
    )
    assert response.status_code == 409
    body = response.get_json()
    assert [e['filename'] for e in body['errors']] == ['chat_rcon.py']
    assert body['skipped'] == ['chat_rcon_acl.py']


def test_download_an_explicitly_picked_helper_is_not_skipped(client, app, monkeypatch):
    _patch_fetch(monkeypatch, error='offline')
    make_user(app, 'dldepspicked', 'password123')
    headers = auth_headers(app, 'dldepspicked')
    with app.app_context():
        repo = _seeded_repo('Repo Deps3', 'https://example.com/deps3', plugins=HELPER_PLUGIN_LIST)
        repo_id = repo.id

    calls = []
    monkeypatch.setattr(
        plugin_repository_routes, 'download_plugin',
        lambda base_url, filename, runtime, overwrite=False, inline_manifest=None: calls.append(filename),
    )
    monkeypatch.setattr(
        plugin_repository_routes, 'plugin_update_status', lambda entry: 'up_to_date')
    monkeypatch.setattr(plugin_repository_routes, 'push_pool_to_hosts',
                        lambda runtimes: {'queued': [], 'skipped': []})

    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['chat_rcon_acl.py'], 'overwrite': True},
    )
    assert response.status_code == 200
    assert calls == ['chat_rcon_acl.py']
    assert response.get_json()['skipped'] == []


def test_updates_folds_a_stale_helper_into_the_plugins_status(client, app, monkeypatch):
    make_user(app, 'updatesdeps', 'password123')
    headers = auth_headers(app, 'updatesdeps')
    with app.app_context():
        _seeded_repo('Repo Deps4', 'https://example.com/deps4', plugins=HELPER_PLUGIN_LIST)

    # plugin_update_status_with_dependencies() resolves this by module
    # attribute, so patch it where it lives rather than on the route module.
    monkeypatch.setattr(
        plugin_repositories, 'plugin_update_status',
        lambda entry: 'update_available' if entry['filename'] == 'chat_rcon_acl.py' else 'up_to_date',
    )
    response = client.get('/api/plugin-repositories/updates', headers=headers)
    assert response.status_code == 200
    statuses = {p['filename']: p['status'] for p in response.get_json()['data'][0]['plugins']}
    assert statuses['chat_rcon.py'] == 'update_available'


def test_download_uses_freshly_fetched_entry_for_inline_manifest(client, app, monkeypatch):
    make_user(app, 'dlfresh', 'password123')
    headers = auth_headers(app, 'dlfresh')
    with app.app_context():
        repo = _seeded_repo('Repo J', 'https://example.com/j')  # stored entry has no cvars
        repo_id = repo.id

    cvars = [{'cvar': 'qlx_balance', 'type': 'bool', 'default': True}]
    _patch_fetch(monkeypatch, plugins=[
        {'filename': 'balance2.py', 'label': 'Balance', 'description': None,
         'runtime': 'minqlx', 'requires_qlsm_version': None, 'cvars': cvars},
    ])
    calls = []
    monkeypatch.setattr(
        plugin_repository_routes, 'download_plugin',
        lambda base_url, filename, runtime, overwrite=False, inline_manifest=None:
            calls.append((filename, runtime, inline_manifest)),
    )
    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['balance2.py']},
    )
    assert response.status_code == 200
    assert calls == [('balance2.py', 'minqlx', {'label': 'Balance', 'cvars': cvars})]


def test_download_falls_back_to_stored_entries_when_fresh_fetch_fails(client, app, monkeypatch):
    make_user(app, 'dlfallback', 'password123')
    headers = auth_headers(app, 'dlfallback')
    cvars = [{'cvar': 'qlx_stored', 'type': 'string', 'default': ''}]
    with app.app_context():
        repo = _seeded_repo('Repo K', 'https://example.com/k', plugins=[
            {'filename': 'stored.py', 'label': None, 'description': None,
             'runtime': 'minqlx', 'requires_qlsm_version': None, 'cvars': cvars},
        ])
        repo_id = repo.id

    _patch_fetch(monkeypatch, error='unreachable')
    calls = []
    monkeypatch.setattr(
        plugin_repository_routes, 'download_plugin',
        lambda base_url, filename, runtime, overwrite=False, inline_manifest=None:
            calls.append((filename, inline_manifest)),
    )
    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['stored.py']},
    )
    assert response.status_code == 200
    assert calls == [('stored.py', {'cvars': cvars})]


def test_download_uses_the_stored_entry_when_the_fresh_manifest_lacks_the_filename(client, app, monkeypatch):
    make_user(app, 'dlmissing', 'password123')
    headers = auth_headers(app, 'dlmissing')
    cvars = [{'cvar': 'qlx_stored', 'type': 'string', 'default': ''}]
    with app.app_context():
        repo = _seeded_repo('Repo L', 'https://example.com/l', plugins=[
            {'filename': 'stored.py', 'label': None, 'description': None,
             'runtime': 'minqlx', 'requires_qlsm_version': None, 'cvars': cvars},
        ])
        repo_id = repo.id

    # The author dropped stored.py from qlsm-plugins.json since the last sync.
    # The operator still clicked the row the UI showed, so it downloads with
    # the stored runtime + metadata; if the .py is really gone download_plugin
    # reports the real HTTP error, not "No runtime declared".
    _patch_fetch(monkeypatch, plugins=[
        {'filename': 'other.py', 'label': None, 'description': None,
         'runtime': 'minqlxtended', 'requires_qlsm_version': None},
    ])
    calls = []
    monkeypatch.setattr(
        plugin_repository_routes, 'download_plugin',
        lambda base_url, filename, runtime, overwrite=False, inline_manifest=None:
            calls.append((filename, runtime, inline_manifest)),
    )
    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['stored.py']},
    )
    assert response.status_code == 200
    assert response.get_json()['errors'] == []
    assert calls == [('stored.py', 'minqlx', {'cvars': cvars})]


def test_download_keeps_the_stored_runtime_when_the_fresh_entry_declares_another(client, app, monkeypatch):
    make_user(app, 'dlkeepruntime', 'password123')
    headers = auth_headers(app, 'dlkeepruntime')
    with app.app_context():
        repo = _seeded_repo('Repo M', 'https://example.com/m')  # balance2.py, runtime minqlx
        repo_id = repo.id

    # Fresh manifest moved balance2.py to another runtime and added cvars.
    # The pool is still chosen by what the UI listed (stored: minqlx); only
    # the metadata comes from the fresh entry.
    cvars = [{'cvar': 'qlx_balance', 'type': 'bool', 'default': True}]
    _patch_fetch(monkeypatch, plugins=[
        {'filename': 'balance2.py', 'label': 'Balance', 'description': None,
         'runtime': 'minqlxtended', 'requires_qlsm_version': None, 'cvars': cvars},
    ])
    calls = []
    monkeypatch.setattr(
        plugin_repository_routes, 'download_plugin',
        lambda base_url, filename, runtime, overwrite=False, inline_manifest=None:
            calls.append((filename, runtime, inline_manifest)),
    )
    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['balance2.py']},
    )
    assert response.status_code == 200
    assert calls == [('balance2.py', 'minqlx', {'label': 'Balance', 'cvars': cvars})]


def test_create_repository_stores_the_raw_url_and_keeps_what_was_typed(client, app, monkeypatch):
    """A github.com repo URL is unusable for fetching (it serves HTML), so it
    is resolved to a raw base -- but the card still shows the typed URL."""
    _patch_fetch(monkeypatch)
    make_user(app, 'creator7', 'creatorpass')
    headers = auth_headers(app, 'creator7')

    response = client.post('/api/plugin-repositories/', headers=headers, json={
        'name': 'Doom', 'url': 'https://github.com/D00MSDAYDEVICE/minqlx',
    })

    assert response.status_code == 201
    data = response.get_json()['data']
    assert data['url'] == 'https://github.com/D00MSDAYDEVICE/minqlx'
    assert data['fetch_url'] == 'https://raw.githubusercontent.com/D00MSDAYDEVICE/minqlx/main/'
    assert data['plugins']


def test_create_repository_rejects_a_url_already_added_in_its_other_form(client, app, monkeypatch):
    _patch_fetch(monkeypatch)
    make_user(app, 'creator8', 'creatorpass')
    headers = auth_headers(app, 'creator8')
    client.post('/api/plugin-repositories/', headers=headers, json={
        'name': 'Doom', 'url': 'https://github.com/D00MSDAYDEVICE/minqlx',
    })

    raw = client.post('/api/plugin-repositories/', headers=headers, json={
        'name': 'Doom Raw', 'url': 'https://raw.githubusercontent.com/D00MSDAYDEVICE/minqlx/main/',
    })
    typed_again = client.post('/api/plugin-repositories/', headers=headers, json={
        'name': 'Doom Again', 'url': 'https://github.com/D00MSDAYDEVICE/minqlx/',
    })

    assert raw.status_code == 409
    assert typed_again.status_code == 409


# --- _resolve_runtime ---

@pytest.mark.parametrize('declared, picked, expected', [
    ('minqlx', 'minqlxtended', 'minqlx'),   # declared valid wins over the pick
    ('retired', 'minqlxtended', 'minqlxtended'),  # declared invalid falls through
    ('retired', 'nope', None),               # both invalid
    (None, None, None),                      # nothing to resolve
    ('MinQLX', None, 'minqlx'),              # result is normalized
])
def test_resolve_runtime(declared, picked, expected):
    entry = {'filename': 'x.py', 'runtime': declared} if declared is not None else None
    assert plugin_repository_routes._resolve_runtime(entry, picked) == expected


# --- GET /api/plugin-repositories/<id>/diff ---

def _patch_diff(monkeypatch, tmp_path, local=None, remote=b'print("repo")', error=None):
    """Point the pool at tmp_path/<runtime> and stub the repo fetch.
    `local` bytes are written as tmp_path/<runtime>/balance2.py."""
    def fake_resolve(runtime, filename):
        path = tmp_path / runtime / filename
        return str(path) if path.is_file() else None

    fetched = []

    def fake_fetch(base_url, filename):
        fetched.append((base_url, filename))
        if error:
            raise PluginRepositoryError(error)
        return remote

    monkeypatch.setattr(plugin_repository_routes, 'resolve_pool_file', fake_resolve)
    monkeypatch.setattr(plugin_repository_routes, 'fetch_plugin_source', fake_fetch)
    if local is not None:
        (tmp_path / 'minqlx').mkdir(parents=True, exist_ok=True)
        (tmp_path / 'minqlx' / 'balance2.py').write_bytes(local)
    return fetched


def test_diff_returns_local_and_remote_text(client, app, monkeypatch, tmp_path):
    fetched = _patch_diff(monkeypatch, tmp_path, local=b'print("local")')
    make_user(app, 'diff1', 'password123')
    headers = auth_headers(app, 'diff1')
    with app.app_context():
        repo_id = _seeded_repo('Diff A', 'https://example.com/diff-a/').id

    response = client.get(
        f'/api/plugin-repositories/{repo_id}/diff?filename=balance2.py', headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json()['data'] == {
        'filename': 'balance2.py', 'runtime': 'minqlx',
        'local': 'print("local")', 'remote': 'print("repo")',
    }
    assert fetched == [('https://example.com/diff-a/', 'balance2.py')]


def test_diff_declared_runtime_wins_over_query_runtime(client, app, monkeypatch, tmp_path):
    _patch_diff(monkeypatch, tmp_path, local=b'x = 1')
    make_user(app, 'diff2', 'password123')
    headers = auth_headers(app, 'diff2')
    with app.app_context():
        repo_id = _seeded_repo('Diff B', 'https://example.com/diff-b').id

    response = client.get(
        f'/api/plugin-repositories/{repo_id}/diff?filename=balance2.py&runtime=minqlxtended',
        headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json()['data']['runtime'] == 'minqlx'


def test_diff_uses_query_runtime_when_manifest_declares_none(client, app, monkeypatch, tmp_path):
    _patch_diff(monkeypatch, tmp_path, local=b'x = 1')
    make_user(app, 'diff3', 'password123')
    headers = auth_headers(app, 'diff3')
    with app.app_context():
        repo_id = _seeded_repo('Diff C', 'https://example.com/diff-c', plugins=[
            {'filename': 'balance2.py', 'label': None, 'description': None,
             'runtime': None, 'requires_qlsm_version': None},
        ]).id

    missing = client.get(
        f'/api/plugin-repositories/{repo_id}/diff?filename=balance2.py', headers=headers,
    )
    picked = client.get(
        f'/api/plugin-repositories/{repo_id}/diff?filename=balance2.py&runtime=minqlx', headers=headers,
    )

    assert missing.status_code == 400
    assert 'No runtime declared' in missing.get_json()['error']['message']
    assert picked.status_code == 200


def test_diff_works_for_a_never_synced_repository_with_a_picked_runtime(client, app, monkeypatch, tmp_path):
    # Empty manifest: the filename is not in the synced list, but a valid pick
    # still resolves the pool, the same as download.
    _patch_diff(monkeypatch, tmp_path, local=b'x = 1')
    make_user(app, 'diff3b', 'password123')
    headers = auth_headers(app, 'diff3b')
    with app.app_context():
        repo_id = _seeded_repo('Diff C2', 'https://example.com/diff-c2', plugins=[]).id

    response = client.get(
        f'/api/plugin-repositories/{repo_id}/diff?filename=balance2.py&runtime=minqlx', headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json()['data']['runtime'] == 'minqlx'


def test_diff_rejects_an_unknown_query_runtime(client, app, monkeypatch, tmp_path):
    fetched = _patch_diff(monkeypatch, tmp_path, local=b'x = 1')
    make_user(app, 'diff3c', 'password123')
    headers = auth_headers(app, 'diff3c')
    with app.app_context():
        repo_id = _seeded_repo('Diff C3', 'https://example.com/diff-c3').id

    response = client.get(
        f'/api/plugin-repositories/{repo_id}/diff?filename=balance2.py&runtime=foo', headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()['error']['message'] == "Unknown runtime: 'foo'"
    assert fetched == []


@pytest.mark.parametrize('case, filename', [
    ('parent', '../balance2.py'), ('nested', 'sub/balance2.py'), ('ext', 'balance2.txt'), ('empty', ''),
])
def test_diff_rejects_unsafe_filenames(client, app, monkeypatch, tmp_path, case, filename):
    fetched = _patch_diff(monkeypatch, tmp_path, local=b'x = 1')
    # One user per case, in case the app fixture's DB outlives a single parametrized run.
    make_user(app, f'diff4{case}', 'password123')
    headers = auth_headers(app, f'diff4{case}')
    with app.app_context():
        repo_id = _seeded_repo('Diff D', 'https://example.com/diff-d').id

    response = client.get(
        f'/api/plugin-repositories/{repo_id}/diff', headers=headers,
        query_string={'filename': filename},
    )

    assert response.status_code == 400
    assert response.get_json()['error']['message'] == f"Refusing to diff unsafe filename: '{filename}'"
    assert fetched == []


def test_diff_missing_local_file_is_404(client, app, monkeypatch, tmp_path):
    fetched = _patch_diff(monkeypatch, tmp_path, local=None)
    make_user(app, 'diff5', 'password123')
    headers = auth_headers(app, 'diff5')
    with app.app_context():
        repo_id = _seeded_repo('Diff E', 'https://example.com/diff-e').id

    response = client.get(
        f'/api/plugin-repositories/{repo_id}/diff?filename=balance2.py', headers=headers,
    )

    assert response.status_code == 404
    assert 'not in the local pool' in response.get_json()['error']['message']
    assert fetched == []


def test_diff_local_file_vanishing_after_isfile_is_404_not_500(client, app, monkeypatch, tmp_path):
    # TOCTOU: an overwrite download or a pool sync can remove the file between
    # the isfile check and the read.
    fetched = _patch_diff(monkeypatch, tmp_path, local=b'x = 1')
    monkeypatch.setattr(
        plugin_repository_routes.os.path, 'getsize',
        lambda path: (_ for _ in ()).throw(FileNotFoundError(path)),
    )
    make_user(app, 'diff5b', 'password123')
    headers = auth_headers(app, 'diff5b')
    with app.app_context():
        repo_id = _seeded_repo('Diff E2', 'https://example.com/diff-e2').id

    response = client.get(
        f'/api/plugin-repositories/{repo_id}/diff?filename=balance2.py', headers=headers,
    )

    assert response.status_code == 404
    assert 'not in the local pool' in response.get_json()['error']['message']
    assert fetched == []


def test_diff_unknown_repository_is_404(client, app, monkeypatch, tmp_path):
    _patch_diff(monkeypatch, tmp_path, local=b'x = 1')
    make_user(app, 'diff6', 'password123')
    headers = auth_headers(app, 'diff6')

    response = client.get('/api/plugin-repositories/9999/diff?filename=balance2.py', headers=headers)

    assert response.status_code == 404
    assert response.get_json()['error']['message'] == 'Repository not found.'


def test_diff_fetch_failure_is_422_not_502(client, app, monkeypatch, tmp_path):
    _patch_diff(monkeypatch, tmp_path, local=b'x = 1', error='https://example.com/x returned HTTP 404')
    make_user(app, 'diff7', 'password123')
    headers = auth_headers(app, 'diff7')
    with app.app_context():
        repo_id = _seeded_repo('Diff F', 'https://example.com/diff-f').id

    response = client.get(
        f'/api/plugin-repositories/{repo_id}/diff?filename=balance2.py', headers=headers,
    )

    assert response.status_code == 422
    assert response.get_json()['error']['message'] == 'https://example.com/x returned HTTP 404'


def test_diff_oversized_local_file_is_422(client, app, monkeypatch, tmp_path):
    monkeypatch.setattr(plugin_repository_routes, 'PLUGIN_FILE_MAX_SIZE', 4)
    _patch_diff(monkeypatch, tmp_path, local=b'123456')
    make_user(app, 'diff8', 'password123')
    headers = auth_headers(app, 'diff8')
    with app.app_context():
        repo_id = _seeded_repo('Diff G', 'https://example.com/diff-g').id

    response = client.get(
        f'/api/plugin-repositories/{repo_id}/diff?filename=balance2.py', headers=headers,
    )

    assert response.status_code == 422
    assert 'larger than the 4 byte limit' in response.get_json()['error']['message']


def test_diff_replaces_invalid_utf8(client, app, monkeypatch, tmp_path):
    _patch_diff(monkeypatch, tmp_path, local=b'caf\xe9', remote=b'ok')
    make_user(app, 'diff9', 'password123')
    headers = auth_headers(app, 'diff9')
    with app.app_context():
        repo_id = _seeded_repo('Diff H', 'https://example.com/diff-h').id

    response = client.get(
        f'/api/plugin-repositories/{repo_id}/diff?filename=balance2.py', headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json()['data']['local'] == 'caf�'


def test_diff_requires_auth(client, app):
    response = client.get('/api/plugin-repositories/1/diff?filename=balance2.py')
    assert response.status_code == 401


# --- auto-push after download ---

def test_download_pushes_pool_to_hosts_of_the_downloaded_runtime(client, app, monkeypatch):
    _patch_fetch(monkeypatch, error='offline')
    make_user(app, 'dlpush', 'password123')
    headers = auth_headers(app, 'dlpush')
    with app.app_context():
        repo = _seeded_repo('Repo P', 'https://example.com/p')
        repo_id = repo.id

    monkeypatch.setattr(
        plugin_repository_routes, 'download_plugin',
        lambda base_url, filename, runtime, overwrite=False, inline_manifest=None: None,
    )
    pushed = []
    fake_result = {'queued': [{'id': 1, 'name': 'alpha'}], 'skipped': [{'id': 2, 'name': 'beta', 'reason': 'busy'}]}
    monkeypatch.setattr(
        plugin_repository_routes, 'push_pool_to_hosts',
        lambda runtimes: (pushed.append(set(runtimes)), fake_result)[1],
    )
    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['balance2.py']},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body['downloaded'] == ['balance2.py']
    assert body['push'] == fake_result
    assert pushed == [{'minqlx'}]


def test_download_does_not_push_when_nothing_was_downloaded(client, app, monkeypatch):
    _patch_fetch(monkeypatch, error='offline')
    make_user(app, 'dlnopush', 'password123')
    headers = auth_headers(app, 'dlnopush')
    with app.app_context():
        repo = _seeded_repo('Repo Q', 'https://example.com/q')
        repo_id = repo.id

    def failing_download(base_url, filename, runtime, overwrite=False, inline_manifest=None):
        raise PluginRepositoryError('boom', code='fetch')
    monkeypatch.setattr(plugin_repository_routes, 'download_plugin', failing_download)
    called = []
    monkeypatch.setattr(plugin_repository_routes, 'push_pool_to_hosts', lambda runtimes: called.append(runtimes))

    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['balance2.py']},
    )
    assert response.status_code == 422
    assert 'push' not in response.get_json()
    assert called == []


def test_download_still_succeeds_when_the_push_cannot_take_the_host_lock(client, app, monkeypatch):
    """Redis down used to make the whole download 500 even though the files had
    already landed in the pool, and the retry then hit the overwrite prompt."""
    from ui.models import Host, HostStatus
    _patch_fetch(monkeypatch, error='offline')
    make_user(app, 'dllock', 'password123')
    headers = auth_headers(app, 'dllock')
    with app.app_context():
        repo = _seeded_repo('Repo R', 'https://example.com/r')
        repo_id = repo.id
        host = Host(name='redis-down', provider='standalone', ip_address='10.0.0.9',
                    runtime='minqlx', status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.commit()
        host_id = host.id

    monkeypatch.setattr(
        plugin_repository_routes, 'download_plugin',
        lambda base_url, filename, runtime, overwrite=False, inline_manifest=None: None,
    )
    import ui.plugin_push as plugin_push

    def dead_redis(*args, **kwargs):
        raise RuntimeError('Error 111 connecting to redis:6379. Connection refused.')
    monkeypatch.setattr(plugin_push, 'acquire_lock', dead_redis)

    response = client.post(
        f'/api/plugin-repositories/{repo_id}/download', headers=headers,
        json={'filenames': ['balance2.py']},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body['downloaded'] == ['balance2.py']
    assert body['push']['queued'] == []
    assert body['push']['skipped'] == [
        {'id': host_id, 'name': 'redis-down', 'reason': 'lock unavailable'}
    ]


# --- POST /api/plugin-repositories/<id>/install-addon ---

def test_install_addon_passes_the_manifest_entry(client, app, monkeypatch, tmp_path):
    make_user(app, 'addoninstall', 'password123')
    headers = auth_headers(app, 'addoninstall')
    # The test app fixture's from_mapping() config has no ADDON_PACKAGES_DIR.
    app.config['ADDON_PACKAGES_DIR'] = str(tmp_path)
    with app.app_context():
        repo = _seeded_repo('Repo AI', 'https://example.com/ai', addons=list(ADDON_LIST))
        repo_id = repo.id

    calls = []

    def fake_download_addon(base_url, entry, packages_dir):
        calls.append((base_url, entry['id'], entry['zip']))
        return {'id': entry['id'], 'name': 'Demo Addon', 'version': '1.2.0'}

    monkeypatch.setattr(plugin_repository_routes, 'download_addon', fake_download_addon)
    response = client.post(
        f'/api/plugin-repositories/{repo_id}/install-addon', headers=headers,
        json={'id': 'demo-addon'},
    )
    assert response.status_code == 201
    data = response.get_json()['data']
    assert data['id'] == 'demo-addon'
    assert data['pending_restart'] is True
    assert calls == [('https://example.com/ai', 'demo-addon', 'demo-addon.zip')]


def test_install_addon_unknown_id_404(client, app, monkeypatch):
    make_user(app, 'addonunknown', 'password123')
    headers = auth_headers(app, 'addonunknown')
    with app.app_context():
        repo = _seeded_repo('Repo AK', 'https://example.com/ak', addons=list(ADDON_LIST))
        repo_id = repo.id

    response = client.post(
        f'/api/plugin-repositories/{repo_id}/install-addon', headers=headers,
        json={'id': 'not-in-manifest'},
    )
    assert response.status_code == 404


def test_install_addon_download_failure_422(client, app, monkeypatch, tmp_path):
    make_user(app, 'addonfail', 'password123')
    headers = auth_headers(app, 'addonfail')
    app.config['ADDON_PACKAGES_DIR'] = str(tmp_path)
    with app.app_context():
        repo = _seeded_repo('Repo AL', 'https://example.com/al', addons=list(ADDON_LIST))
        repo_id = repo.id

    def fake_download_addon(base_url, entry, packages_dir):
        raise PluginRepositoryError('sha256 mismatch')

    monkeypatch.setattr(plugin_repository_routes, 'download_addon', fake_download_addon)
    response = client.post(
        f'/api/plugin-repositories/{repo_id}/install-addon', headers=headers,
        json={'id': 'demo-addon'},
    )
    assert response.status_code == 422
    assert 'sha256 mismatch' in response.get_json()['error']['message']


# --- GET /api/plugin-repositories/updates ---

def test_updates_reports_both_kinds(client, app, tmp_path):
    make_user(app, 'updatesuser', 'password123')
    headers = auth_headers(app, 'updatesuser')
    with app.app_context():
        app.config['ADDON_PACKAGES_DIR'] = str(tmp_path)
        repo = _seeded_repo(
            'Repo AM', 'https://example.com/am',
            plugins=[
                # No declared runtime -> nothing to compare against.
                {'filename': 'no_runtime.py', 'label': None, 'description': None,
                 'runtime': None, 'version': None, 'sha256': 'a' * 64,
                 'requires_qlsm_version': None},
            ],
            addons=list(ADDON_LIST),
        )
        repo_id = repo.id

    response = client.get('/api/plugin-repositories/updates', headers=headers)
    assert response.status_code == 200
    data = response.get_json()['data']
    entry = next(r for r in data if r['repo_id'] == repo_id)
    assert entry['plugins'] == [{'filename': 'no_runtime.py', 'runtime': None, 'status': 'unknown'}]
    assert entry['addons'][0]['id'] == 'demo-addon'
    assert entry['addons'][0]['status'] == 'not_installed'


def test_updates_sees_an_installed_addon_version(client, app, tmp_path):
    make_user(app, 'updatesuser2', 'password123')
    headers = auth_headers(app, 'updatesuser2')
    target = tmp_path / 'demo-addon'
    target.mkdir()
    (target / 'qlsm-addon.json').write_text(json.dumps({'id': 'demo-addon', 'version': '1.0.0'}))
    with app.app_context():
        app.config['ADDON_PACKAGES_DIR'] = str(tmp_path)
        repo = _seeded_repo('Repo AN', 'https://example.com/an', plugins=[], addons=list(ADDON_LIST))
        repo_id = repo.id

    response = client.get('/api/plugin-repositories/updates', headers=headers)
    assert response.status_code == 200
    entry = next(r for r in response.get_json()['data'] if r['repo_id'] == repo_id)
    assert entry['addons'][0]['status'] == 'update_available'
    assert entry['addons'][0]['installed_version'] == '1.0.0'
    assert entry['addons'][0]['available_version'] == '1.2.0'
