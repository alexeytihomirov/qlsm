"""Unit tests for qlsm_plugins/tournament_access.py — _steam_id_in_set()."""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock

# ── Minimal minqlx mock ──────────────────────────────────────────────────────

minqlx_mock = types.ModuleType("minqlx")


class _Priority:
    HIGH = 0


minqlx_mock.Priority = _Priority
minqlx_mock.Return = types.SimpleNamespace(STOP_ALL="stop_all")
minqlx_mock.owner = lambda: None
minqlx_mock.console_command = lambda *args, **kwargs: None
minqlx_mock.next_frame = lambda fn: fn


class _FakePlugin:
    def __init__(self):
        self.db = MagicMock()
        self.logger = MagicMock()
        self._cvars = {}

    def set_cvar_once(self, key, value):
        self._cvars.setdefault(key, value)

    def add_hook(self, *args, **kwargs):
        pass

    def get_cvar(self, key, type_=None):
        val = self._cvars.get(key)
        if type_ is bool:
            if val is None:
                return None
            return str(val).strip().lower() not in ("0", "false", "")
        return val


minqlx_mock.Plugin = _FakePlugin
sys.modules["minqlx"] = minqlx_mock

# ── Import plugin after mock is in place ────────────────────────────────────

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ql-assets", "data", "minqlx-plugins"))
from tournament_access import tournament_access  # noqa: E402


class TestSteamIdInSet(unittest.TestCase):
    def test_exact_string_match_accepted(self):
        self.assertTrue(
            tournament_access._steam_id_in_set("76561197960287930", {"76561197960287930"})
        )

    def test_exact_int_match_accepted_despite_string_mismatch(self):
        # "007" != "7" as strings but are the same id as ints
        self.assertTrue(tournament_access._steam_id_in_set("7", {"007"}))

    def test_off_by_one_plus_rejected(self):
        self.assertFalse(
            tournament_access._steam_id_in_set("76561197960287931", {"76561197960287930"})
        )

    def test_off_by_one_minus_rejected(self):
        self.assertFalse(
            tournament_access._steam_id_in_set("76561197960287929", {"76561197960287930"})
        )

    def test_unrelated_id_rejected(self):
        self.assertFalse(
            tournament_access._steam_id_in_set("11111111111111111", {"76561197960287930"})
        )

    def test_empty_steam_rejected(self):
        self.assertFalse(tournament_access._steam_id_in_set("", {"76561197960287930"}))

    def test_empty_allowed_rejected(self):
        self.assertFalse(tournament_access._steam_id_in_set("76561197960287930", set()))

    def test_non_numeric_steam_falls_back_to_string_compare(self):
        self.assertFalse(tournament_access._steam_id_in_set("not-a-number", {"76561197960287930"}))

    def test_non_numeric_allowed_entry_skipped(self):
        # "garbage" can't be cast to int and must not abort the scan for
        # the still-valid numeric match later in the set.
        self.assertTrue(tournament_access._steam_id_in_set("7", {"garbage", "007"}))


if __name__ == "__main__":
    unittest.main()
