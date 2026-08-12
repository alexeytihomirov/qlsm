"""Tests for block.py — per-player chat blocking.

Runs without a Quake Live server by stubbing the minqlx module. The chat and
tchat payloads used here are verbatim captures from a live server, so the parser
is tested against exactly what the engine emits.
"""

import os
import sys
import types
import unittest

sys.modules.setdefault("redis", types.ModuleType("redis"))
_exc = types.ModuleType("redis.exceptions")


class RedisError(Exception):
    pass


_exc.RedisError = RedisError
sys.modules["redis.exceptions"] = _exc

_minqlx = types.ModuleType("minqlx")
# Values mirror the enum in pyminqlx.h. RET_NONE being 0 is the whole reason the
# hot path must return RET_STOP_EVENT rather than a literal False: `False == 0`
# is True, so the dispatcher would read a returned False as "continue".
_minqlx.RET_NONE = 0
_minqlx.RET_STOP = 1
_minqlx.RET_STOP_EVENT = 2
_minqlx.RET_STOP_ALL = 3
_minqlx.PRI_HIGHEST = 0
_minqlx.PRI_HIGH = 1
_minqlx.PRI_NORMAL = 2
_minqlx.PRI_LOW = 3
_minqlx.PRI_LOWEST = 4


class NonexistentPlayerError(Exception):
    pass


_minqlx.NonexistentPlayerError = NonexistentPlayerError
_minqlx.get_logger = lambda p=None: _NullLogger()


class _NullLogger:
    def warning(self, *a, **k):
        pass


class _PluginBase:
    def add_hook(self, *a, **k):
        pass

    def add_command(self, *a, **k):
        pass

    def set_cvar_once(self, *a, **k):
        pass


_minqlx.Plugin = _PluginBase
sys.modules["minqlx"] = _minqlx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import block as block_mod  # noqa: E402
from block import parse_speaker_cid, blocks_key  # noqa: E402


# Verbatim captures from the Slaughterhouse probe run.
CHAT_FROM_2 = 'chat "02 Doomsday^7\x19: ^2Test1"'
TCHAT_FROM_2 = 'tchat "02 \x19(Doomsday^7\x19) (upper courtyard^7)\x19: ^5test2"'
SCORES = 'scores_ca 2 0 0 2 1 0 41 0 0 0 0 14 0 0 0 0 0 0 1 3 2 0 34'
CONFIGSTRING = 'cs 532 "n\\\\sakura optics\\\\t\\\\1\\\\model\\\\uriel/blue"'
CENTERPRINT = 'cp "sakura optics^7 joined the Red Team.\n"'


class FakePlayer:
    def __init__(self, cid, steam_id, name="p", team="red"):
        self.id = cid
        self.steam_id = steam_id
        self.name = name
        self.clean_name = name
        self.team = team
        self.told = []

    def tell(self, msg):
        self.told.append(msg)


class FakeDB:
    def __init__(self, data=None, fail=False):
        self.data = data or {}
        self.fail = fail

    def smembers(self, key):
        if self.fail:
            raise RedisError("down")
        return set(self.data.get(key, set()))

    def sadd(self, key, value):
        if self.fail:
            raise RedisError("down")
        self.data.setdefault(key, set()).add(str(value))

    def srem(self, key, value):
        if self.fail:
            raise RedisError("down")
        self.data.get(key, set()).discard(str(value))


def make_plugin(roster=(), db=None, max_entries=50):
    """Build a block plugin instance wired to fakes."""
    plugin = block_mod.block.__new__(block_mod.block)
    plugin._roster = list(roster)
    plugin.db = db if db is not None else FakeDB()
    plugin._max_entries = max_entries
    plugin.players = lambda: list(plugin._roster)
    plugin.get_cvar = lambda name, kind=str: max_entries
    plugin.player = lambda cid: next((p for p in plugin._roster if p.id == cid), None)
    plugin._blocks = {}
    plugin._active = {}
    for p in plugin._roster:
        plugin._load_blocks(p.steam_id)
    plugin._rebuild_active()
    return plugin


