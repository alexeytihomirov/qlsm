"""Unit tests for demo_native_manifest.py's pure manifest/window/zip-building
helpers. Ported from ql-server-core/tests/test_demo_native_manifest.py when
the native multi-POV demo capture plugin (demo_native_autorecord.py /
demo_native_manifest.py) moved into ql-assets/data/minqlx-plugins/ — the
plugin pool is this repo's source of truth (see
qlsm-plugin-pool-vs-builtin-preset-duplication in project memory), so its
tests move here too, same convention test_match_restore_*.py already uses
for sys.path'ing into the pool.

demo_native_manifest.py deliberately has no minqlx import so it can be
exercised here without a live QLDS/minqlx process, against synthetic
{match_id}_*.dm_91 placeholder files and index/*.snaps.json fixtures on disk.
"""

from __future__ import annotations

import json
import os
import sys
import zipfile

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "ql-assets", "data", "minqlx-plugins")
)

from demo_native_manifest import (  # noqa: E402
    build_entries,
    build_manifest,
    build_match_package,
    compute_window,
    discover_pov_files,
    index_path_for,
    parse_name_from_basename,
    write_qlmatch_zip,
)


MATCH_ID = "20260817T120000Z"
MAP_NAME = "overkill"


def _basename(slot, name, seg_time=1700000000, seg_id=0, match_id=MATCH_ID, map_name=MAP_NAME):
    return "%s_%s_p%d_%s_%d_%d.dm_91" % (match_id, map_name, slot, name, seg_time, seg_id)


def _write_index(demo_dir, dm91_basename, *, client_num, first, last, game_start, index_framing="with_header"):
    idx_dir = os.path.join(demo_dir, "index")
    os.makedirs(idx_dir, exist_ok=True)
    stem = dm91_basename[: -len(".dm_91")]
    idx_path = os.path.join(idx_dir, stem + ".snaps.json")
    payload = {
        "file": "demos/%s" % dm91_basename,
        "client_num": client_num,
        "first_server_time": first,
        "last_server_time": last,
        "game_start_server_time": game_start,
        "index_framing": index_framing,
        "snapshots": [{"t": first, "off": 6759, "len": 967, "delta": 0}],
    }
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return idx_path


def _make_match_fixture(tmp_path):
    """4-file match: p0/p1 share the aligned stage-2 window, p2 is an
    excluded outlier (own untrimmed stage-1 range per the design spec's
    "Why trim" section), p3 is an unindexed copy-through (no index dir
    entry at all, per Task 6b's "index refused on clock reset" behaviour).
    """
    demo_dir = tmp_path / "demos"
    demo_dir.mkdir()
    demo_dir = str(demo_dir)

    p0 = _basename(0, "alice")
    p1 = _basename(1, "bob")
    p2 = _basename(2, "carol")
    p3 = _basename(3, "dave")

    for basename in (p0, p1, p2, p3):
        with open(os.path.join(demo_dir, basename), "wb") as f:
            f.write(b"\x00" * 32)  # placeholder .dm_91 bytes

    _write_index(demo_dir, p0, client_num=0, first=201750, last=703000, game_start=212150)
    _write_index(demo_dir, p1, client_num=1, first=201750, last=703000, game_start=212150)
    _write_index(demo_dir, p2, client_num=2, first=180000, last=690000, game_start=212150)
    # p3 gets no index file — simulates a copy-through fallback.

    # A file from a DIFFERENT match_id in the same directory must not be
    # picked up by the glob.
    other = _basename(0, "eve", match_id="20260101T000000Z")
    with open(os.path.join(demo_dir, other), "wb") as f:
        f.write(b"\x00" * 32)

    return demo_dir, {p0: 0, p1: 1, p2: 2, p3: 3}


# ---------------------------------------------------------------------------
# index_path_for — must mirror demos.c's demo_index_path() exactly (index
# lives at {dir}/index/{basename minus .dm_91}.snaps.json, Task 6b's
# collision fix — NOT a bare "p{slot}.snaps.json").
# ---------------------------------------------------------------------------


