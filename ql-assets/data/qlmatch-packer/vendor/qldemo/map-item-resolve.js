const PICKUP_PREFIXES = ["item_", "ammo_", "weapon_"];

const CLASS_MAP = {
  ammo_bullets: "weapon_machinegun",
  ammo_shells: "weapon_shotgun",
  ammo_rockets: "weapon_rocketlauncher",
  ammo_lightning: "weapon_lightning",
  ammo_railgun: "weapon_railgun",
  ammo_cells: "weapon_plasmagun",
  item_health_mega: "item_health_mega",
  item_health_large: "item_health_large",
  item_health: "item_health",
  item_health_small: "item_health_small",
  item_armor_shard: "item_armor_shard",
  item_armor_combat: "item_armor_combat",
  item_armor_body: "item_armor_body",
  item_armor_jacket: "item_armor_yellow",
};

const tableCache = new Map();

export function normalizeMapKey(name) {
  return String(name || "")
    .trim()
    .toLowerCase()
    .replace(/^map-/, "")
    .replace(/[^a-z0-9]/g, "");
}

export function filterPickupEntities(entities) {
  return (entities || []).filter((row) =>
    PICKUP_PREFIXES.some((p) => String(row.classname || "").startsWith(p)),
  );
}

export function registerMapPickupTable(mapName, rows) {
  tableCache.set(normalizeMapKey(mapName), rows || []);
}

/** In-browser: populate via registerMapPickupTable or pass options.mapTable to demoToReplay. */
export function loadMapPickupTable(mapName) {
  return tableCache.get(normalizeMapKey(mapName)) || [];
}

export function toRestoreClassname(mapClassname) {
  const cn = String(mapClassname || "");
  if (CLASS_MAP[cn]) return CLASS_MAP[cn];
  if (cn.startsWith("item_") || cn.startsWith("weapon_")) return cn;
  return "";
}

// The pipeline ends up naming the same pickup spot up to four ways:
// hardcoded model-path names in demo-to-replay's modelPathToClassname
// (item_armor_yellow, item_powerup_quad, ammo boxes as their weapon),
// CLASS_MAP restore names above, raw BSP classnames passed through
// toRestoreClassname, and bg_itemlist canon from ps pickup events
// (item_armor_combat, item_quad, ammo_rockets). itemFamilyKey collapses all
// of them to one comparison key so a ps-event pickup can be matched against
// a registry item or another POV's pickup regardless of which convention
// named it. Position (not the name) disambiguates which physical spot it
// was, so conflating e.g. every ammo box of a weapon with that weapon is
// fine - two spots of the same family are never within match radius.
const ITEM_FAMILY_ALIASES = {
  item_armor_jacket: "item_armor_yellow",
  item_armor_combat: "item_armor_yellow",
  item_quad: "item_powerup_quad",
  item_regen: "item_powerup_regen",
  item_haste: "item_powerup_haste",
  item_invis: "item_powerup_invis",
  item_enviro: "item_powerup_battlesuit",
  item_flight: "item_powerup_flight",
  holdable_medkit: "item_holdable_medkit",
  holdable_teleporter: "item_holdable_teleporter",
  holdable_kamikaze: "item_holdable_kamikaze",
  holdable_portal: "item_holdable_portal",
  holdable_invulnerability: "item_holdable_invulnerability",
  ammo_bullets: "weapon_machinegun",
  ammo_shells: "weapon_shotgun",
  ammo_rockets: "weapon_rocketlauncher",
  ammo_lightning: "weapon_lightning",
  ammo_railgun: "weapon_railgun",
  ammo_slugs: "weapon_railgun",
  ammo_cells: "weapon_plasmagun",
  ammo_grenades: "weapon_grenadelauncher",
  ammo_bfg: "weapon_bfg",
  ammo_nails: "weapon_nailgun",
  ammo_mines: "weapon_prox_launcher",
  ammo_belt: "weapon_chaingun",
  ammo_hmg: "weapon_hmg",
};

export function itemFamilyKey(classname) {
  const cn = String(classname || "");
  return ITEM_FAMILY_ALIASES[cn] || cn;
}

/** Nearest map-spawn row within tolerance of (x, y, z), or null. */
export function resolvePickupRowAt(table, x, y, z, tolerance = 64) {
  let best = null;
  let bestD = tolerance * tolerance;
  for (const row of table || []) {
    const dx = row.x - x;
    const dy = row.y - y;
    const dz = row.z - z;
    const d = dx * dx + dy * dy + dz * dz;
    if (d < bestD) {
      bestD = d;
      best = row;
    }
  }
  return best;
}

export function resolvePickupAt(table, x, y, z, tolerance = 64) {
  const best = resolvePickupRowAt(table, x, y, z, tolerance);
  return best ? toRestoreClassname(best.classname) : "";
}
