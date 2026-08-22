"""Regression test: match_restore.py's checkpoint `pw` field must be seconds
end to end. `Player.powerups` (minqlxtended v1.0.0 property) is milliseconds;
`_export_powerups` must convert down to seconds, and `_apply_powerups` (which
always multiplies by 1000) must recover the original ms value on apply.
"""

import collections
import os
import sys
import types
import unittest

# ── Minimal minqlx mock (only `Plugin` is needed at import time — the two
#    methods under test are @staticmethod and never touch minqlx.*) ─────────

minqlx_mock = types.ModuleType("minqlx")


class _FakePlugin:
    def __init__(self):
        pass

    def set_cvar_once(self, *args, **kwargs):
        pass

    def add_hook(self, *args, **kwargs):
        pass

    def add_command(self, *args, **kwargs):
        pass


minqlx_mock.Plugin = _FakePlugin
sys.modules["minqlx"] = minqlx_mock

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "ql-assets", "data", "minqlx-plugins")
)

from match_restore import match_restore  # noqa: E402
from restore.codec import canonicalize  # noqa: E402


_Powerups = collections.namedtuple(
    "Powerups",
    ("quad", "battlesuit", "haste", "invulnerability", "invisibility", "regeneration"),
)

_ZERO_POWERUPS = _Powerups(0, 0, 0, 0, 0, 0)


class TestPowerupExportApplyRoundTrip(unittest.TestCase):
    def test_export_produces_seconds_not_raw_ms(self):
        player = types.SimpleNamespace(powerups=_ZERO_POWERUPS._replace(quad=30000))
        pw = match_restore._export_powerups(player)
        self.assertEqual(pw, {"quad": 30})

    def test_export_then_canonicalize_then_apply_recovers_original_ms(self):
        player = types.SimpleNamespace(powerups=_ZERO_POWERUPS._replace(quad=30000))
        pw = match_restore._export_powerups(player)

        doc = {
            "v": 2,
            "t_ms": 0,
            "map": "bloodrun",
            "players": [{"cid": 0, "x": 0, "y": 0, "z": 0, "pw": pw}],
        }
        canon_pw = canonicalize(doc)["players"][0]["pw"]

        target = types.SimpleNamespace(powerups=_ZERO_POWERUPS)
        match_restore._apply_powerups(target, canon_pw)

        self.assertEqual(target.powerups.quad, 30000)

    def test_manual_draft_seconds_path_still_applies_correctly(self):
        # `!restorecp player <slot> powerup quad 30` writes seconds directly,
        # bypassing _export_powerups entirely — must keep working unchanged.
        target = types.SimpleNamespace(powerups=_ZERO_POWERUPS)
        match_restore._apply_powerups(target, {"quad": 30})
        self.assertEqual(target.powerups.quad, 30000)


if __name__ == "__main__":
    unittest.main()
