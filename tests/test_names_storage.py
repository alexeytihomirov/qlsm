"""OFFLINE Redis observation contracts: deliberately different across runtimes."""
import pytest

from tests.names_offline import FILES, Harness


@pytest.fixture(params=FILES)
def h(request, monkeypatch):
    return Harness(request.param, monkeypatch)


@pytest.mark.parametrize('registered', [None, '^2Same'])
def test_reload_cache_missing_is_not_negative(h, registered):
    p = h.add('Same', connect=False, loaded=False)
    if registered is not None:
        h.plugin.db[h.key()] = registered
    h.plugin.db.calls.clear()
    h.change(rate='25000')
    assert not h.plugin.db.calls
    if h.ext:
        assert p.steam_id not in h.plugin.registered_names
    for i in range(100):
        h.change(name='^4Same' if i % 2 == 0 else '^5Same')
    assert dict(h.plugin.db.calls) == {'get': 1 if h.ext else 100}
    assert h.raw() == (registered if registered is not None else '^5Same')
    if h.ext:
        assert p.steam_id in h.plugin.registered_names
        assert h.plugin.registered_names[p.steam_id] == registered


@pytest.mark.parametrize('initial', [None, '^2Same'])
def test_external_add_edit_delete_keeps_runtime_freshness_contract(h, initial):
    h.add('Same', loaded=False)
    if initial is not None:
        h.plugin.db[h.key()] = initial
    h.plugin.handle_player_loaded(h.snapshot())
    h.plugin.db[h.key()] = '^3Same'
    h.change(name='^4Same')
    assert h.raw() == ((initial or '^4Same') if h.ext else '^3Same')
    del h.plugin.db[h.key()]
    h.change(name='^5Same')
    assert h.raw() == ((initial or '^5Same') if h.ext else '^5Same')
    # Disconnect/reconnect is already an existing refresh boundary in extended.
    h.plugin.handle_player_disconnect(h.snapshot(), 'quit')
    h.plugin.db[h.key()] = '^6Same'
    h.add('Same')
    h.change(name='^4Same')
    assert h.raw() == '^6Same'


def test_command_updates_positive_and_negative_cache(h):
    h.add('Same')  # Normal loaded event records a known negative in extended.
    h.change(name='^4Same')
    h.command('^2Same')
    h.change(name='^5Same')
    assert h.raw() == '^7^2Same'
    h.command()
    h.change(name='^6Same')
    assert h.raw() == '^6Same'
    if h.ext:
        assert h.plugin.registered_names[h.snapshot().steam_id] is None
