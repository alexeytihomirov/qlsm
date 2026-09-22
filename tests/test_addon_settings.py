"""Scoped addon settings + the three-layer enable rule."""
import pytest

from ui import db
from ui.models import AddonState, Host, HostStatus, QLInstance
from ui.addons.settings import AddonSettings, AddonSettingsError, delete_scope_rows

MANIFEST = {
    'id': 'sample-addon',
    'settings': {
        'global': [
            {'key': 'stats_hub_url', 'type': 'string', 'default': ''},
            {'key': 'ingest_token', 'type': 'secret'},
        ],
        'host': [
            {'key': 'timeout_sec', 'type': 'number', 'default': 2, 'min': 1, 'max': 30},
        ],
        'instance': [
            {'key': 'server_id', 'type': 'number', 'default': 0, 'min': 0},
            {'key': 'verbose', 'type': 'bool', 'default': False},
        ],
    },
}


@pytest.fixture
def settings(app):
    with app.app_context():
        yield AddonSettings('sample-addon', MANIFEST)


@pytest.fixture
def host_and_instance(app):
    with app.app_context():
        host = Host(name='germany', ip_address='10.0.0.1', provider='vultr',
                    status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.flush()
        instance = QLInstance(name='duel', port=27960, hostname='duel', host_id=host.id)
        db.session.add(instance)
        db.session.commit()
        yield host.id, instance.id


# ---- defaults + reads -------------------------------------------------

def test_get_returns_manifest_defaults_when_nothing_stored(settings):
    assert settings.get('host', 1) == {'timeout_sec': 2}


def test_missing_default_falls_back_per_type(settings):
    values = settings.get('instance', 1)
    assert values == {'server_id': 0, 'verbose': False}


def test_secret_without_default_reads_as_empty_string(settings):
    assert settings.get('global')['ingest_token'] == ''


def test_stored_values_override_defaults(settings):
    settings.set('host', 7, {'timeout_sec': 9})
    assert settings.get('host', 7)['timeout_sec'] == 9


def test_values_are_scoped_per_id(settings):
    settings.set('host', 7, {'timeout_sec': 9})
    assert settings.get('host', 8)['timeout_sec'] == 2


def test_keys_dropped_from_the_manifest_are_not_returned(settings):
    """An addon must never see a field it no longer declares."""
    settings.set('host', 7, {'timeout_sec': 9})
    shrunk = AddonSettings('sample-addon', {'settings': {'host': []}})
    assert shrunk.get('host', 7) == {}


# ---- validation -------------------------------------------------------

def test_unknown_key_is_rejected_not_ignored(settings):
    with pytest.raises(AddonSettingsError) as exc:
        settings.set('host', 1, {'timeuot_sec': 5})
    assert 'timeuot_sec' in str(exc.value)


def test_number_below_min_is_rejected(settings):
    with pytest.raises(AddonSettingsError):
        settings.set('host', 1, {'timeout_sec': 0})


def test_number_above_max_is_rejected(settings):
    with pytest.raises(AddonSettingsError):
        settings.set('host', 1, {'timeout_sec': 31})


def test_non_numeric_string_is_rejected(settings):
    with pytest.raises(AddonSettingsError):
        settings.set('host', 1, {'timeout_sec': 'soon'})


def test_numeric_string_is_coerced(settings):
    assert settings.set('host', 1, {'timeout_sec': '5'})['timeout_sec'] == 5


def test_bool_is_not_accepted_as_a_number(settings):
    with pytest.raises(AddonSettingsError):
        settings.set('host', 1, {'timeout_sec': True})


def test_bool_string_forms_are_coerced(settings):
    assert settings.set('instance', 1, {'verbose': 'true'})['verbose'] is True
    assert settings.set('instance', 1, {'verbose': '0'})['verbose'] is False


def test_unknown_scope_is_rejected(settings):
    with pytest.raises(AddonSettingsError):
        settings.get('galaxy', 1)


def test_corrupt_settings_blob_reads_as_empty(settings, app):
    with app.app_context():
        db.session.add(AddonState(
            addon_id='sample-addon', scope='host', scope_id=3,
            enabled=True, settings_json='{oops',
        ))
        db.session.commit()
        # falls back to defaults rather than raising
        assert settings.get('host', 3) == {'timeout_sec': 2}


# ---- the three-layer enable rule --------------------------------------

def test_nothing_is_enabled_by_default(settings, host_and_instance):
    host_id, instance_id = host_and_instance
    assert settings.is_enabled('global') is False
    assert settings.is_enabled('host', host_id) is False
    assert settings.is_enabled('instance', instance_id) is False


def test_host_requires_global(settings, host_and_instance):
    host_id, _ = host_and_instance
    settings.set_enabled('host', host_id, True)
    assert settings.is_enabled('host', host_id) is False
    settings.set_enabled('global', 0, True)
    assert settings.is_enabled('host', host_id) is True


def test_instance_requires_its_own_host(settings, host_and_instance):
    host_id, instance_id = host_and_instance
    settings.set_enabled('global', 0, True)
    settings.set_enabled('instance', instance_id, True)
    assert settings.is_enabled('instance', instance_id) is False
    settings.set_enabled('host', host_id, True)
    assert settings.is_enabled('instance', instance_id) is True


def test_disabling_global_switches_everything_off(settings, host_and_instance):
    host_id, instance_id = host_and_instance
    for scope, sid in (('global', 0), ('host', host_id), ('instance', instance_id)):
        settings.set_enabled(scope, sid, True)
    assert settings.is_enabled('instance', instance_id) is True
    settings.set_enabled('global', 0, False)
    assert settings.is_enabled('instance', instance_id) is False


def test_layer_flag_is_kept_even_when_a_parent_blocks_it(settings, host_and_instance):
    """The UI needs "on, blocked by host" -- the click must not be silently lost."""
    host_id, instance_id = host_and_instance
    settings.set_enabled('global', 0, True)
    settings.set_enabled('instance', instance_id, True)
    assert settings.is_layer_enabled('instance', instance_id) is True
    assert settings.is_enabled('instance', instance_id) is False


def test_enable_state_for_a_vanished_instance_is_false(settings, host_and_instance):
    """A stale id from the UI (instance deleted mid-session) must read False,
    not raise -- QLInstance.host_id is NOT NULL, so "no host" reaches this
    code only as "no instance row at all"."""
    host_id, instance_id = host_and_instance
    settings.set_enabled('global', 0, True)
    settings.set_enabled('host', host_id, True)
    settings.set_enabled('instance', instance_id, True)
    assert settings.is_enabled('instance', instance_id) is True

    QLInstance.query.filter_by(id=instance_id).delete()
    db.session.commit()
    assert settings.is_enabled('instance', instance_id) is False


def test_global_rows_share_one_sentinel_id(settings):
    settings.set_enabled('global', 0, True)
    settings.set_enabled('global', 999, False)   # scope_id ignored for global
    assert AddonState.query.filter_by(addon_id='sample-addon', scope='global').count() == 1
    assert settings.is_enabled('global') is False


# ---- cleanup ----------------------------------------------------------

def test_delete_scope_rows_removes_every_addons_rows(settings, host_and_instance):
    host_id, _ = host_and_instance
    settings.set_enabled('host', host_id, True)
    AddonSettings('other-addon', MANIFEST).set_enabled('host', host_id, True)
    assert delete_scope_rows('host', host_id, commit=True) == 2
    assert AddonState.query.filter_by(scope='host', scope_id=host_id).count() == 0


def test_delete_scope_rows_leaves_other_scopes_alone(settings, host_and_instance):
    host_id, instance_id = host_and_instance
    settings.set_enabled('host', host_id, True)
    settings.set_enabled('instance', instance_id, True)
    delete_scope_rows('host', host_id, commit=True)
    assert settings.is_layer_enabled('instance', instance_id) is True
