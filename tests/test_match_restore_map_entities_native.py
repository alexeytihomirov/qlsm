"""Regression test: match_restore_util.load_map_spawns() must prefer live
minqlxtended.map_entities() (BSP entity lump) over the bundled
data/map_entities/<map>.json snapshot, and must fall back to the JSON path
when the native function is unavailable or errors out.
"""

import collections
import importlib
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "ql-assets", "data", "minqlx-plugins")
)

_MapEntity = collections.namedtuple("MapEntity", ("classname", "origin", "keys"))


def _install_minqlx_mock(map_entities_fn=None):
    mock = types.ModuleType("minqlx")
    if map_entities_fn is not None:
        mock.map_entities = map_entities_fn
    sys.modules.pop("minqlxtended", None)
    sys.modules["minqlx"] = mock
    sys.modules.pop("match_restore_util", None)
    return importlib.import_module("match_restore_util")


_FIXTURE_JSON = {
    "map_name": "fixturemap",
    "entities": [
        {"id": 2, "classname": "item_health_mega", "x": 1.0, "y": 2.0, "z": 3.0},
        {"id": 3, "classname": "target_location", "x": 4.0, "y": 5.0, "z": 6.0},
    ],
}


class NativeMapEntitiesTests(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop("minqlx", None)
        sys.modules.pop("match_restore_util", None)

    def _write_fixture_json(self, util, map_key):
        tmp_dir = tempfile.mkdtemp()
        with open(os.path.join(tmp_dir, map_key + ".json"), "w", encoding="utf-8") as handle:
            json.dump(_FIXTURE_JSON, handle)
        util._data_dir = lambda: tmp_dir

    def test_native_path_used_when_available(self):
        entities = [
            _MapEntity("worldspawn", None, {}),
            _MapEntity("item_health_mega", (784.0, -224.0, 88.0), {}),
            _MapEntity("target_location", (10.0, 20.0, 30.0), {}),
            _MapEntity("weapon_railgun", (1.0, 2.0, 3.0), {}),
        ]
        calls = []

        def fake_map_entities(mapname):
            calls.append(mapname)
            return entities

        util = _install_minqlx_mock(fake_map_entities)
        table = util.load_map_spawns("bloodrun", "bloodrun")

        self.assertEqual(calls, ["bloodrun"])
        self.assertIn("mega", table)
        self.assertEqual(table["mega"]["classname"], "item_health_mega")
        self.assertEqual((table["mega"]["x"], table["mega"]["y"], table["mega"]["z"]), (784.0, -224.0, 88.0))
        self.assertIn("rg", table)
        # worldspawn/target_location are not restorable pickups
        self.assertNotIn("target_location", [row["classname"] for row in table.values()])

    def test_falls_back_to_json_when_native_missing(self):
        util = _install_minqlx_mock(map_entities_fn=None)
        self.assertFalse(hasattr(util.minqlx, "map_entities"))
        self._write_fixture_json(util, "fixturemap")
        table = util.load_map_spawns("fixturemap")
        self.assertIn("mega", table)

    def test_falls_back_to_json_when_native_raises(self):
        def broken(mapname):
            raise RuntimeError("bsp read failed")

        util = _install_minqlx_mock(broken)
        self._write_fixture_json(util, "fixturemap")
        table = util.load_map_spawns("fixturemap", "fixturemap")
        self.assertIn("mega", table)

    def test_native_result_used_even_when_empty(self):
        util = _install_minqlx_mock(lambda mapname: [])
        self._write_fixture_json(util, "fixturemap")
        table = util.load_map_spawns("fixturemap", "fixturemap")
        # native call succeeded (even if empty) - must NOT fall back to the JSON fixture
        self.assertEqual(table, {})


if __name__ == "__main__":
    unittest.main()