def test_index_path_for_mirrors_c_convention():
    dm91 = "/srv/demos/20260817T120000Z_overkill_p0_alice_1700000000_0.dm_91"
    expected = "/srv/demos/index/20260817T120000Z_overkill_p0_alice_1700000000_0.snaps.json"
    assert index_path_for(dm91).replace("\\", "/") == expected


# ---------------------------------------------------------------------------
# discover_pov_files
# ---------------------------------------------------------------------------


def test_discover_pov_files_only_matches_this_match_id(tmp_path):
    demo_dir, by_basename = _make_match_fixture(tmp_path)
    found = discover_pov_files(demo_dir, MATCH_ID)
    found_basenames = sorted(os.path.basename(p) for p in found)
    assert found_basenames == sorted(by_basename.keys())
    # the other match's file must not appear
    assert not any("20260101T000000Z" in b for b in found_basenames)


# ---------------------------------------------------------------------------
# parse_name_from_basename — filename fallback when no live-tracked name
# ---------------------------------------------------------------------------


def test_parse_name_from_basename_extracts_slot_and_name():
    basename = _basename(3, "dave")
    slot, name = parse_name_from_basename(basename, MATCH_ID, MAP_NAME)
    assert slot == 3
    assert name == "dave"


# ---------------------------------------------------------------------------
# build_entries
# ---------------------------------------------------------------------------


def test_build_entries_reads_index_fields_and_flags_missing_index(tmp_path):
    demo_dir, _ = _make_match_fixture(tmp_path)
    entries = build_entries(demo_dir, MATCH_ID, MAP_NAME)
    by_basename = {e["basename"]: e for e in entries}

    assert len(entries) == 4
    p0 = by_basename[_basename(0, "alice")]
    assert p0["has_index"] is True
    assert p0["client_num"] == 0
    assert p0["first_server_time"] == 201750
    assert p0["last_server_time"] == 703000
    assert p0["game_start_server_time"] == 212150

    p3 = by_basename[_basename(3, "dave")]
    assert p3["has_index"] is False
    assert p3["client_num"] is None
    assert p3["index_path"] is None


def test_build_entries_prefers_tracked_name_over_filename_fallback(tmp_path):
    demo_dir, _ = _make_match_fixture(tmp_path)
    p0_path = os.path.join(demo_dir, _basename(0, "alice"))
    entries = build_entries(demo_dir, MATCH_ID, MAP_NAME, names_by_path={p0_path: "^1Alice"})
    by_basename = {e["basename"]: e for e in entries}
    assert by_basename[_basename(0, "alice")]["name"] == "^1Alice"
    # p3 has no tracked name -> falls back to the filename's own component
    assert by_basename[_basename(3, "dave")]["name"] == "dave"


# ---------------------------------------------------------------------------
# compute_window — mode of (first_server_time, last_server_time) across
# indexed files identifies the aligned cohort vs. the excluded outlier.
# ---------------------------------------------------------------------------


def test_compute_window_picks_the_majority_pair_and_excludes_outlier(tmp_path):
    demo_dir, _ = _make_match_fixture(tmp_path)
    entries = build_entries(demo_dir, MATCH_ID, MAP_NAME)
    window, group = compute_window(entries)

    assert window == {
        "start_server_time": 201750,
        "end_server_time": 703000,
        "game_start_server_time": 212150,
    }
    assert sorted(e["basename"] for e in group) == sorted([_basename(0, "alice"), _basename(1, "bob")])


def test_compute_window_with_no_indexed_entries_returns_unknown_sentinel():
    entries = [
        {"has_index": False, "first_server_time": None, "last_server_time": None,
         "game_start_server_time": None, "client_num": None, "basename": "x.dm_91"},
    ]
    window, group = compute_window(entries)
    assert window == {"start_server_time": -1, "end_server_time": -1, "game_start_server_time": -1}
    assert group == []


# ---------------------------------------------------------------------------
# build_manifest — schema + pov_index ordering + null index for copy-through
# ---------------------------------------------------------------------------


