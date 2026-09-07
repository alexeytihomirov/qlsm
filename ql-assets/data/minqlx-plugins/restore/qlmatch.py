# restore/qlmatch.py — list .qlmatch packs and build a checkpoint (see
# restore/codec.py canonicalize()) from a match's replay-v2 sidecar JSON.
#
# match_restore.py cannot parse .dm_91 itself (the demo parser is
# JavaScript, in ql-stream-tools/live-overlay/lib/qldemo/) so this module
# only ever reads two things the packer (qlsm/ql-assets/data/qlmatch-packer)
# and a *separate, not-yet-built* merge module are contracted to produce:
#   - manifest.json inside each {match_id}_{map}...qlmatch (zip, STORE) —
#     read via the zip central directory only, never demos/*.dm_91 or
#     index/*.snaps.json (those stay untouched and unopened here).
#   - {match_id}_{map}.replay.json.gz next to the pack — a gzipped
#     replay-v2 JSON ({meta, events}) sidecar, produced by the packer's
#     qlmatch-to-replay.mjs (pack.mjs spawns it after every pack; see
#     docs/superpowers/specs/2026-08-29-qlmatch-unified-replay-feed-research.md
#     for the merge design). Per-player inventory is folded into each
#     "positions" player row (ammo/weapons/holdable, raw playerState shapes
#     — see _extract_inventory) and meta.generator_version tracks the merge
#     algorithm. Every inventory field is still read defensively: if the
#     merge module ships a different shape, only weapon/ammo restore
#     degrades — position/health/armor/items still work off the parts of
#     the contract implemented here (positions events, pickup events).

from __future__ import annotations

import gzip
import json
import os
import re
import zipfile

try:
    from restore.codec import AMMO_KEYS, WEAPON_ORDER, loadout_to_mask, mask_weapon_keys
    from restore.items import export_item_row
except ImportError:
    from .codec import AMMO_KEYS, WEAPON_ORDER, loadout_to_mask, mask_weapon_keys
    from .items import export_item_row

PACK_EXT = ".qlmatch"
SIDECAR_EXT = ".replay.json.gz"

_MMSS_RE = re.compile(r"^(\d+):(\d{1,2})(?:\.(\d{1,3}))?$")

WEAPON_KEY_ALIASES = {
    "gauntlet": "g", "g": "g",
    "mg": "mg", "machinegun": "mg",
    "sg": "sg", "shotgun": "sg",
    "gl": "gl", "grenadelauncher": "gl",
    "rl": "rl", "rocketlauncher": "rl",
    "lg": "lg", "lightning": "lg",
    "rg": "rg", "railgun": "rg",
    "pg": "pg", "plasmagun": "pg",
    "bfg": "bfg",
    "gh": "gh", "grapplinghook": "gh",
    "ng": "ng", "nailgun": "ng",
    "pl": "pl", "proxlauncher": "pl", "prox_launcher": "pl",
    "cg": "cg", "chaingun": "cg",
    "hmg": "hmg",
}


def parse_clock_to_ms(text):
    """Strict 'mm:ss' or 'mm:ss.mmm' -> elapsed match ms. Raises ValueError.

    Deliberately does not accept a bare number: unlike restorecp's other
    `time` subcommand (which supports raw ms elsewhere in this plugin), the
    scoreboard clock is the only reference an operator has for a qlmatch
    pack, so the command only takes that one unambiguous shape.
    """
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("time argument empty")
    m = _MMSS_RE.match(raw)
    if not m:
        raise ValueError("time must be mm:ss, got {!r}".format(raw))
    minutes = int(m.group(1))
    seconds = int(m.group(2))
    if seconds > 59:
        raise ValueError("seconds must be 00-59, got {!r}".format(raw))
    frac = m.group(3) or "0"
    ms = minutes * 60000 + seconds * 1000 + int(round(float("0." + frac) * 1000))
    return max(0, ms)


def format_clock(ms):
    """Integer match-elapsed ms -> 'm:ss' or 'm:ss.mmm' (inverse of parse_clock_to_ms)."""
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        return "?"
    ms = max(0, ms)
    minutes, rem = divmod(ms, 60000)
    seconds, millis = divmod(rem, 1000)
    if millis:
        return "{}:{:02d}.{:03d}".format(minutes, seconds, millis)
    return "{}:{:02d}".format(minutes, seconds)


