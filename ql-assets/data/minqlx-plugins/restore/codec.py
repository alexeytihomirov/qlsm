# restore/codec.py — checkpoint helpers for draft/cfg restore.
# No binary blob / paste / fetch transport.

import re
import zlib

CHECKPOINT_VERSION = 2

AMMO_KEYS = ("rl", "lg", "rg", "pg", "gl", "sg", "mg", "cg")

# Player-held powerup remaining time (seconds). Keys are cfg aliases.
POWERUP_KEYS = ("quad", "regen", "bs", "haste", "invis", "invuln")
POWERUP_ALIAS = {
    "quad": "quad",
    "regen": "regen",
    "regeneration": "regen",
    "bs": "bs",
    "battlesuit": "bs",
    "battle": "bs",
    "enviro": "bs",
    "haste": "haste",
    "invis": "invis",
    "invisibility": "invis",
    "invuln": "invuln",
    "invulnerability": "invuln",
}
# minqlxtended Player.powerups property field names (v1.0.0: read/write property, not a method)
POWERUP_MINQLX = {
    "quad": "quad",
    "regen": "regeneration",
    "bs": "battlesuit",
    "haste": "haste",
    "invis": "invisibility",
    "invuln": "invulnerability",
}

WEAPON_ORDER = (
    "g", "mg", "sg", "gl", "rl", "lg", "rg", "pg",
    "bfg", "gh", "ng", "pl", "cg", "hmg", "hands",
)

COORD_DECIMALS = 1


def normalize_map_key(name):
    text = str(name or "").strip().lower()
    if text.startswith("map-"):
        text = text[4:]
    return re.sub(r"[^a-z0-9]", "", text)


def map_crc32(map_key):
    key = normalize_map_key(map_key)
    if not key:
        return 0
    return zlib.crc32(key.encode("utf-8")) & 0xFFFFFFFF


def loadout_to_mask(loadout):
    if loadout is None:
        return 0
    if isinstance(loadout, int):
        return int(loadout) & 0xFFFF
    if not isinstance(loadout, dict):
        return 0
    mask = 0
    for idx, key in enumerate(WEAPON_ORDER):
        if loadout.get(key):
            mask |= 1 << (idx + 1)
    return mask & 0xFFFF


def mask_to_loadout(mask):
    out = {}
    m = int(mask) & 0xFFFF
    for idx, key in enumerate(WEAPON_ORDER):
        if m & (1 << (idx + 1)):
            out[key] = 1
    return out


def weapon_key_bit(key):
    """Loadout bit for weapon key (g/mg/…); None if unknown."""
    key = str(key or "").strip().lower()
    if key not in WEAPON_ORDER or key == "hands":
        return None
    return 1 << (WEAPON_ORDER.index(key) + 1)


def mask_weapon_keys(mask):
    """Owned weapon keys from loadout mask (excludes hands)."""
    out = []
    m = int(mask or 0) & 0xFFFF
    for idx, key in enumerate(WEAPON_ORDER):
        if key == "hands":
            continue
        if m & (1 << (idx + 1)):
            out.append(key)
    return out


def normalize_powerups(raw):
    """Return {alias: remaining_seconds} for known powerups; drop zeros.

    `pw` values are always whole seconds, never milliseconds -- match_restore.py's
    `_export_powerups` converts `Player.powerups` (ms) down to seconds before this
    ever sees it, and `_apply_powerups` converts back up (`sec * 1000`) on apply.
    """
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, val in raw.items():
        alias = POWERUP_ALIAS.get(str(key).strip().lower())
        if not alias:
            continue
        try:
            sec = int(val)
        except (TypeError, ValueError):
            continue
        if sec > 0:
            out[alias] = sec
    return out


def repair_telemetry_loadout_mask(mask):
    """Shift old 1<<idx masks (bit0 set) to 1<<(idx+1)."""
    m = int(mask) & 0xFFFF
    if m & 1:
        return (m << 1) & 0xFFFF
    return m


def ensure_active_weapon_in_loadout(lo, weapon_w):
    if weapon_w is None:
        return int(lo) & 0xFFFF
    try:
        w = int(weapon_w)
    except (TypeError, ValueError):
        return int(lo) & 0xFFFF
    if 1 <= w <= 14:
        return (int(lo) | (1 << w)) & 0xFFFF
    return int(lo) & 0xFFFF