class TestParseSpeakerCid(unittest.TestCase):
    def test_general_chat(self):
        self.assertEqual(parse_speaker_cid(CHAT_FROM_2), 2)

    def test_team_chat(self):
        self.assertEqual(parse_speaker_cid(TCHAT_FROM_2), 2)

    def test_two_digit_client_id(self):
        self.assertEqual(parse_speaker_cid('chat "13 Someone^7\x19: ^2hi"'), 13)

    def test_highest_slot(self):
        self.assertEqual(parse_speaker_cid('chat "63 Someone^7\x19: ^2hi"'), 63)

    def test_no_quote_fails_open(self):
        self.assertIsNone(parse_speaker_cid("chat noquote"))

    def test_non_numeric_fails_open(self):
        self.assertIsNone(parse_speaker_cid('chat "xx Someone: hi"'))

    def test_single_digit_fails_open(self):
        # Guards against int("2") succeeding on a truncated payload.
        self.assertIsNone(parse_speaker_cid('chat "2'))

    def test_unicode_digits_fail_open(self):
        # str.isdigit() accepts these; the explicit ASCII check must not.
        self.assertIsNone(parse_speaker_cid('chat "٢٣ Someone: hi"'))


class TestHotPath(unittest.TestCase):
    def setUp(self):
        self.speaker = FakePlayer(2, 76561197973279898, "Doomsday")
        self.viewer = FakePlayer(3, 76561199813623382, "sakura")
        self.third = FakePlayer(4, 76561190000000004, "carol")

    def _plugin_with_block(self):
        db = FakeDB({blocks_key(self.viewer.steam_id): {str(self.speaker.steam_id)}})
        return make_plugin([self.speaker, self.viewer, self.third], db)

    def test_blocked_viewer_drops_general_chat(self):
        p = self._plugin_with_block()
        self.assertEqual(p.handle_server_command(self.viewer, CHAT_FROM_2), _minqlx.RET_STOP_EVENT)

    def test_blocked_viewer_drops_team_chat(self):
        p = self._plugin_with_block()
        self.assertEqual(p.handle_server_command(self.viewer, TCHAT_FROM_2), _minqlx.RET_STOP_EVENT)

    def test_other_players_still_receive(self):
        p = self._plugin_with_block()
        self.assertIsNone(p.handle_server_command(self.third, CHAT_FROM_2))
        self.assertIsNone(p.handle_server_command(self.speaker, CHAT_FROM_2))

    def test_no_blocks_delivers(self):
        p = make_plugin([self.speaker, self.viewer])
        self.assertIsNone(p.handle_server_command(self.viewer, CHAT_FROM_2))

    def test_broadcast_ignored(self):
        p = self._plugin_with_block()
        self.assertIsNone(p.handle_server_command(None, CHAT_FROM_2))

    def test_non_chat_traffic_ignored(self):
        p = self._plugin_with_block()
        for cmd in (SCORES, CONFIGSTRING, CENTERPRINT):
            self.assertIsNone(p.handle_server_command(self.viewer, cmd))

    def test_unparseable_chat_fails_open(self):
        p = self._plugin_with_block()
        self.assertIsNone(p.handle_server_command(self.viewer, 'chat "?? weird"'))

    def test_drop_return_is_not_false_equivalent(self):
        """Regression guard for the RET_NONE trap.

        minqlx's dispatcher checks `res == minqlx.RET_NONE` before anything else,
        and RET_NONE is 0. Because `False == 0` is True in Python, returning a
        literal False here would be read as "continue" and the message would be
        delivered anyway -- a block that silently does nothing. Anyone tempted to
        simplify the return to False will trip this test.
        """
        p = self._plugin_with_block()
        res = p.handle_server_command(self.viewer, CHAT_FROM_2)
        self.assertNotEqual(res, _minqlx.RET_NONE)
        self.assertNotEqual(res, False)
        self.assertEqual(res, _minqlx.RET_STOP_EVENT)