def duration_ms_from_window(window):
    """Scoreboard-clock duration from a .qlmatch manifest window, or None.

    game_start_server_time is the fight clock origin (mm:ss = 0:00). Falling
    back to start_server_time covers packs that omit game_start.
    """
    if not isinstance(window, dict):
        return None
    try:
        end = int(window["end_server_time"])
    except (TypeError, ValueError, KeyError):
        return None
    start_raw = window.get("game_start_server_time")
    if start_raw is None:
        start_raw = window.get("start_server_time")
    try:
        start = int(start_raw)
    except (TypeError, ValueError):
        return None
    # Packer/index sentinels: -1 is not a valid QL serverTime (seen on
    # real packs whose window was never filled in). Treat as "unknown".
    if end < 0 or start < 0:
        return None
    if end < start:
        return None
    return end - start


def demo_duration_ms(window=None, sidecar=None):
    """Operator-facing demo length in game-clock ms.

    Prefer the pack manifest window (same value `qlmatch list` shows). Fall
    back to the last positions event so a sidecar-only restore still rejects
    times past the recorded feed.
    """
    dur = duration_ms_from_window(window)
    if dur is not None:
        return dur
    if sidecar is not None:
        return last_positions_ms(sidecar.get("events"))
    return None


def reject_if_past_duration(target_ms, duration_ms):
    if duration_ms is None:
        return
    target_ms = int(target_ms)
    duration_ms = int(duration_ms)
    if target_ms > duration_ms:
        raise ValueError(
            "requested time {} ({}ms) is past demo duration {} ({}ms)".format(
                format_clock(target_ms), target_ms,
                format_clock(duration_ms), duration_ms,
            )
        )


def sidecar_path_for(demo_dir, match_id, map_name):
    return os.path.join(demo_dir, "{}_{}{}".format(match_id, map_name, SIDECAR_EXT))


def _read_manifest_bytes(zip_path):
    """The only file operation this module ever performs against a pack's
    zip contents — deliberately isolated in its own function so tests can
    spy on it (or on zipfile.ZipFile.read) and assert no other member name
    is ever requested."""
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read("manifest.json")


def _pack_summary(zip_path, filename):
    try:
        raw = _read_manifest_bytes(zip_path)
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    match_id = str(manifest.get("match_id") or "")
    map_name = str(manifest.get("map") or "")
    players = [
        str(d.get("name") or "").strip()
        for d in (manifest.get("demos") or [])
        if isinstance(d, dict)
    ]
    window = manifest.get("window") or {}
    return {
        "path": zip_path,
        "filename": filename,
        "match_id": match_id,
        "map": map_name,
        "players": [p for p in players if p],
        "window": window,
        "duration_ms": duration_ms_from_window(window),
    }