def normalize_loadout_mask(lo, weapon_w=None):
    m = repair_telemetry_loadout_mask(int(lo or 0))
    return ensure_active_weapon_in_loadout(m, weapon_w)


def _coord_val(value):
    return round(float(value), COORD_DECIMALS)


def _item_row_eid(row):
    if row.get("eid") is not None:
        try:
            return int(row["eid"])
        except (TypeError, ValueError):
            pass
    key = str(row.get("k", row.get("key", row.get("alias", "")))).strip().lower()
    if key.startswith("e") and key[1:].isdigit():
        return int(key[1:])
    return None


def canonicalize(doc):
    if not isinstance(doc, dict):
        raise ValueError("checkpoint must be object")
    ver = int(doc.get("v", doc.get("version", CHECKPOINT_VERSION)) or CHECKPOINT_VERSION)
    if ver != CHECKPOINT_VERSION:
        raise ValueError("unsupported checkpoint version: {} (need {})".format(ver, CHECKPOINT_VERSION))
    out = {
        "v": CHECKPOINT_VERSION,
        "t_ms": int(doc.get("t_ms", doc.get("game_time_ms", 0)) or 0),
        "map": normalize_map_key(doc.get("map", doc.get("map_name", ""))),
        "players": [],
        "items": [],
    }
    for row in doc.get("players") or []:
        if not isinstance(row, dict):
            continue
        p = {
            "cid": int(row.get("cid", row.get("client_id", 0))),
            "x": _coord_val(row["x"]),
            "y": _coord_val(row["y"]),
            "z": _coord_val(row["z"]),
            "h": int(row.get("h", row.get("health", 0)) or 0),
            "a": int(row.get("a", row.get("armor", 0)) or 0),
            "w": int(row.get("w", row.get("weapon", 0)) or 0),
            "lo": loadout_to_mask(row.get("lo", row.get("loadout"))),
        }
        sid = row.get("sid", row.get("steam_id64"))
        if sid:
            p["sid"] = str(sid).strip()
        for axis in ("vx", "vy", "vz"):
            if row.get(axis) is not None:
                p[axis] = int(round(float(row[axis])))
        am = row.get("am", row.get("ammo"))
        if isinstance(am, dict) and am:
            p["am"] = {k: int(am[k]) for k in AMMO_KEYS if k in am}
        sc = row.get("sc", row.get("score"))
        if sc is not None:
            p["sc"] = int(sc)
        pw = normalize_powerups(row.get("pw", row.get("powerups")))
        if pw:
            p["pw"] = pw
        if row.get("dead") in (1, True, "1") or row.get("alive") is False:
            p["dead"] = 1
        if row.get("bot"):
            p["bot"] = 1
        out["players"].append(p)
    for row in doc.get("items") or []:
        if not isinstance(row, dict):
            continue
        state = int(row.get("s", row.get("state", 1)) or 0)
        if state == 1:
            continue
        eid = _item_row_eid(row)
        item = {"s": state}
        if eid is not None:
            item["eid"] = int(eid)
        key = str(row.get("k", row.get("key", row.get("alias", "")))).strip().lower()
        if key:
            item["k"] = key
        cn = str(row.get("cn") or "").strip()
        has_pos = all(row.get(axis) is not None for axis in ("x", "y", "z"))
        if not item.get("eid") and not item.get("k"):
            if not (
                cn
                and (cn.startswith("item_") or cn.startswith("weapon_"))
                and has_pos
            ):
                continue
        if item["s"] == 2 and row.get("in") is not None:
            item["in"] = float(row["in"])
        if item["s"] == 2 and row.get("at_ms") is not None:
            try:
                item["at_ms"] = int(row["at_ms"])
            except (TypeError, ValueError):
                pass
        if cn:
            item["cn"] = cn
        for axis in ("x", "y", "z"):
            if row.get(axis) is not None:
                try:
                    item[axis] = round(float(row[axis]), 1)
                except (TypeError, ValueError):
                    pass
        out["items"].append(item)
    return out