class TestSlotReuse(unittest.TestCase):
    def test_recycled_slot_does_not_inherit_block(self):
        speaker = FakePlayer(2, 76561197973279898, "Doomsday")
        viewer = FakePlayer(3, 76561199813623382, "sakura")
        db = FakeDB({blocks_key(viewer.steam_id): {str(speaker.steam_id)}})
        p = make_plugin([speaker, viewer], db)
        self.assertEqual(p.handle_server_command(viewer, CHAT_FROM_2), _minqlx.RET_STOP_EVENT)

        # Blocked player leaves; a different person takes client slot 2.
        p._roster = [viewer]
        p.handle_player_disconnect(speaker, "quit")
        newcomer = FakePlayer(2, 76561190000000099, "newcomer")
        p._roster = [newcomer, viewer]
        p.handle_player_loaded(newcomer)

        self.assertIsNone(p.handle_server_command(viewer, CHAT_FROM_2))

    def test_block_survives_blocker_reconnect(self):
        speaker = FakePlayer(2, 76561197973279898, "Doomsday")
        viewer = FakePlayer(3, 76561199813623382, "sakura")
        db = FakeDB({blocks_key(viewer.steam_id): {str(speaker.steam_id)}})
        p = make_plugin([speaker, viewer], db)

        p._roster = [speaker]
        p.handle_player_disconnect(viewer, "quit")
        self.assertEqual(p._active, {})

        returning = FakePlayer(5, viewer.steam_id, "sakura")
        p._roster = [speaker, returning]
        p.handle_player_loaded(returning)
        self.assertEqual(p.handle_server_command(returning, CHAT_FROM_2), _minqlx.RET_STOP_EVENT)