def _duration_from_sidecar(path):
    """Last positions game_time_ms from a replay sidecar, or None.

    Only used when the pack manifest window cannot yield a duration (missing
    or sentinel -1). List still never opens demos/*.dm_91.
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        sidecar = load_sidecar(path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError, gzip.BadGzipFile, EOFError):
        return None
    return last_positions_ms(sidecar.get("events"))


def list_packs(demo_dir, filter_substr=None):
    """Numbered (1-based) list of .qlmatch packs in demo_dir, newest match_id
    first. Reads manifest.json out of each pack's zip; if the window cannot
    yield a duration, falls back to the sibling replay sidecar (not the
    .dm_91 files).
    """
    if not demo_dir or not os.path.isdir(demo_dir):
        return []
    rows = []
    for filename in sorted(os.listdir(demo_dir)):
        if not filename.endswith(PACK_EXT):
            continue
        summary = _pack_summary(os.path.join(demo_dir, filename), filename)
        if summary is None:
            continue
        if summary.get("duration_ms") is None:
            summary["duration_ms"] = _duration_from_sidecar(
                sidecar_path_for(demo_dir, summary["match_id"], summary["map"])
            )
        rows.append(summary)
    rows.sort(key=lambda r: r["match_id"], reverse=True)
    needle = str(filter_substr or "").strip().lower()
    if needle:
        def _matches(row):
            haystack = " ".join([row["map"], row["match_id"]] + row["players"]).lower()
            return needle in haystack

        rows = [r for r in rows if _matches(r)]
    for idx, row in enumerate(rows, start=1):
        row["index"] = idx
    return rows


def resolve_pack_by_index(cache, index):
    """Look up a pack in an already-produced list_packs() result — never
    rescans the directory, so a stale/out-of-range index just misses."""
    try:
        want = int(index)
    except (TypeError, ValueError):
        return None
    for row in cache or []:
        if int(row.get("index", -1)) == want:
            return row
    return None


def load_sidecar(path):
    with gzip.open(path, "rb") as handle:
        data = handle.read()
    doc = json.loads(data.decode("utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("sidecar replay must be a JSON object")
    return doc


def _event_time_ms(ev):
    t = ev.get("game_time_ms", ev.get("t"))
    if t is None:
        return None
    try:
        return int(t)
    except (TypeError, ValueError):
        return None


def last_positions_ms(events):
    last = None
    for ev in events or []:
        if not isinstance(ev, dict) or ev.get("event") != "positions":
            continue
        t = _event_time_ms(ev)
        if t is None:
            continue
        if last is None or t > last:
            last = t
    return last


def nearest_positions_event(events, target_ms):
    """Latest 'positions' event with game_time_ms <= target_ms, or (None, None)."""
    best = None
    best_t = None
    for ev in events or []:
        if not isinstance(ev, dict) or ev.get("event") != "positions":
            continue
        t = _event_time_ms(ev)
        if t is None or t > target_ms:
            continue
        if best_t is None or t > best_t:
            best_t = t
            best = ev
    return best, best_t


def _extract_inventory(row):
    """Best-effort weapons/ammo/holdable extraction from a positions player
    row. The qlmatch-packer's replay sidecar (qlmatch-to-replay.mjs) carries
    the raw playerState shapes: `weapons` is the STAT_WEAPONS bitmask where
    bit i = dm_91 weapon index i — bit-identical to codec.WEAPON_ORDER's
    loadout mask (bit idx+1: 1=g, 2=mg, ... 14=hmg) — and `ammo` is the
    ps.ammo array indexed by the same weapon indices, with -1/65535 meaning
    infinite (gauntlet). Dict/list shapes are kept for other producers. Any
    field the row doesn't carry comes back None so the caller omits it
    instead of forcing an empty/zeroed value onto the checkpoint."""
    weapons = row.get("weapons")
    loadout_keys = None
    if isinstance(weapons, bool):
        weapons = None
    if isinstance(weapons, int):
        loadout_keys = {k: 1 for k in mask_weapon_keys(weapons)}
    elif isinstance(weapons, dict):
        loadout_keys = {
            WEAPON_KEY_ALIASES.get(str(k).strip().lower(), str(k).strip().lower()): 1
            for k, v in weapons.items()
            if v
        }
    elif isinstance(weapons, (list, tuple, set)):
        loadout_keys = {
            WEAPON_KEY_ALIASES.get(str(k).strip().lower(), str(k).strip().lower()): 1
            for k in weapons
        }
    ammo = row.get("ammo")
    if isinstance(ammo, (list, tuple)):
        converted = {}
        for idx, value in enumerate(ammo):
            # ammo[0] is WP_NONE; WEAPON_ORDER[idx - 1] is the key for
            # weapon index idx ("hands" is not a real weapon slot).
            if idx < 1 or idx - 1 >= len(WEAPON_ORDER):
                continue
            key = WEAPON_ORDER[idx - 1]
            if key == "hands":
                continue
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            if value < 0 or value >= 0xFFFF:
                continue
            converted[key] = value
        ammo = converted or None
    elif not isinstance(ammo, dict):
        ammo = None
    holdable = row.get("holdable") or row.get("holdables") or None
    return loadout_keys, ammo, holdable


def _finite_xyz(p):
    if not isinstance(p, dict):
        return None
    try:
        return float(p["x"]), float(p["y"]), float(p["z"])
    except (TypeError, ValueError, KeyError):
        return None


def _attach_velocity(row, p, prev_p=None, dt_ms=None):
    """Copy sidecar vx/vy/vz, or estimate from the previous positions row.

    Own-POV rows historically serialized vx=0 always: entityVelocity()
    ignores TR_INTERPOLATE (playerStateToEntityState's type). If sidecar
    velocity is missing or all-zero while the player moved, derive it
    from the position delta so restore still gets a motion vector.
    """
    vx, vy, vz = p.get("vx"), p.get("vy"), p.get("vz")
    has = vx is not None and vy is not None and vz is not None
    prev_xyz = _finite_xyz(prev_p)
    moved = False
    if prev_xyz is not None:
        moved = (
            abs(row["x"] - prev_xyz[0])
            + abs(row["y"] - prev_xyz[1])
            + abs(row["z"] - prev_xyz[2])
        ) > 1.0
    use_delta = False
    if not has:
        use_delta = prev_xyz is not None and dt_ms
    elif (
        moved
        and dt_ms
        and float(vx) == 0.0
        and float(vy) == 0.0
        and float(vz) == 0.0
    ):
        use_delta = True
    if use_delta and prev_xyz is not None and dt_ms and dt_ms > 0:
        scale = 1000.0 / float(dt_ms)
        row["vx"] = (row["x"] - prev_xyz[0]) * scale
        row["vy"] = (row["y"] - prev_xyz[1]) * scale
        row["vz"] = (row["z"] - prev_xyz[2]) * scale
        return
    if has:
        row["vx"] = float(vx)
        row["vy"] = float(vy)
        row["vz"] = float(vz)


def build_player_rows(snapshot_event, prev_by_cn=None, dt_ms=None):
    """Loose (pre-canonicalize) players[] rows from one 'positions' event.

    Health/armor default to 100/0 when the sidecar doesn't carry them (a
    single-POV-derived replay only has real vitals for its own recording
    player — see the research spec section 5) rather than 0/0, which
    codec.canonicalize would otherwise read as a dead/near-dead player.
    """
    rows = []
    prev_by_cn = prev_by_cn or {}
    for p in (snapshot_event or {}).get("players") or []:
        if not isinstance(p, dict):
            continue
        try:
            cn = int(p.get("clientNum"))
            x = float(p["x"])
            y = float(p["y"])
            z = float(p["z"])
        except (TypeError, ValueError, KeyError):
            continue
        health = p.get("health")
        armor = p.get("armor")
        row = {
            "cid": cn,
            "x": x,
            "y": y,
            "z": z,
            "h": int(health) if health is not None else 100,
            "a": int(armor) if armor is not None else 0,
        }
        sid = p.get("steam_id64") or p.get("st")
        if sid:
            row["sid"] = str(sid).strip()
        if health is not None:
            try:
                if int(health) <= 0:
                    row["dead"] = 1
            except (TypeError, ValueError):
                pass
        weapon = p.get("weapon")
        if weapon is not None:
            try:
                w = int(weapon)
            except (TypeError, ValueError):
                w = 0
            if w > 0:
                row["w"] = w
        _attach_velocity(row, p, prev_by_cn.get(cn), dt_ms)
        loadout_keys, ammo, _holdable = _extract_inventory(p)
        if loadout_keys is not None:
            row["lo"] = loadout_to_mask(loadout_keys)
        if ammo:
            filtered = {k: int(v) for k, v in ammo.items() if k in AMMO_KEYS}
            if filtered:
                row["am"] = filtered
        rows.append(row)
    return rows


def pickup_state_at(events, target_ms):
    """{(item, round(x), round(y), round(z)): {pickup_ms, respawn_sec}} for
    spots still hidden/respawning at target_ms — the last pickup with no
    later respawn observed by target_ms. Mirrors the pairing logic in
    ql-stream-tools/live-overlay/lib/qldemo/replay-for-overlay.js's
    itemStateRows(), collapsed to a single point in time instead of full
    intervals for the whole match.
    """
    by_key = {}
    for ev in events or []:
        if not isinstance(ev, dict) or ev.get("event") != "pickup":
            continue
        t = _event_time_ms(ev)
        if t is None or t > target_ms:
            continue
        item = str(ev.get("item") or "")
        if not item:
            continue
        try:
            x = round(float(ev.get("x", 0)))
            y = round(float(ev.get("y", 0)))
            z = round(float(ev.get("z", 0)))
        except (TypeError, ValueError):
            continue
        key = (item, x, y, z)
        action = str(ev.get("action") or "pickup")
        if action == "pickup":
            respawn_sec = ev.get("respawn_sec")
            try:
                respawn_sec = float(respawn_sec) if respawn_sec is not None else None
            except (TypeError, ValueError):
                respawn_sec = None
            by_key[key] = {"pickup_ms": t, "respawn_sec": respawn_sec}
        elif action == "respawn":
            by_key.pop(key, None)
    return by_key


def build_item_rows(pickup_state, map_spawns_table, target_ms, map_key, wall_now):
    """items[] rows (pre-canonicalize) for every map spawn not in its
    default/available state at target_ms — addressed by classname+position
    (find_map_item_entity in match_restore.py), same as the existing
    checkpoint mechanism, not by a raw demo entity_id (the demo has none)."""
    rows = []
    for alias, meta in (map_spawns_table or {}).items():
        if not isinstance(meta, dict):
            continue
        classname = str(meta.get("classname") or "")
        if not classname:
            continue
        try:
            key = (
                classname,
                round(float(meta.get("x", 0))),
                round(float(meta.get("y", 0))),
                round(float(meta.get("z", 0))),
            )
        except (TypeError, ValueError):
            continue
        bundled = pickup_state.get(key)
        row = export_item_row(
            alias, meta, target_ms, wall_now=wall_now, bundled_pickup=bundled, map_key=map_key
        )
        if int(row.get("s", 1)) == 1:
            continue
        try:
            row["eid"] = int(meta.get("entity_id"))
        except (TypeError, ValueError):
            pass
        rows.append(row)
    return rows


def pause_warning(sidecar_meta):
    """No sidecar today defines a pause-window field (see module docstring);
    this checks the shapes the match-to-replay ticket is most likely to use
    so a future producer's warning "just works", and stays silent (rather
    than guessing) when neither is present — the mm:ss/game_start+ms
    mismatch during a paused match is otherwise undetectable from here."""
    meta = sidecar_meta or {}
    windows = meta.get("pause_windows") or meta.get("pauses")
    if not windows:
        return None
    return (
        "^3warning^7: this match had {} pause(s) — serverTime keeps advancing "
        "during a QL pause while the scoreboard clock does not, so mm:ss may "
        "no longer line up with this replay's game_start+ms axis after a "
        "pause. Restored position/hp/items are still from the requested "
        "snapshot; only the mm:ss you asked for may be off.".format(len(windows))
    )


def build_checkpoint_doc(sidecar, target_ms, map_spawns_table, map_key, wall_now, window=None):
    """Return (doc, warning, snapshot_t_ms) for restore.codec.canonicalize().

    Raises ValueError if target_ms is past the demo duration, or if the
    sidecar has no snapshot at or before target_ms.
    """
    reject_if_past_duration(target_ms, demo_duration_ms(window=window, sidecar=sidecar))
    events = sidecar.get("events") or []
    snapshot, snap_t = nearest_positions_event(events, target_ms)
    if snapshot is None:
        raise ValueError(
            "no snapshot at or before {}ms in this replay (match may start later, "
            "or the sidecar has no positions events)".format(target_ms)
        )
    prev_event, prev_t = (
        nearest_positions_event(events, snap_t - 1) if snap_t is not None else (None, None)
    )
    dt_ms = (snap_t - prev_t) if (snap_t is not None and prev_t is not None) else None
    prev_by_cn = {}
    for p in (prev_event or {}).get("players") or []:
        if not isinstance(p, dict):
            continue
        try:
            prev_by_cn[int(p.get("clientNum"))] = p
        except (TypeError, ValueError):
            continue
    players = build_player_rows(snapshot, prev_by_cn=prev_by_cn, dt_ms=dt_ms)
    pickup_state = pickup_state_at(events, target_ms)
    items = build_item_rows(pickup_state, map_spawns_table, target_ms, map_key, wall_now)
    doc = {
        "t_ms": target_ms,
        "map": map_key,
        "players": players,
        "items": items,
    }
    warning = pause_warning(sidecar.get("meta"))
    return doc, warning, snap_t
