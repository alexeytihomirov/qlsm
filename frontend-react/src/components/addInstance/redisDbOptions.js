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
 * Always lists every DB from 1 to maxInstances, so the choice of port never
 * changes which values are offered -- picking Redis DB and picking a port
 * are independent decisions.
 */
export function buildRedisDbOptions({ instances, maxInstances = MAX_REDIS_DB }) {
  const list = instances || [];

  const occupants = new Map();
  for (const instance of list) {
    const db = effectiveRedisDb(instance);
    if (!occupants.has(db)) {
      occupants.set(db, instance.name);
    }
  }

  return Array.from({ length: maxInstances }, (_, index) => {
    const db = index + 1;
    return {
      db,
      inUse: occupants.has(db),
      instanceName: occupants.get(db) ?? null,
    };
  });
}

/**
 * The lowest unoccupied DB for a host, used as the initial default when the
 * Add Instance form first opens against that host. Once shown, the value is
 * just a normal independent selection -- nothing re-derives it afterward, so
 * picking an already-used DB on purpose (e.g. to share state) sticks.
 */
export function nextFreeRedisDb(instances, maxInstances = MAX_REDIS_DB) {
  const options = buildRedisDbOptions({ instances, maxInstances });
  const free = options.find((option) => !option.inUse);
  return free ? free.db : 1;
}