class TestCommands(unittest.TestCase):
    def setUp(self):
        self.caller = FakePlayer(3, 76561199813623382, "sakura")
        self.target = FakePlayer(2, 76561197973279898, "Doomsday")

    def test_block_by_client_id(self):
        p = make_plugin([self.target, self.caller])
        p.cmd_block(self.caller, ["!block", "2"], None)
        self.assertIn(self.target.steam_id, p._blocks[self.caller.steam_id])
        self.assertEqual(p.handle_server_command(self.caller, CHAT_FROM_2), _minqlx.RET_STOP_EVENT)

    def test_block_by_steam_id(self):
        p = make_plugin([self.target, self.caller])
        p.cmd_block(self.caller, ["!block", str(self.target.steam_id)], None)
        self.assertIn(self.target.steam_id, p._blocks[self.caller.steam_id])

    def test_commands_never_pass_through_to_chat(self):
        # The command text must not be broadcast; RET_STOP_ALL is what prevents it.
        p = make_plugin([self.target, self.caller])
        for call in (
            lambda: p.cmd_block(self.caller, ["!block", "2"], None),
            lambda: p.cmd_block(self.caller, ["!block"], None),
            lambda: p.cmd_unblock(self.caller, ["!unblock", "2"], None),
            lambda: p.cmd_blocklist(self.caller, ["!blocklist"], None),
        ):
            self.assertEqual(call(), _minqlx.RET_STOP_ALL)

    def test_cannot_block_self(self):
        p = make_plugin([self.target, self.caller])
        p.cmd_block(self.caller, ["!block", "3"], None)
        self.assertNotIn(self.caller.steam_id, p._blocks.get(self.caller.steam_id, set()))
        self.assertIn("yourself", " ".join(self.caller.told))

    def test_cannot_block_bot(self):
        bot = FakePlayer(4, 2, "botA")
        p = make_plugin([self.target, self.caller, bot])
        p.cmd_block(self.caller, ["!block", "4"], None)
        self.assertNotIn(2, p._blocks.get(self.caller.steam_id, set()))
        self.assertIn("bot", " ".join(self.caller.told))

    def test_duplicate_block_reports(self):
        p = make_plugin([self.target, self.caller])
        p.cmd_block(self.caller, ["!block", "2"], None)
        self.caller.told.clear()
        p.cmd_block(self.caller, ["!block", "2"], None)
        self.assertIn("already", " ".join(self.caller.told))

    def test_cap_enforced(self):
        p = make_plugin([self.target, self.caller], max_entries=1)
        p.cmd_block(self.caller, ["!block", "2"], None)
        self.caller.told.clear()
        p.cmd_block(self.caller, ["!block", "76561190000000123"], None)
        self.assertIn("full", " ".join(self.caller.told))
        self.assertEqual(len(p._blocks[self.caller.steam_id]), 1)

    def test_unknown_client_id_reports(self):
        p = make_plugin([self.target, self.caller])
        p.cmd_block(self.caller, ["!block", "40"], None)
        self.assertIn("No player", " ".join(self.caller.told))

    def test_non_numeric_id_reports(self):
        p = make_plugin([self.target, self.caller])
        p.cmd_block(self.caller, ["!block", "Doomsday"], None)
        self.assertIn("Invalid ID", " ".join(self.caller.told))

    def test_unblock_restores_delivery(self):
        p = make_plugin([self.target, self.caller])
        p.cmd_block(self.caller, ["!block", "2"], None)
        self.assertEqual(p.handle_server_command(self.caller, CHAT_FROM_2), _minqlx.RET_STOP_EVENT)
        p.cmd_unblock(self.caller, ["!unblock", "2"], None)
        self.assertIsNone(p.handle_server_command(self.caller, CHAT_FROM_2))

    def test_unblock_when_not_blocked(self):
        p = make_plugin([self.target, self.caller])
        p.cmd_unblock(self.caller, ["!unblock", "2"], None)
        self.assertIn("not blocked", " ".join(self.caller.told))

    def test_blocklist_empty(self):
        p = make_plugin([self.target, self.caller])
        p.cmd_blocklist(self.caller, ["!blocklist"], None)
        self.assertIn("not blocked anyone", " ".join(self.caller.told))

    def test_blocklist_shows_entries(self):
        p = make_plugin([self.target, self.caller])
        p.cmd_block(self.caller, ["!block", "2"], None)
        self.caller.told.clear()
        p.cmd_blocklist(self.caller, ["!blocklist"], None)
        self.assertIn(str(self.target.steam_id), " ".join(self.caller.told))


class TestRedisFailure(unittest.TestCase):
    def test_load_failure_does_not_raise(self):
        caller = FakePlayer(3, 76561199813623382, "sakura")
        p = make_plugin([caller], FakeDB(fail=True))
        self.assertEqual(p._blocks, {})

    def test_chat_still_delivered_when_redis_down(self):
        speaker = FakePlayer(2, 76561197973279898, "Doomsday")
        viewer = FakePlayer(3, 76561199813623382, "sakura")
        p = make_plugin([speaker, viewer], FakeDB(fail=True))
        self.assertIsNone(p.handle_server_command(viewer, CHAT_FROM_2))

    def test_block_reports_failure(self):
        caller = FakePlayer(3, 76561199813623382, "sakura")
        target = FakePlayer(2, 76561197973279898, "Doomsday")
        p = make_plugin([target, caller], FakeDB(fail=True))
        p.cmd_block(caller, ["!block", "2"], None)
        self.assertIn("Could not save", " ".join(caller.told))

    def test_malformed_db_entry_skipped(self):
        viewer = FakePlayer(3, 76561199813623382, "sakura")
        db = FakeDB({blocks_key(viewer.steam_id): {"not-a-number", "76561197973279898"}})
        p = make_plugin([viewer], db)
        self.assertEqual(p._blocks[viewer.steam_id], {76561197973279898})


if __name__ == "__main__":
    unittest.main(verbosity=2)
