# demo_native_manifest.py — pure manifest/window/zip-building helpers for
# the native multi-POV demo capture pack (Task 7 of the plan; see
# ql-server-core/docs/superpowers/specs/
# 2026-08-17-native-multi-pov-demo-capture-design.md, "Final artifact"
# section for the manifest.json schema this module builds).
#
# Deliberately has NO minqlx import so it can be unit-tested without a live
# QLDS/minqlx process (see tests/test_demo_native_manifest.py) — same split
# addons/telemetry/minqlx/telemetry_unified_sched.py already established for
# this codebase's other pure per-plugin helpers. demo_native_autorecord.py
# (the actual minqlx plugin) imports this module and keeps its own event
# handlers thin: parse hook arguments, call into here.
#
# What this module does NOT do: it does not talk to minqlxtended (no
# demo_arm/demo_disarm calls), does not read cvars, and does not know about
# minqlx.Plugin at all. Its only inputs are a directory on disk (already
# finalised .dm_91 files + their index/*.snaps.json siblings, both written
# by the C side per Task 6a/6b) and plain strings/dicts the plugin passes in.
#
# Naming/layout this module assumes (confirmed against the real C code, not
# guessed — see demo_match.c:demo_build_pov_name and
# demo_match.c:demo_seg_build_final / demo_index_path. The minqlxtended v1.0.0
# port folded demo_slot.c away entirely and left upstream's demos.c untouched,
# so everything this module mirrors now lives in demo_match.c):
#   - Each finalised POV file's basename is
#     "{match_id}_{map}_p{slot}_{sanitised_name}_{seg_time}_{seg_id}.dm_91"
#     and always starts with "{match_id}_" — so a match's files are found by
#     globbing "{match_id}_*.dm_91" in the demo output directory, NOT by
#     tracking demo_recording_started state (a slot can produce more than
#     one segment/file per match; the glob is the source of truth for which
#     files exist, per the controller's explicit guidance for this task).
#   - Each file's paired snapshot index (if any — an unindexed copy-through
#     has none, see demo_match.c:demo_write_index) lives at
#     "{same dir}/index/{basename minus '.dm_91'}.snaps.json" — this is
#     Task 6b's post-review collision fix (index name derived from the full,
#     per-segment-unique final_path basename), NOT the spec's original,
#     now-stale "index/p{slot}.snaps.json" literal wording.

from __future__ import annotations

import glob
import json
import os
import zipfile
from collections import Counter

DM91_SUFFIX = ".dm_91"
INDEX_DIRNAME = "index"
ZIP_DEMOS_DIR = "demos"
ZIP_INDEX_DIR = "index"


def index_path_for(dm91_path):
    """Mirror demo_match.c's demo_index_path(): "{dir}/index/{basename minus
    '.dm_91'}.snaps.json". Kept as its own function so the convention lives
    in exactly one place and the test suite can pin it directly against the
    real C behaviour.
    """
    d = os.path.dirname(dm91_path)
    base = os.path.basename(dm91_path)
    stem = base[: -len(DM91_SUFFIX)] if base.endswith(DM91_SUFFIX) else base
    return os.path.join(d, INDEX_DIRNAME, stem + ".snaps.json")


def discover_pov_files(demo_dir, match_id):
    """Glob demo_dir for "{match_id}_*.dm_91", sorted for determinism.

    This is deliberately NOT driven by any live-tracked per-slot state: a
    slot can legitimately produce more than one segment/file in one match
    (re-gamestate, slot takeover, ring-full recovery — see demo_match.c's own
    comment at demo_seg_build_final()), so per-slot tracking during the match
    would undercount. The filesystem, at demo_match_finalized time (when
    every file for this match_id has reached final form), is the only
    complete and authoritative listing.
    """
    pattern = os.path.join(demo_dir, "%s_*%s" % (match_id, DM91_SUFFIX))
    return sorted(glob.glob(pattern))


def parse_name_from_basename(basename, match_id, map_name):
    """Best-effort fallback: recover (slot, name) from the C-owned filename
    convention "{match_id}_{map}_p{slot}_{name}_{seg_time}_{seg_id}.dm_91"
    (demo_match.c:demo_build_pov_name + demo_match.c:demo_seg_build_final's
    segment suffix).

    This is a FALLBACK, not the primary name source. The primary source is
    the plugin's own names_by_path dict, populated from
    demo_recording_started(slot, path, name)'s own `name` argument — that
    carries the player's raw, unsanitised name (color codes and all), while
    this filename component is demo_sanitise()'d (stripped to
    [A-Za-z0-9_-], spaces -> '_') and therefore lossy. This fallback exists
    for the case where a file appears in the glob without a corresponding
    tracked event (e.g. a plugin reload mid-match) and is also what makes
    this module fully self-contained/testable without any live event
    tracking at all.

    Splitting on "_" is ambiguous in the fully general case (a sanitised
    name or map can itself contain "_pN_"-shaped substrings); this trades
    that narrow edge case for simplicity, matching the brief's explicit
    "your call, note which you used and why" latitude.
    """
    stem = basename[: -len(DM91_SUFFIX)] if basename.endswith(DM91_SUFFIX) else basename
    prefix = "%s_%s_" % (match_id, map_name)
    if not stem.startswith(prefix):
        return None, ""
    rest = stem[len(prefix):]
    parts = rest.split("_")
    if not parts or not (parts[0].startswith("p") and parts[0][1:].isdigit()):
        return None, ""
    slot = int(parts[0][1:])
    middle = parts[1:]
    # Trailing seg_time/seg_id are always both purely-numeric tokens.
    if len(middle) >= 2 and middle[-1].isdigit() and middle[-2].isdigit():
        middle = middle[:-2]
    name = "_".join(middle)
    return slot, name


