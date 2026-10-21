"""Offline minqlx doubles; run directly with python3 (no QLDS required)."""
import importlib.util
import logging
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / "ql-assets/data/minqlx-plugins/autokick.py"


class NicknameTests(unittest.TestCase):
    def setUp(self):
        self.runtime = types.ModuleType("minqlx")
        self.runtime.__dict__.update(
            Plugin=type("Plugin", (), {}), RET_STOP_ALL=3,
            get_logger=Mock(return_value=Mock(spec=logging.Logger)))
        spec = importlib.util.spec_from_file_location("autokick_under_test", SOURCE)
        assert spec is not None and spec.loader is not None
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"minqlx": self.runtime}):
            spec.loader.exec_module(self.module)
        self.plugin = self.module.autokick.__new__(self.module.autokick)
        self.plugin.regex_patterns = [re.compile(r"\bnigga\b", re.IGNORECASE)]
        self.plugin.banned_words = {"literal-only"}
        self.plugin.warnings = {}
        self.plugin.mode = "kick"
        self.plugin.max_warnings = 1
        self.plugin.log = Mock()
        self.plugin.db = Mock()
        self.player = types.SimpleNamespace(name="clean player", steam_id=76561199818065399)

    def connect(self, name):
        self.player.name = name
        return self.plugin.handle_player_connect(self.player)

    def test_clean_name_allowed_without_io_or_redis(self):
        with patch("builtins.open", side_effect=AssertionError("connect opened file")):
            self.assertIsNone(self.connect("clean player"))
        self.plugin.log.assert_not_called()
        self.assertEqual(self.plugin.db.mock_calls, [])

    def test_case_insensitive_matching(self):
        for name in ("dirty nigga", "THE NIGGA DEMON"):
            with self.subTest(name=name):
                self.assertEqual(self.connect(name), self.module.NICKNAME_REJECTION)

    def test_embedded_color_codes_cannot_evade_regex(self):
        self.assertEqual(self.connect("^1ni^2gg^7a"), self.module.NICKNAME_REJECTION)

    def test_regex_boundaries_are_preserved(self):
        self.assertIsNone(self.connect("niggardly"))

    def test_literal_chat_word_does_not_block_nickname(self):
        self.assertIsNone(self.connect("literal-only"))

    def test_all_chat_modes_reject_without_warnings(self):
        for mode in ("kick", "warn", "silent"):
            with self.subTest(mode=mode):
                self.plugin.mode = mode
                self.plugin.max_warnings = 99
                self.assertEqual(self.connect("nigga"), self.module.NICKNAME_REJECTION)
        self.assertEqual(self.plugin.warnings, {})
        self.assertEqual(self.plugin.db.mock_calls, [])

    def test_admin_permission_does_not_bypass_check(self):
        self.plugin.db.get_permission.return_value = 5
        self.assertEqual(self.connect("nigga"), self.module.NICKNAME_REJECTION)
        self.plugin.db.get_permission.assert_not_called()

    def test_log_failure_does_not_allow_connection(self):
        self.plugin.log.side_effect = OSError("disk full")
        self.assertEqual(self.connect("nigga"), self.module.NICKNAME_REJECTION)
        self.runtime.get_logger.return_value.warning.assert_called_once()

    def test_rejection_log_escapes_newlines(self):
        self.connect("nigga\nforged event")
        entry = self.plugin.log.call_args.args[0]
        self.assertNotIn("\n", entry)
        self.assertIn("\\n", entry)
        self.assertIn("[REJECT-NAME]", entry)

    def test_empty_patterns_allow_connection(self):
        self.plugin.regex_patterns = []
        self.assertIsNone(self.connect("nigga"))

    def test_pattern_reload_changes_chat_and_connection_patterns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "autokick_patterns.txt"
            path.write_text("# ignored\n\n(?i)\\bnigga\\b\n[invalid\n", encoding="utf-8")
            self.plugin.patterns_file = str(path)
            self.plugin.reload_cvars = Mock()
            channel = Mock()
            self.plugin.cmd_reloadpatterns(self.player, [], channel)
            self.assertEqual(len(self.plugin.regex_patterns), 1)
            self.assertEqual(self.connect("NIGGA"), self.module.NICKNAME_REJECTION)
            path.write_text(r"\bblocked\b" + "\n", encoding="utf-8")
            self.plugin.cmd_reloadpatterns(self.player, [], channel)
            self.assertIsNone(self.connect("nigga"))
            self.assertEqual(self.connect("blocked"), self.module.NICKNAME_REJECTION)
            self.plugin.db.get_permission.return_value = 0
            self.plugin.process_violation = Mock()
            self.assertEqual(self.plugin.handle_chat(self.player, "blocked", channel),
                             self.runtime.RET_STOP_ALL)

    def test_init_registers_connect_hook_and_loads_patterns(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "autokick_patterns.txt").write_text("nigga\n", encoding="utf-8")
            plugin = self.module.autokick.__new__(self.module.autokick)
            plugin.db = Mock()
            plugin.db.smembers.return_value = set()
            plugin.add_hook = Mock()
            plugin.add_command = Mock()
            plugin.set_cvar_once = Mock()
            plugin.get_cvar = Mock(side_effect=lambda key: {
                "qlx_autokickWarnings": "1", "qlx_autokickMode": "warn"}[key])
            with patch.object(plugin, "get_minqlx_dir", return_value=directory):
                plugin.__init__()
            plugin.add_hook.assert_any_call("player_connect", plugin.handle_player_connect)
            self.player.name = "nigga"
            self.assertEqual(plugin.handle_player_connect(self.player), self.module.NICKNAME_REJECTION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
