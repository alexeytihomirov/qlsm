"""Accepted F1–F4 and policy controls on all four actual files; OFFLINE only."""
import inspect

import pytest

from tests.names_offline import FILES, Harness, clean


@pytest.fixture(params=FILES)
def h(request, monkeypatch):
    return Harness(request.param, monkeypatch)


def test_runtime_signatures_and_version(h):
    expected = {'handle_player_connect': 2 if h.ext else 1,
                'handle_player_loaded': 1, 'handle_player_disconnect': 2,
                'handle_userinfo': 3 if h.ext else 2, 'cmd_name': 3}
    for method, count in expected.items():
        assert len(inspect.signature(getattr(h.plugin, method)).parameters) == count
    assert h.version == '1.1.0'


def test_rename_reregister_colour_resend(h):
    p = h.add('Old')
    h.command('^2Old')
    h.change(name='New')
    assert h.key() not in h.plugin.db
    assert h.plugin.steam_names[p.steam_id] == 'New'
    assert h.command('^3New') == 3
    h.change(name='^4New')
    assert h.raw() == '^7^3New'
    assert h.plugin.db[h.key()] == '^7^3New'
    assert len([m for m in h.messages[0] if 'reset' in m]) == 1


def test_unregistered_rename_and_non_name_noop(h):
    p = h.add('Old')
    h.plugin.db.calls.clear()
    h.change(rate='25000')
    assert not h.plugin.db.calls
    assert h.plugin.steam_names[p.steam_id] == 'Old'
    h.change(name='New')
    assert h.plugin.steam_names[p.steam_id] == 'New'
    assert not h.messages[0]


@pytest.mark.parametrize('loaded', [True, False])
@pytest.mark.parametrize('enforce', [True, False])
def test_stale_registration_eligibility_on_load_and_reload(h, loaded, enforce):
    p = h.add('New', connect=loaded, loaded=False)
    h.enforce(enforce)
    h.plugin.db[h.key()] = '^2Old'
    if loaded:
        h.plugin.handle_player_loaded(h.snapshot())
        assert h.raw() == ('New' if enforce else '^2Old')
    h.change(name='^4New')
    assert h.raw() == ('^4New' if enforce else '^2Old')
    assert h.plugin.db[h.key()] == '^2Old'  # Not destructively cleaned on load.
    assert h.plugin.steam_names[p.steam_id] == 'New'


def test_enforcement_off_repeated_alias_keeps_original_baseline(h):
    p = h.add('Original')
    h.enforce(False)
    for alias in ('^3Alias', '^2OtherAlias'):
        h.command(alias)
        assert h.plugin.steam_names[p.steam_id] == 'Original'
        h.change(name='^4Original')
        assert h.raw() == '^7' + alias
    h.change(name='ActuallyNew')
    assert h.raw() == 'ActuallyNew'
    assert h.plugin.steam_names[p.steam_id] == 'ActuallyNew'
    assert h.key() not in h.plugin.db


def test_matching_mixed_case_registration_stays_eligible(h):
    h.add('Same', loaded=False)
    h.plugin.db[h.key()] = '^2sAmE'
    h.plugin.handle_player_loaded(h.snapshot())
    h.change(name='^4Same')
    assert h.raw() == '^2sAmE'
    assert h.command('^3SAME') == 3  # Existing command lower-case comparison.
    h.change(name='^5Same')
    assert h.raw() == '^7^3SAME'
    # Client baseline comparisons remain case-sensitive, as before this patch.
    h.change(name='same')
    assert h.key() not in h.plugin.db
    assert h.plugin.steam_names[h.snapshot().steam_id] == 'same'


def test_reload_fresh_input_not_server_snapshot_seeds_baseline(h):
    p = h.add('ServerAlias', connect=False, loaded=False)
    h.plugin.db[h.key()] = '^2Original'
    h.change(name='^4Original')
    assert h.plugin.steam_names[p.steam_id] == 'Original'
    assert h.raw() == '^2Original'
    h.change(name='^5Original')
    assert h.raw() == '^2Original'


@pytest.mark.parametrize('alias', [False, True])
def test_command_immediately_after_reload_and_reset(h, alias):
    p = h.add('Original', connect=False, loaded=False)
    h.enforce(not alias)
    h.command('^2Alias' if alias else '^2Original')
    assert h.plugin.steam_names[p.steam_id] == 'Original'
    assert not h.plugin.name_set
    h.change(name='^4Original')
    assert h.raw() == ('^7^2Alias' if alias else '^7^2Original')
    assert h.command() == 3
    assert h.key() not in h.plugin.db
    h.change(name='^5Original')
    assert h.raw() == '^5Original'
    assert h.command() == 1


def test_reset_immediately_after_reload(h):
    h.add('Same', connect=False, loaded=False)
    h.plugin.db[h.key()] = '^2Same'
    assert h.command() == 3
    h.change(name='^4Same')
    assert h.raw() == '^4Same'
    if h.ext:
        assert h.plugin.registered_names[h.snapshot().steam_id] is None


@pytest.mark.parametrize('invalid', ['^1Different', 'x' * 37, 'Bad\\Name', '^1   '])
def test_rejected_commands_do_not_initialize_or_mutate_state(h, invalid):
    h.add('Same', connect=False, loaded=False)
    assert h.command(invalid) == 3
    assert not h.plugin.steam_names
    assert not h.plugin.db
    assert h.raw() == 'Same'
    assert not h.plugin.name_set


