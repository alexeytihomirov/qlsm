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

export function resolvePickupAt(table, x, y, z, tolerance = 64) {
  if (!table.length) return "";
  let best = null;
  let bestD = tolerance * tolerance;
  for (const row of table) {
    const dx = row.x - x;
    const dy = row.y - y;
    const dz = row.z - z;
    const d = dx * dx + dy * dy + dz * dz;
    if (d < bestD) {
      bestD = d;
      best = row;
    }
  }
  return best ? toRestoreClassname(best.classname) : "";
}