def test_build_manifest_schema_and_pov_index_ordering(tmp_path):
    demo_dir, _ = _make_match_fixture(tmp_path)
    entries = build_entries(demo_dir, MATCH_ID, MAP_NAME)
    manifest, ordered = build_manifest(MATCH_ID, MAP_NAME, entries)

    assert manifest["format"] == "ql-match"
    assert manifest["version"] == 1
    assert manifest["match_id"] == MATCH_ID
    assert manifest["map"] == MAP_NAME
    assert manifest["window"]["start_server_time"] == 201750

    demos = manifest["demos"]
    assert len(demos) == 4
    # client_num-known entries come first, ordered by client_num; the
    # unindexed copy-through (client_num unknown) sorts last.
    assert [d["client_num"] for d in demos] == [0, 1, 2, None]
    assert [d["pov_index"] for d in demos] == [0, 1, 2, 3]

    p0 = demos[0]
    assert p0["file"] == "demos/%s" % _basename(0, "alice")
    assert p0["index"] == "index/%s" % (_basename(0, "alice")[: -len(".dm_91")] + ".snaps.json")
    assert p0["name"] == "alice"

    p3 = demos[3]
    assert p3["client_num"] is None
    assert p3["index"] is None
    assert p3["name"] == "dave"

    assert ordered[0]["basename"] == _basename(0, "alice")
    assert ordered[3]["basename"] == _basename(3, "dave")


# ---------------------------------------------------------------------------
# write_qlmatch_zip / build_match_package — zip layout + per-entry
# compression type (ZIP_STORED demos, ZIP_DEFLATED json).
# ---------------------------------------------------------------------------


def test_write_qlmatch_zip_layout_and_compression(tmp_path):
    demo_dir, _ = _make_match_fixture(tmp_path)
    entries = build_entries(demo_dir, MATCH_ID, MAP_NAME)
    manifest, ordered = build_manifest(MATCH_ID, MAP_NAME, entries)

    zip_path = os.path.join(demo_dir, "%s_%s.qlmatch" % (MATCH_ID, MAP_NAME))
    write_qlmatch_zip(zip_path, manifest, ordered)

    assert os.path.isfile(zip_path)
    assert not os.path.isfile(zip_path + ".part")  # atomic rename, no leftover temp

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        for basename in (_basename(0, "alice"), _basename(1, "bob"), _basename(2, "carol"), _basename(3, "dave")):
            assert "demos/%s" % basename in names
        # only the 3 indexed POVs have an index entry — p3 has none
        assert "index/%s" % (_basename(0, "alice")[: -len(".dm_91")] + ".snaps.json") in names
        assert "index/%s" % (_basename(3, "dave")[: -len(".dm_91")] + ".snaps.json") not in names

        assert zf.getinfo("manifest.json").compress_type == zipfile.ZIP_DEFLATED
        assert zf.getinfo("demos/%s" % _basename(0, "alice")).compress_type == zipfile.ZIP_STORED
        assert zf.getinfo(
            "index/%s" % (_basename(0, "alice")[: -len(".dm_91")] + ".snaps.json")
        ).compress_type == zipfile.ZIP_DEFLATED

        loaded_manifest = json.loads(zf.read("manifest.json"))
        assert loaded_manifest == manifest


def test_build_match_package_end_to_end(tmp_path):
    demo_dir, _ = _make_match_fixture(tmp_path)
    manifest, zip_path, ordered = build_match_package(demo_dir, MATCH_ID, MAP_NAME)

    assert zip_path == os.path.join(demo_dir, "%s_%s.qlmatch" % (MATCH_ID, MAP_NAME))
    assert os.path.isfile(zip_path)
    assert len(ordered) == 4
    assert manifest["demos"][0]["client_num"] == 0

    # source .dm_91/index files are NOT deleted after zipping — spec/brief
    # say the loose files "may remain for debug".
    assert os.path.isfile(os.path.join(demo_dir, _basename(0, "alice")))
    assert os.path.isfile(os.path.join(demo_dir, "index", _basename(0, "alice")[: -len(".dm_91")] + ".snaps.json"))


def test_build_match_package_with_no_matching_files_skips_zip(tmp_path):
    demo_dir = str(tmp_path / "empty")
    os.makedirs(demo_dir)
    manifest, zip_path, ordered = build_match_package(demo_dir, "NOMATCH", MAP_NAME)
    assert zip_path is None
    assert ordered == []
    assert manifest["demos"] == []
