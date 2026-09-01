"""Unit tests for restore/qlmatch.py: .qlmatch pack listing (manifest.json
only, via zip central directory), list -> N cache resolution, mm:ss ->
snapshot mapping, and item/inventory degradation when a sidecar doesn't
carry every field yet (see the module's own docstring for the contract
this is written against - no producer exists in the repo yet).
"""

import gzip
import json
import os
import sys
import unittest
import zipfile

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "ql-assets", "data", "minqlx-plugins")
)

from restore import qlmatch  # noqa: E402


def _write_pack(path, match_id, map_name, players, gametype="1", window=None):
    manifest = {
        "format": "ql-match",
        "version": 1,
        "match_id": match_id,
        "map": map_name,
        "gametype": gametype,
        "index_framing": "with_header",
        "window": window if window is not None else {
            "start_server_time": 1000,
            "end_server_time": 500000,
            "game_start_server_time": 5000,
        },
        "demos": [
            {"file": "demos/p{}.dm_91".format(i), "pov_index": i, "client_num": i, "name": name, "index": None}
            for i, name in enumerate(players)
        ],
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for i in range(len(players)):
            # Decoy members - listing must never read these.
            zf.writestr("demos/p{}.dm_91".format(i), b"not a real demo, just bytes")
        zf.writestr("index/p0.snaps.json", b"[]")
    return manifest


def _write_sidecar(path, events, meta=None):
    doc = {"meta": meta or {}, "events": events}
    with gzip.open(path, "wb") as handle:
        handle.write(json.dumps(doc).encode("utf-8"))


class ListPacksTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp_dir = tempfile.mkdtemp()

    def test_lists_only_manifest_and_numbers_newest_first(self):
        _write_pack(
            os.path.join(self.tmp_dir, "20260101T000000Z_bloodrun.qlmatch"),
            "20260101T000000Z", "bloodrun", ["alice", "bob"],
        )
        _write_pack(
            os.path.join(self.tmp_dir, "20260201T000000Z_campgrounds.qlmatch"),
            "20260201T000000Z", "campgrounds", ["carol", "dave"],
        )

        requested_members = []
        original_read = zipfile.ZipFile.read

        def spy_read(self, name, *a, **kw):
            requested_members.append(name)
            return original_read(self, name, *a, **kw)

        zipfile.ZipFile.read = spy_read
        try:
            rows = qlmatch.list_packs(self.tmp_dir)
        finally:
            zipfile.ZipFile.read = original_read

        self.assertEqual(requested_members, ["manifest.json", "manifest.json"])
        self.assertEqual(len(rows), 2)
        # Newest match_id (20260201...) first.
        self.assertEqual(rows[0]["match_id"], "20260201T000000Z")
        self.assertEqual(rows[0]["index"], 1)
        self.assertEqual(rows[1]["match_id"], "20260101T000000Z")
        self.assertEqual(rows[1]["index"], 2)
        # window end 500000 - game_start 5000 = 495000 ms = 8:15
        self.assertEqual(rows[0]["duration_ms"], 495000)
        self.assertEqual(qlmatch.format_clock(rows[0]["duration_ms"]), "8:15")

    def test_filter_by_map_substring(self):
        _write_pack(
            os.path.join(self.tmp_dir, "20260101T000000Z_bloodrun.qlmatch"),
            "20260101T000000Z", "bloodrun", ["alice"],
        )
        _write_pack(
            os.path.join(self.tmp_dir, "20260201T000000Z_campgrounds.qlmatch"),
            "20260201T000000Z", "campgrounds", ["bob"],
        )
        rows = qlmatch.list_packs(self.tmp_dir, filter_substr="bloodrun")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["map"], "bloodrun")
        self.assertEqual(rows[0]["index"], 1)

    def test_filter_by_player_substring(self):
        _write_pack(
            os.path.join(self.tmp_dir, "20260101T000000Z_bloodrun.qlmatch"),
            "20260101T000000Z", "bloodrun", ["alice", "bob"],
        )
        _write_pack(
            os.path.join(self.tmp_dir, "20260201T000000Z_campgrounds.qlmatch"),
            "20260201T000000Z", "campgrounds", ["carol", "dave"],
        )
        rows = qlmatch.list_packs(self.tmp_dir, filter_substr="carol")
        self.assertEqual(len(rows), 1)
        self.assertIn("carol", rows[0]["players"])

    def test_skips_pack_with_bad_manifest(self):
        good = os.path.join(self.tmp_dir, "20260101T000000Z_bloodrun.qlmatch")
        _write_pack(good, "20260101T000000Z", "bloodrun", ["alice"])
        bad = os.path.join(self.tmp_dir, "20260101T000001Z_broken.qlmatch")
        with zipfile.ZipFile(bad, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("manifest.json", b"{not valid json")
        rows = qlmatch.list_packs(self.tmp_dir)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["map"], "bloodrun")

    def test_empty_dir_returns_empty_list(self):
        self.assertEqual(qlmatch.list_packs(self.tmp_dir), [])

    def test_missing_dir_returns_empty_list(self):
        self.assertEqual(qlmatch.list_packs(os.path.join(self.tmp_dir, "nope")), [])

    def test_list_falls_back_to_sidecar_duration_when_window_is_sentinel(self):
        _write_pack(
            os.path.join(self.tmp_dir, "20260101T000000Z_bloodrun.qlmatch"),
            "20260101T000000Z", "bloodrun", ["alice"],
            window={"start_server_time": -1, "end_server_time": -1, "game_start_server_time": -1},
        )
        _write_sidecar(
            os.path.join(self.tmp_dir, "20260101T000000Z_bloodrun.replay.json.gz"),
            events=[{"event": "positions", "game_time_ms": 121175, "players": []}],
        )
        rows = qlmatch.list_packs(self.tmp_dir)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(qlmatch.duration_ms_from_window(rows[0]["window"]))
        self.assertEqual(rows[0]["duration_ms"], 121175)
        self.assertEqual(qlmatch.format_clock(rows[0]["duration_ms"]), "2:01.175")


class ResolveByIndexCacheTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp_dir = tempfile.mkdtemp()

    def test_index_resolves_against_the_cache_it_was_produced_from(self):
        path_a = os.path.join(self.tmp_dir, "20260101T000000Z_bloodrun.qlmatch")
        _write_pack(path_a, "20260101T000000Z", "bloodrun", ["alice"])

        cache1 = qlmatch.list_packs(self.tmp_dir)
        self.assertEqual(len(cache1), 1)
        self.assertEqual(qlmatch.resolve_pack_by_index(cache1, 1)["match_id"], "20260101T000000Z")

        # A newer match lands - it sorts to #1, bumping the first pack to #2.
        path_b = os.path.join(self.tmp_dir, "20260201T000000Z_campgrounds.qlmatch")
        _write_pack(path_b, "20260201T000000Z", "campgrounds", ["bob"])
        cache2 = qlmatch.list_packs(self.tmp_dir)
        self.assertEqual(len(cache2), 2)
        self.assertEqual(qlmatch.resolve_pack_by_index(cache2, 1)["match_id"], "20260201T000000Z")
        self.assertEqual(qlmatch.resolve_pack_by_index(cache2, 2)["match_id"], "20260101T000000Z")

        # Resolving against the STALE cache1 must still give the old #1
        # (the pack that was actually #1 in that listing), proving
        # resolution reads the cache object passed in, not a fresh scan.
        self.assertEqual(qlmatch.resolve_pack_by_index(cache1, 1)["match_id"], "20260101T000000Z")

    def test_resolve_does_not_touch_disk(self):
        path_a = os.path.join(self.tmp_dir, "20260101T000000Z_bloodrun.qlmatch")
        _write_pack(path_a, "20260101T000000Z", "bloodrun", ["alice"])
        cache = qlmatch.list_packs(self.tmp_dir)

        os.remove(path_a)  # Pack gone from disk...
        # ...but the cached summary is still resolvable (pure dict lookup).
        row = qlmatch.resolve_pack_by_index(cache, 1)
        self.assertIsNotNone(row)
        self.assertEqual(row["match_id"], "20260101T000000Z")

    def test_out_of_range_and_non_numeric_index_return_none(self):
        path_a = os.path.join(self.tmp_dir, "20260101T000000Z_bloodrun.qlmatch")
        _write_pack(path_a, "20260101T000000Z", "bloodrun", ["alice"])
        cache = qlmatch.list_packs(self.tmp_dir)
        self.assertIsNone(qlmatch.resolve_pack_by_index(cache, 99))
        self.assertIsNone(qlmatch.resolve_pack_by_index(cache, "not-a-number"))