def test_no_diff_load_command_and_cross_player_rename(h):
    a = h.add('^7^2A', loaded=False)
    b = h.add('B', slot=1)
    h.plugin.db[h.key()] = '^7^2A'
    h.command('^3B', slot=1)
    h.writes.clear()
    h.plugin.handle_player_loaded(h.snapshot())
    h.command('^2A')
    assert not h.writes  # raw cvars, NOT getter (which appends ^7).
    assert not h.plugin.name_set
    h.change(slot=1, name='NewB')
    assert h.plugin.steam_names[b.steam_id] == 'NewB'
    assert h.key(1) not in h.plugin.db
    assert h.plugin.steam_names[a.steam_id] == 'A'


def test_synchronous_reentry_only_ignores_own_name(h):
    a = h.add('Original')
    b = h.add('B', slot=1)
    h.enforce(False)
    h.command('^3B', slot=1)

    def interleave():
        assert a.steam_id in h.plugin.name_set
        h.userinfo(h.snapshot(), {'rate': '25000'})
        assert a.steam_id in h.plugin.name_set  # Non-name event cannot consume guard.
        h.change(slot=1, name='NewB')
        assert a.steam_id in h.plugin.name_set

    h.before_write = interleave
    h.command('^3Alias')
    assert h.raw() == '^7^3Alias'
    assert h.plugin.steam_names[a.steam_id] == 'Original'
    assert h.plugin.steam_names[b.steam_id] == 'NewB'
    assert not h.plugin.name_set
    assert h.key(1) not in h.plugin.db


@pytest.mark.parametrize('mode', ['blocked', 'error'])
def test_self_assignment_transport_failure_has_no_pending_guard(h, mode):
    p = h.add('Original')
    h.enforce(False)
    h.mode = mode
    if mode == 'error':
        with pytest.raises(RuntimeError, match='OFFLINE transport error'):
            h.command('^3Alias')
    else:
        h.command('^3Alias')  # No new promise to roll back a blocked registration.
    assert not h.plugin.name_set
    assert h.raw() == 'Original'
    h.mode = 'normal'
    h.change(name='New')
    assert h.plugin.steam_names[p.steam_id] == 'New'
    assert h.key() not in h.plugin.db


def test_disconnect_reconnect_cleans_all_session_state(h):
    p = h.add('Original')
    h.command('^2Original')
    h.plugin.name_set.add(p.steam_id)
    h.plugin.handle_player_disconnect(h.snapshot(), 'quit')
    assert not h.plugin.steam_names and not h.plugin.name_set
    if h.ext:
        assert not h.plugin.registered_names
    h.add('New')
    h.change(name='^4New')
    assert h.raw() == '^4New'
    assert h.plugin.db[h.key()] == '^7^2Original'


def test_player_snapshot_does_not_magically_refresh_after_assignment(h):
    p = h.add('Original')
    before = p.cvars
    p.name = '^3New'
    assert h.raw() == '^3New'
    assert p.name == 'Original^7'  # Setter does not update cached display name.
    assert p.cvars == before  # minqlxtended invalidates parse, not cached _info.
    assert h.snapshot().name == '^3New^7'


@pytest.mark.parametrize('invalid', ['Bad\\Name', '^1   ', 'é' * 19])
def test_validation_preserves_existing_alias_baseline_and_storage(h, invalid):
    p = h.add('Original')
    h.enforce(False)
    h.command('^2Alias')
    before = dict(h.plugin.db)
    assert h.command(invalid) == 3
    assert dict(h.plugin.db) == before
    assert h.plugin.steam_names[p.steam_id] == 'Original'
    assert h.raw() == '^7^2Alias'


def test_runtime_specific_infostring_validation_remains_unchanged(h):
    if not h.ext:
        return  # minqlx validation is intentionally not widened in this patch.
    h.add('Original')
    h.enforce(False)
    for invalid in ('Bad;Name', 'Bad"Name'):
        assert h.command(invalid) == 3
        assert not h.plugin.db
        assert h.raw() == 'Original'


def test_excessive_colour_cleanup_compatibility(h):
    h.add('Same')
    h.command('^1^2Same')
    assert h.raw() == '^7^2Same'
    assert h.plugin.db[h.key()] == '^7^2Same'


@pytest.mark.parametrize('order', ['names_first', 'rank_first'])
def test_tier_colour_hook_order_never_resurrects_stale_base(h, order):
    # OFFLINE rankcolors-like colour-only hook, not a deployed rankcolors claim.
    h.add('New', loaded=False)
    h.plugin.db[h.key()] = '^2Old'
    h.plugin.handle_player_loaded(h.snapshot())

    def tier(player, changed):
        if 'name' in changed:
            changed['name'] = '^4' + clean(changed['name'])

    original = h.userinfo
    if order == 'names_first':
        h.after_hook = tier
    else:
        def rank_first(player, changed):
            tier(player, changed)
            return original(player, changed) or changed
        h.userinfo = rank_first
    h.change(name='^3New')
    assert clean(h.raw()) == 'New'
    assert h.plugin.db[h.key()] == '^2Old'
