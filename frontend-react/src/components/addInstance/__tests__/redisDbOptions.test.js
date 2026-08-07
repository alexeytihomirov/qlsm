import { describe, it, expect } from 'vitest';
import { buildRedisDbOptions, effectiveRedisDb, nextFreeRedisDb } from '../redisDbOptions';

const inst = (name, port, redis_db = null) => ({ name, port, redis_db });

describe('effectiveRedisDb', () => {
  it('prefers the stored value', () => {
    expect(effectiveRedisDb(inst('a', 27960, 6))).toBe(6);
  });

  it('falls back to the port derivation when null', () => {
    expect(effectiveRedisDb(inst('a', 27963))).toBe(4);
  });

  it('treats a stored 1 as a real value, not as missing', () => {
    expect(effectiveRedisDb(inst('a', 27967, 1))).toBe(1);
  });
});

describe('buildRedisDbOptions', () => {
  it('always lists every DB from 1 to the max on an empty host', () => {
    const options = buildRedisDbOptions({ instances: [] });
    expect(options).toEqual([
      { db: 1, inUse: false, instanceName: null },
      { db: 2, inUse: false, instanceName: null },
      { db: 3, inUse: false, instanceName: null },
      { db: 4, inUse: false, instanceName: null },
      { db: 5, inUse: false, instanceName: null },
      { db: 6, inUse: false, instanceName: null },
      { db: 7, inUse: false, instanceName: null },
      { db: 8, inUse: false, instanceName: null },
    ]);
  });

  it('marks the occupied DB when the host has a single instance', () => {
    const options = buildRedisDbOptions({ instances: [inst('Duel #1', 27960)] });
    expect(options).toHaveLength(8);
    expect(options[0]).toEqual({ db: 1, inUse: true, instanceName: 'Duel #1' });
    expect(options[1]).toEqual({ db: 2, inUse: false, instanceName: null });
  });

  it('marks every occupied DB when the host has two contiguous instances', () => {
    const options = buildRedisDbOptions({
      instances: [inst('Duel #1', 27960), inst('FFA', 27961)],
    });
    expect(options.map((o) => [o.db, o.inUse])).toEqual([
      [1, true],
      [2, true],
      [3, false],
      [4, false],
      [5, false],
      [6, false],
      [7, false],
      [8, false],
    ]);
  });

  it('marks a non-contiguous occupied DB correctly', () => {
    const options = buildRedisDbOptions({
      instances: [inst('Duel #1', 27960), inst('FFA', 27961, 3)],
    });
    expect(options.map((o) => [o.db, o.inUse])).toEqual([
      [1, true],
      [2, false],
      [3, true],
      [4, false],
      [5, false],
      [6, false],
      [7, false],
      [8, false],
    ]);
  });

  it('keeps a high occupied DB visible', () => {
    const options = buildRedisDbOptions({ instances: [inst('Duel #1', 27960, 7)] });
    expect(options.map((o) => o.db)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
    expect(options.find((o) => o.db === 7).instanceName).toBe('Duel #1');
  });

  it('never exceeds the maximum', () => {
    const instances = Array.from({ length: 8 }, (_, i) => inst(`i${i}`, 27960 + i));
    const options = buildRedisDbOptions({ instances });
    expect(options).toHaveLength(8);
    expect(options[7].db).toBe(8);
  });

  it('names the first occupant when two instances share a DB', () => {
    const options = buildRedisDbOptions({
      instances: [inst('Duel #1', 27960), inst('Duel #2', 27961, 1)],
    });
    expect(options[0]).toEqual({ db: 1, inUse: true, instanceName: 'Duel #1' });
  });

  it('tolerates a missing instances list', () => {
    const options = buildRedisDbOptions({ instances: undefined });
    expect(options).toHaveLength(8);
    expect(options[0]).toEqual({ db: 1, inUse: false, instanceName: null });
  });

  it('respects a smaller maxInstances override', () => {
    const options = buildRedisDbOptions({ instances: [], maxInstances: 3 });
    expect(options.map((o) => o.db)).toEqual([1, 2, 3]);
  });
});

describe('nextFreeRedisDb', () => {
  it('returns 1 on an empty host', () => {
    expect(nextFreeRedisDb([])).toBe(1);
  });

  it('returns 1 when instances exist but leave DB 1 free', () => {
    expect(nextFreeRedisDb([inst('Duel #1', 27960, 3)])).toBe(1);
  });

  it('skips contiguous occupied DBs', () => {
    expect(nextFreeRedisDb([inst('Duel #1', 27960), inst('FFA', 27961)])).toBe(3);
  });

  it('fills a gap before extending past it', () => {
    expect(nextFreeRedisDb([inst('Duel #1', 27960), inst('FFA', 27961, 3)])).toBe(2);
  });

  it('falls back to 1 when every DB up to the max is occupied', () => {
    const instances = Array.from({ length: 8 }, (_, i) => inst(`i${i}`, 27960 + i));
    expect(nextFreeRedisDb(instances)).toBe(1);
  });

  it('tolerates a missing instances list', () => {
    expect(nextFreeRedisDb(undefined)).toBe(1);
  });
});