class ParseClockTests(unittest.TestCase):
    def test_mmss(self):
        self.assertEqual(qlmatch.parse_clock_to_ms("1:05"), 65000)
        self.assertEqual(qlmatch.parse_clock_to_ms("0:00"), 0)
        self.assertEqual(qlmatch.parse_clock_to_ms("12:34"), 754000)

    def test_mmss_with_fraction(self):
        self.assertEqual(qlmatch.parse_clock_to_ms("0:01.500"), 1500)

    def test_rejects_bad_seconds(self):
        with self.assertRaises(ValueError):
            qlmatch.parse_clock_to_ms("1:75")

    def test_rejects_non_mmss(self):
        with self.assertRaises(ValueError):
            qlmatch.parse_clock_to_ms("65")
        with self.assertRaises(ValueError):
            qlmatch.parse_clock_to_ms("")
        with self.assertRaises(ValueError):
            qlmatch.parse_clock_to_ms("abc")

    def test_format_clock_roundtrip(self):
        self.assertEqual(qlmatch.format_clock(0), "0:00")
        self.assertEqual(qlmatch.format_clock(65000), "1:05")
        self.assertEqual(qlmatch.format_clock(120000), "2:00")
        self.assertEqual(qlmatch.format_clock(1500), "0:01.500")
        self.assertEqual(qlmatch.format_clock(None), "?")
        self.assertEqual(qlmatch.parse_clock_to_ms(qlmatch.format_clock(125500)), 125500)

    def test_duration_from_window_ignores_sentinel_minus_one(self):
        self.assertIsNone(qlmatch.duration_ms_from_window({
            "start_server_time": -1,
            "end_server_time": -1,
            "game_start_server_time": -1,
        }))
        self.assertEqual(qlmatch.duration_ms_from_window({
            "start_server_time": 1000,
            "end_server_time": 121000,
            "game_start_server_time": 1000,
        }), 120000)


