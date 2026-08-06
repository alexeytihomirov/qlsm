/**
 * Redis DB option list for the Add Instance modal.
 *
 * Mirrors ui/constants.py: DB 0 is reserved for QLSM's own state, so instances
 * start at DB 1, and an instance with no stored redis_db keeps the historical
 * port-derived value.
 */

export const REDIS_DB_PORT_OFFSET = 27959;
export const MAX_REDIS_DB = 8;

/** The DB an instance actually uses, stored or derived. */
export function effectiveRedisDb(instance) {
  if (instance.redis_db !== null && instance.redis_db !== undefined) {
    return instance.redis_db;
  }
  return instance.port - REDIS_DB_PORT_OFFSET;
}

/**
 * Build the dropdown's options.
 *
 * The list stays as short as the host plausibly needs rather than always
 * showing all 8. Three terms set the upper bound:
 *   - instances.length + 1 : one slot per existing instance, plus the new one
 *   - highest occupied DB  : keeps an occupied DB visible above the baseline
 *   - selectedDb           : guarantees the current value is in its own list
 */
export function buildRedisDbOptions({ instances, selectedDb, maxInstances = MAX_REDIS_DB }) {
  const list = instances || [];

  const occupants = new Map();
  for (const instance of list) {
    const db = effectiveRedisDb(instance);
    if (!occupants.has(db)) {
      occupants.set(db, instance.name);
    }
  }

  const highestOccupied = occupants.size ? Math.max(...occupants.keys()) : 0;
  const upper = Math.min(
    maxInstances,
    Math.max(list.length + 1, highestOccupied, selectedDb || 1)
  );

  return Array.from({ length: upper }, (_, index) => {
    const db = index + 1;
    return {
      db,
      inUse: occupants.has(db),
      instanceName: occupants.get(db) ?? null,
    };
  });
}
