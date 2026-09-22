"""Manifest validation: what loads, what is rejected, and why."""
import json

import pytest

from ui.addons.manifest import CURRENT_UI_API, read_manifest, validate_manifest


def _minimal(**overrides):
    data = {'id': 'sample-addon', 'version': '1.0.0'}
    data.update(overrides)
    return data


def test_minimal_manifest_is_valid():
    manifest, errors = validate_manifest(_minimal())
    assert errors == []
    assert manifest['id'] == 'sample-addon'
    assert manifest['scopes'] == ['global']
    assert manifest['ui_api'] == CURRENT_UI_API


@pytest.mark.parametrize('bad_id', [
    'Sample',           # uppercase
    'sample_addon',     # underscore
    'sample--addon',    # double dash
    '-sample',          # leading dash
    'sample-',          # trailing dash
    '',
])
def test_id_must_be_kebab_case(bad_id):
    _, errors = validate_manifest(_minimal(id=bad_id))
    assert errors, f'expected {bad_id!r} to be rejected'


def test_version_is_required():
    _, errors = validate_manifest({'id': 'sample-addon'})
    assert any('version' in e for e in errors)


def test_scopes_are_canonically_ordered_and_deduped():
    manifest, errors = validate_manifest(
        _minimal(scopes=['instance', 'global', 'instance', 'host'])
    )
    assert errors == []
    assert manifest['scopes'] == ['global', 'host', 'instance']


def test_unknown_scope_is_rejected():
    _, errors = validate_manifest(_minimal(scopes=['galaxy']))
    assert any('galaxy' in e for e in errors)


def test_settings_field_type_must_be_known():
    _, errors = validate_manifest(_minimal(settings={
        'host': [{'key': 'url', 'type': 'urlish'}],
    }))
    assert any('type must be one of' in e for e in errors)


def test_min_max_only_apply_to_numbers():
    _, errors = validate_manifest(_minimal(settings={
        'host': [{'key': 'name', 'type': 'string', 'min': 1}],
    }))
    assert any('only applies to type "number"' in e for e in errors)


def test_duplicate_setting_keys_are_rejected():
    _, errors = validate_manifest(_minimal(settings={
        'host': [
            {'key': 'url', 'type': 'string'},
            {'key': 'url', 'type': 'string'},
        ],
    }))
    assert any('duplicate field key' in e for e in errors)


def test_panel_route_may_not_be_absolute():
    """A panel pointing at a core endpoint is the whole thing this prevents."""
    _, errors = validate_manifest(_minimal(ui={
        'panels': {'p': {'kind': 'form', 'load': 'GET /api/hosts'}},
    }))
    assert any('must be relative to the addon prefix' in e for e in errors)


def test_panel_route_may_not_be_external_url():
    _, errors = validate_manifest(_minimal(ui={
        'panels': {'p': {'kind': 'form', 'load': 'GET https://evil.example/steal'}},
    }))
    assert any('must be relative' in e for e in errors)


def test_relative_panel_route_is_accepted():
    manifest, errors = validate_manifest(_minimal(ui={
        'panels': {'p': {'kind': 'form', 'load': 'GET hosts/{host_id}'}},
        'host_menu': [{'id': 'relay', 'label': 'Relay', 'panel': 'p'}],
    }))
    assert errors == []
    assert manifest['ui']['host_menu'][0]['panel'] == 'p'


def test_menu_entry_must_reference_a_declared_panel():
    _, errors = validate_manifest(_minimal(ui={
        'panels': {},
        'host_menu': [{'id': 'relay', 'panel': 'nope'}],
    }))
    assert any('not declared in ui.panels' in e for e in errors)


def test_menu_entry_needs_panel_or_component():
    _, errors = validate_manifest(_minimal(ui={'host_menu': [{'id': 'relay'}]}))
    assert any('needs either "panel" or "component"' in e for e in errors)


def test_menu_entry_cannot_have_both():
    _, errors = validate_manifest(_minimal(ui={
        'panels': {'p': {'kind': 'form'}},
        'host_menu': [{'id': 'relay', 'panel': 'p', 'component': 'ui/x.js'}],
    }))
    assert any('pick one' in e for e in errors)


@pytest.mark.parametrize('component', ['/etc/passwd', '../../backend.py', 'a/../../b.js'])
def test_component_path_may_not_escape_the_addon(component):
    _, errors = validate_manifest(_minimal(ui={
        'host_menu': [{'id': 'relay', 'component': component}],
    }))
    assert any('must stay inside the addon' in e for e in errors)


def test_unknown_panel_kind_is_rejected():
    _, errors = validate_manifest(_minimal(ui={'panels': {'p': {'kind': 'hologram'}}}))
    assert any('kind must be one of' in e for e in errors)


def test_read_manifest_reports_missing_file(tmp_path):
    manifest, errors = read_manifest(str(tmp_path))
    assert manifest is None
    assert any('not found' in e for e in errors)


def test_read_manifest_reports_bad_json(tmp_path):
    (tmp_path / 'qlsm-addon.json').write_text('{not json', encoding='utf-8')
    manifest, errors = read_manifest(str(tmp_path))
    assert manifest is None
    assert any('could not be read' in e for e in errors)


def test_read_manifest_round_trip(tmp_path):
    (tmp_path / 'qlsm-addon.json').write_text(
        json.dumps(_minimal(name='Sample Addon')), encoding='utf-8'
    )
    manifest, errors = read_manifest(str(tmp_path))
    assert errors == []
    assert manifest['name'] == 'Sample Addon'


# ---- render mode ------------------------------------------------------

def test_a_component_entry_may_render_its_own_modal():
    manifest, errors = validate_manifest(_minimal(ui={
        'host_menu': [{'id': 'relay', 'component': 'ui/Panel.js', 'renders': 'modal'}],
    }))
    assert errors == []
    assert manifest['ui']['host_menu'][0]['renders'] == 'modal'


def test_render_mode_must_be_known():
    _, errors = validate_manifest(_minimal(ui={
        'host_menu': [{'id': 'relay', 'component': 'ui/Panel.js', 'renders': 'hologram'}],
    }))
    assert any('"renders" must be one of' in e for e in errors)


def test_modal_render_mode_requires_a_component():
    """A declarative panel cannot be the whole dialog -- it has no shell."""
    _, errors = validate_manifest(_minimal(ui={
        'panels': {'p': {'kind': 'form'}},
        'host_menu': [{'id': 'relay', 'panel': 'p', 'renders': 'modal'}],
    }))
    assert any('needs a component' in e for e in errors)


def test_panel_render_mode_is_fine_with_a_panel():
    manifest, errors = validate_manifest(_minimal(ui={
        'panels': {'p': {'kind': 'form'}},
        'host_menu': [{'id': 'relay', 'panel': 'p', 'renders': 'panel'}],
    }))
    assert errors == []