class SnapshotAndCheckpointTests(unittest.TestCase):
    MAP_SPAWNS = {
        "mega": {"entity_id": 42, "x": 784.0, "y": -224.0, "z": 88.0, "classname": "item_health_mega"},
        "rl": {"entity_id": 35, "x": 672.0, "y": -1368.0, "z": 272.0, "classname": "weapon_rocketlauncher"},
    }

    def _events(self):
        return [
            {
                "event": "positions", "game_time_ms": 0,
                "players": [
                    {"clientNum": 0, "x": 0.0, "y": 0.0, "z": 0.0, "health": 200, "armor": 100,
                     "steam_id64": "76561197960265729"},
                ],
            },
            {
                "event": "positions", "game_time_ms": 10000,
                "players": [
                    {"clientNum": 0, "x": 100.0, "y": 50.0, "z": 0.0, "health": 150, "armor": 50,
                     "steam_id64": "76561197960265729"},
                    # No health/armor at all - old single-POV-derived replay shape.
                    {"clientNum": 1, "x": 200.0, "y": 60.0, "z": 0.0},
                ],
            },
            {
                "event": "positions", "game_time_ms": 20000,
                "players": [
                    {"clientNum": 0, "x": 300.0, "y": 70.0, "z": 0.0, "health": 0, "armor": 0,
                     "steam_id64": "76561197960265729"},
                ],
            },
            {"event": "pickup", "game_time_ms": 5000, "action": "pickup",
             "item": "item_health_mega", "x": 784.0, "y": -224.0, "z": 88.0, "respawn_sec": 35},
            {"event": "pickup", "game_time_ms": 8000, "action": "pickup",
             "item": "weapon_rocketlauncher", "x": 672.0, "y": -1368.0, "z": 272.0, "respawn_sec": 5},
            {"event": "pickup", "game_time_ms": 13000, "action": "respawn",
             "item": "weapon_rocketlauncher", "x": 672.0, "y": -1368.0, "z": 272.0},
        ]

    def test_nearest_snapshot_at_or_before_target(self):
        events = self._events()
        ev, t = qlmatch.nearest_positions_event(events, 15000)
        self.assertEqual(t, 10000)
        self.assertEqual(ev["players"][1]["clientNum"], 1)

        ev, t = qlmatch.nearest_positions_event(events, 0)
        self.assertEqual(t, 0)

        ev, t = qlmatch.nearest_positions_event(events, -1)
        self.assertIsNone(ev)

    def test_build_checkpoint_doc_degrades_gracefully_without_inventory(self):
        sidecar = {"meta": {"generator_version": 1}, "events": self._events()}
        doc, warning, snap_t = qlmatch.build_checkpoint_doc(
            sidecar, 15000, self.MAP_SPAWNS, "bloodrun", wall_now=1000.0,
        )
        self.assertEqual(snap_t, 10000)
        self.assertIsNone(warning)

        players_by_cid = {p["cid"]: p for p in doc["players"]}
        self.assertEqual(players_by_cid[0]["h"], 150)
        self.assertEqual(players_by_cid[0]["a"], 50)
        self.assertNotIn("lo", players_by_cid[0])
        self.assertNotIn("am", players_by_cid[0])
        # Player without health/armor in the sidecar gets safe defaults,
        # not a fabricated "dead" (0 hp) state, and does not crash the build.
        self.assertEqual(players_by_cid[1]["h"], 100)
        self.assertEqual(players_by_cid[1]["a"], 0)
        self.assertNotIn("dead", players_by_cid[1])

    def test_dead_flag_set_from_zero_health(self):
        sidecar = {"meta": {}, "events": self._events()}
        doc, _warning, _snap_t = qlmatch.build_checkpoint_doc(
            sidecar, 20000, self.MAP_SPAWNS, "bloodrun", wall_now=1000.0,
        )
        players_by_cid = {p["cid"]: p for p in doc["players"]}
        self.assertEqual(players_by_cid[0]["dead"], 1)

    def test_item_pending_when_picked_up_and_not_yet_respawned(self):
        sidecar = {"meta": {}, "events": self._events()}
        # t=10000: mega picked up at 5000 (respawn_sec=35, so still hidden);
        # RL picked up at 8000 but respawned again at 13000 > 10000, so RL
        # is also still "pending" at this exact instant.
        doc, _warning, _snap_t = qlmatch.build_checkpoint_doc(
            sidecar, 10000, self.MAP_SPAWNS, "bloodrun", wall_now=1000.0,
        )
        items_by_alias = {it.get("k"): it for it in doc["items"]}
        self.assertIn("mega", items_by_alias)
        self.assertEqual(items_by_alias["mega"]["s"], 2)

    def test_item_available_after_respawn_observed(self):
        sidecar = {"meta": {}, "events": self._events()}
        # t=20000: RL respawn event at 13000 already happened -> available,
        # so it must be absent from items[] (state 1 = default, not tracked).
        doc, _warning, _snap_t = qlmatch.build_checkpoint_doc(
            sidecar, 20000, self.MAP_SPAWNS, "bloodrun", wall_now=1000.0,
        )
        aliases = {it.get("k") for it in doc["items"]}
        self.assertNotIn("rl", aliases)

    def test_inventory_used_when_present_in_sidecar(self):
        events = [
            {
                "event": "positions", "game_time_ms": 0,
                "players": [
                    {
                        "clientNum": 0, "x": 0.0, "y": 0.0, "z": 0.0,
                        "health": 100, "armor": 50,
                        "weapons": ["rl", "lg"],
                        "ammo": {"rl": 10, "lg": 60, "bfg": 5},
                    },
                ],
            },
        ]
        sidecar = {"meta": {"generator_version": 2}, "events": events}
        doc, _warning, _snap_t = qlmatch.build_checkpoint_doc(
            sidecar, 0, {}, "bloodrun", wall_now=1000.0,
        )
        row = doc["players"][0]
        self.assertIn("lo", row)
        self.assertIn("am", row)
        self.assertEqual(row["am"], {"rl": 10, "lg": 60})  # bfg not an AMMO_KEYS entry -> dropped

    def test_inventory_bitmask_and_ammo_array_shapes_from_packer_sidecar(self):
        # The shapes qlmatch-to-replay.mjs actually writes: `weapons` is the
        # raw STAT_WEAPONS bitmask (bit i = dm_91 weapon index i, which is
        # bit-identical to codec.WEAPON_ORDER's loadout mask) and `ammo` is
        # the ps.ammo array indexed by the same weapon indices, where 65535
        # is the unsigned view of -1 (infinite, e.g. gauntlet).
        weapons_mask = (1 << 1) | (1 << 2) | (1 << 5)  # g + mg + rl
        ammo = [0] * 16
        ammo[1] = 65535  # gauntlet: infinite -> dropped
        ammo[2] = 100    # mg
        ammo[5] = 25     # rl
        events = [
            {
                "event": "positions", "game_time_ms": 0,
                "players": [
                    {
                        "clientNum": 0, "x": 0.0, "y": 0.0, "z": 0.0,
                        "health": 100, "armor": 50,
                        "weapons": weapons_mask,
                        "ammo": ammo,
                    },
                ],
            },
        ]
        sidecar = {"meta": {"generator_version": 1}, "events": events}
        doc, _warning, _snap_t = qlmatch.build_checkpoint_doc(
            sidecar, 0, {}, "bloodrun", wall_now=1000.0,
        )
        row = doc["players"][0]
        self.assertEqual(row["lo"], weapons_mask)
        # Zeros are kept on purpose: an owned weapon shot dry must restore to
        # 0, not to whatever the live player happens to carry.
        self.assertEqual(
            row["am"],
            {"mg": 100, "rl": 25, "sg": 0, "gl": 0, "lg": 0, "rg": 0, "pg": 0, "cg": 0},
        )

    def test_raises_when_no_snapshot_before_target(self):
        sidecar = {"meta": {}, "events": self._events()}
        with self.assertRaises(ValueError):
            qlmatch.build_checkpoint_doc(sidecar, -100, self.MAP_SPAWNS, "bloodrun", wall_now=1000.0)

    def test_raises_when_requested_time_past_demo_duration_window(self):
        # ~2 minute demo (window 120000 ms). Requesting 3:00 must error
        # instead of silently restoring the last snapshot at 2:00.
        sidecar = {"meta": {}, "events": self._events() + [
            {
                "event": "positions", "game_time_ms": 120000,
                "players": [
                    {"clientNum": 0, "x": 9.0, "y": 9.0, "z": 0.0, "health": 100, "armor": 0},
                ],
            },
        ]}
        window = {
            "start_server_time": 5000,
            "end_server_time": 125000,
            "game_start_server_time": 5000,
        }
        self.assertEqual(qlmatch.duration_ms_from_window(window), 120000)
        with self.assertRaises(ValueError) as ctx:
            qlmatch.build_checkpoint_doc(
                sidecar, 180000, self.MAP_SPAWNS, "bloodrun", wall_now=1000.0, window=window,
            )
        self.assertIn("past demo duration", str(ctx.exception))
        self.assertIn("2:00", str(ctx.exception))
        self.assertIn("3:00", str(ctx.exception))
        # Exact end of the demo is still allowed (uses last snapshot).
        doc, _warning, snap_t = qlmatch.build_checkpoint_doc(
            sidecar, 120000, self.MAP_SPAWNS, "bloodrun", wall_now=1000.0, window=window,
        )
        self.assertEqual(snap_t, 120000)
        self.assertEqual(doc["players"][0]["x"], 9.0)

    def test_raises_when_requested_time_past_last_snapshot_without_window(self):
        sidecar = {"meta": {}, "events": self._events()}
        with self.assertRaises(ValueError) as ctx:
            qlmatch.build_checkpoint_doc(
                sidecar, 180000, self.MAP_SPAWNS, "bloodrun", wall_now=1000.0,
            )
        self.assertIn("past demo duration", str(ctx.exception))

    def test_pause_warning_present_when_meta_has_pause_windows(self):
        sidecar = {"meta": {"pause_windows": [{"start_ms": 1000, "end_ms": 2000}]}, "events": self._events()}
        doc, warning, _snap_t = qlmatch.build_checkpoint_doc(
            sidecar, 0, self.MAP_SPAWNS, "bloodrun", wall_now=1000.0,
        )
        self.assertIsNotNone(warning)

    def test_no_pause_warning_when_meta_has_no_pause_info(self):
        sidecar = {"meta": {}, "events": self._events()}
        doc, warning, _snap_t = qlmatch.build_checkpoint_doc(
            sidecar, 0, self.MAP_SPAWNS, "bloodrun", wall_now=1000.0,
        )
        self.assertIsNone(warning)


class SidecarRoundTripTests(unittest.TestCase):
    def test_load_sidecar_gzip_json_roundtrip(self):
        import tempfile

        tmp_dir = tempfile.mkdtemp()
        path = os.path.join(tmp_dir, "20260101T000000Z_bloodrun.replay.json.gz")
        _write_sidecar(path, events=[{"event": "positions", "game_time_ms": 0, "players": []}])
        doc = qlmatch.load_sidecar(path)
        self.assertIn("events", doc)
        self.assertEqual(doc["events"][0]["game_time_ms"], 0)

    def test_sidecar_path_for_uses_match_id_and_map_not_pack_filename(self):
        path = qlmatch.sidecar_path_for("/home/ql/demos", "20260101T000000Z", "bloodrun")
        self.assertEqual(
            os.path.basename(path), "20260101T000000Z_bloodrun.replay.json.gz"
        )


if __name__ == "__main__":
    unittest.main()