def _load_index(dm91_path):
    """Returns (data_dict_or_None, index_path). None means "no index" —
    either the file genuinely doesn't exist (unindexed copy-through, per
    demo_match.c:demo_write_index refusing clock-reset/multi-gamestate files) or
    it exists but failed to parse (treated the same way: no index).
    """
    idx_path = index_path_for(dm91_path)
    if not os.path.isfile(idx_path):
        return None, idx_path
    try:
        with open(idx_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None, idx_path
    return data, idx_path


def build_entries(demo_dir, match_id, map_name, names_by_path=None):
    """Build one entry dict per discovered POV file. Pure filesystem read —
    no mutation, no zip, no network.
    """
    names_by_path = names_by_path or {}
    entries = []
    for dm91_path in discover_pov_files(demo_dir, match_id):
        basename = os.path.basename(dm91_path)
        idx_data, idx_path = _load_index(dm91_path)
        has_index = idx_data is not None

        name = names_by_path.get(dm91_path)
        if name is None:
            _, name = parse_name_from_basename(basename, match_id, map_name)

        entries.append({
            "path": dm91_path,
            "basename": basename,
            "index_path": idx_path if has_index else None,
            "index_basename": os.path.basename(idx_path) if has_index else None,
            "has_index": has_index,
            "client_num": idx_data.get("client_num") if has_index else None,
            "first_server_time": idx_data.get("first_server_time") if has_index else None,
            "last_server_time": idx_data.get("last_server_time") if has_index else None,
            "game_start_server_time": idx_data.get("game_start_server_time") if has_index else None,
            "name": name,
        })
    return entries


def compute_window(entries):
    """The pack's shared window is the MODE (most common)
    (first_server_time, last_server_time) pair across the match's INDEXED
    files. Per Task 6a's two-stage cut design, every POV that shares the
    stage-2 aligned window ends up with byte-identical first/last
    server_time; a POV whose own capture range didn't cover the computed
    shared window is published un-cut (stage-1 only) with its own,
    necessarily-different range instead of being force-cut. So the majority
    pair IS the aligned cohort, and anything else is exactly the excluded
    outlier — no new C-side signal is needed to tell them apart.

    Ties are broken deterministically by first-encountered order (stable
    given `entries`' own order, which callers get from the sorted glob).

    Returns (window_dict, group) where `group` is the list of entries that
    belong to the winning pair (useful for callers/tests that want to see
    which files were actually "in" the aligned cohort).
    """
    counts = Counter()
    order = []
    for e in entries:
        if not e["has_index"]:
            continue
        key = (e["first_server_time"], e["last_server_time"])
        if key not in counts:
            order.append(key)
        counts[key] += 1

    if not counts:
        return {"start_server_time": -1, "end_server_time": -1, "game_start_server_time": -1}, []

    best = max(counts.values())
    mode_key = next(k for k in order if counts[k] == best)
    group = [
        e for e in entries
        if e["has_index"] and (e["first_server_time"], e["last_server_time"]) == mode_key
    ]

    # game_start_server_time is per-file (read off the RAW capture's own
    # "cs 5 -> \time\0" command, per Task 6b), but for a healthy match it is
    # the same real server-clock instant in every POV, so it should already
    # agree within the winning group. -1 ("unknown", Task 6b's documented
    # value for an already-in-progress/pure-warmup file) is excluded from
    # the vote when any real value is present, so one straggling -1 doesn't
    # win by default.
    gst_counts = Counter(
        e["game_start_server_time"] for e in group
        if e["game_start_server_time"] not in (None, -1)
    )
    game_start = gst_counts.most_common(1)[0][0] if gst_counts else -1

    window = {
        "start_server_time": mode_key[0],
        "end_server_time": mode_key[1],
        "game_start_server_time": game_start,
    }
    return window, group


def _pov_sort_key(entry):
    """Deterministic, stable pov_index ordering: known client_num first
    (ascending — this naturally reads as "POV per player, in slot order",
    even though pov_index is explicitly NOT defined to equal client_num/slot
    per the brief's own "not necessarily the slot number" guidance — two
    segments of the same slot both carry the same client_num and are
    tie-broken by first_server_time, then basename). Unindexed
    copy-through entries (client_num unknown) sort after every indexed
    entry, ordered by basename.
    """
    has_cn = entry["client_num"] is not None
    cn = entry["client_num"] if has_cn else 0
    fst = entry["first_server_time"] if entry["first_server_time"] is not None else 2 ** 31
    return (0 if has_cn else 1, cn, fst, entry["basename"])


def build_manifest(match_id, map_name, entries):
    """Build the manifest.json dict per the spec's "Final artifact" schema.

    pov_index: a stable per-file ordinal (0-based position in the sorted
    `demos` array below), NOT the slot/client_num — the spec's own example
    only ever shows one entry so this can't be pinned from the schema text
    alone, but the brief's guidance ("likely a stable per-file ordinal, not
    necessarily the slot number, since one slot can yield 2 files") is
    exactly this: multiple segments of one slot get distinct, consecutive
    pov_index values rather than colliding.

    A POV with no index (unindexed copy-through) is still included in
    `demos` (its .dm_91 is still real, playable output) with
    `client_num: null` and `index: null` — the spec's schema doesn't cover
    this case explicitly (it fixes `index` as a required string), so `null`
    is this module's extension, documented here rather than invented
    silently. `name` still comes through (tracked event name or filename
    fallback) since we have it regardless of indexing.
    """
    window, _group = compute_window(entries)
    ordered = sorted(entries, key=_pov_sort_key)

    demos = []
    for i, e in enumerate(ordered):
        demos.append({
            "file": "%s/%s" % (ZIP_DEMOS_DIR, e["basename"]),
            "pov_index": i,
            "client_num": e["client_num"],
            "name": e["name"],
            "index": ("%s/%s" % (ZIP_INDEX_DIR, e["index_basename"])) if e["has_index"] else None,
        })

    manifest = {
        "format": "ql-match",
        "version": 1,
        "match_id": match_id,
        "map": map_name,
        "window": window,
        "demos": demos,
    }
    return manifest, ordered


def write_qlmatch_zip(zip_path, manifest, ordered_entries):
    """Write the .qlmatch zip. Compression: ZIP_STORED for the .dm_91
    payloads (already dense binary; the spec's original wording favoured
    STORED so cutting CPU on data that doesn't compress), ZIP_DEFLATED for
    manifest.json and the index JSON files (Task 6b measured a real
    20k-snapshot index compressing to ~14% of its raw size — storing that
    uncompressed wastes real space for no reason the spec's pre-Task-6b
    wording could have anticipated). Python's zipfile supports per-entry
    compression type in the same archive; standard readers, including
    Python's own zipfile, handle this transparently.

    Written via "{zip_path}.part" + os.replace(), the same atomic
    publish-by-rename convention demo_match.c's own demo_publish() uses for the
    .dm_91 files themselves, so a reader never observes a half-written zip.
    """
    tmp_path = zip_path + ".part"
    with zipfile.ZipFile(tmp_path, "w") as zf:
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        zf.writestr("manifest.json", manifest_bytes, compress_type=zipfile.ZIP_DEFLATED)
        for e in ordered_entries:
            zf.write(e["path"], "%s/%s" % (ZIP_DEMOS_DIR, e["basename"]), compress_type=zipfile.ZIP_STORED)
            if e["has_index"]:
                zf.write(
                    e["index_path"],
                    "%s/%s" % (ZIP_INDEX_DIR, e["index_basename"]),
                    compress_type=zipfile.ZIP_DEFLATED,
                )
    os.replace(tmp_path, zip_path)
    return zip_path


def build_match_package(demo_dir, match_id, map_name, names_by_path=None):
    """Top-level orchestration: discover -> build entries -> compute window
    -> build manifest -> write zip. This is what
    demo_native_autorecord.py's on_demo_match_finalized handler calls, on a
    worker thread (see @minqlx.thread in the plugin — this function itself
    does blocking file I/O and must never run on the game thread).

    Returns (manifest, zip_path, ordered_entries). zip_path is None (no zip
    written) when no files matched match_id — nothing to package, and
    writing an empty/pointless zip would be misleading. Source .dm_91/index
    files are never deleted here — per the spec/brief, the loose files "may
    remain for debug"; the .qlmatch is the product hub/editor consume.
    """
    entries = build_entries(demo_dir, match_id, map_name, names_by_path)
    manifest, ordered = build_manifest(match_id, map_name, entries)
    if not entries:
        return manifest, None, ordered
    zip_path = os.path.join(demo_dir, "%s_%s.qlmatch" % (match_id, map_name))
    write_qlmatch_zip(zip_path, manifest, ordered)
    return manifest, zip_path, ordered
