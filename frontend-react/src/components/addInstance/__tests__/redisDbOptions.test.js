import { describe, it, expect } from 'vitest';
import { buildRedisDbOptions, effectiveRedisDb } from '../redisDbOptions';

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
  it('offers only DB 1 on an empty host', () => {
    const options = buildRedisDbOptions({ instances: [], selectedDb: 1 });
    expect(options).toEqual([{ db: 1, inUse: false, instanceName: null }]);
  });

  it('offers the occupied DB plus one when the host has a single instance', () => {
    const options = buildRedisDbOptions({
      instances: [inst('Duel #1', 27960)],
      selectedDb: 2,
    });
    expect(options).toEqual([
      { db: 1, inUse: true, instanceName: 'Duel #1' },
      { db: 2, inUse: false, instanceName: null },
    ]);
  });

  it('marks every occupied DB when the host has two contiguous instances', () => {
    const options = buildRedisDbOptions({
      instances: [inst('Duel #1', 27960), inst('FFA', 27961)],
      selectedDb: 3,
    });
    expect(options.map((o) => [o.db, o.inUse])).toEqual([
      [1, true],
      [2, true],
      [3, false],
    ]);
  });

  it('keeps a gap selectable when occupancy is not contiguous', () => {
    const options = buildRedisDbOptions({
      instances: [inst('Duel #1', 27960), inst('FFA', 27961, 3)],
      selectedDb: 3,
    });
    expect(options.map((o) => [o.db, o.inUse])).toEqual([
      [1, true],
      [2, false],
      [3, true],
    ]);
  });

  it('extends the range so the selected DB is always present', () => {
    const options = buildRedisDbOptions({
      instances: [inst('Duel #1', 27960)],
      selectedDb: 6,
    });
    expect(options.map((o) => o.db)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(options.find((o) => o.db === 6).inUse).toBe(false);
  });

  it('keeps an occupied DB visible even when it sits above the baseline', () => {
    const options = buildRedisDbOptions({
      instances: [inst('Duel #1', 27960, 7)],
      selectedDb: 1,
    });
    expect(options.map((o) => o.db)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(options.find((o) => o.db === 7).instanceName).toBe('Duel #1');
  });

  it('never exceeds the maximum', () => {
    const instances = Array.from({ length: 8 }, (_, i) => inst(`i${i}`, 27960 + i));
    const options = buildRedisDbOptions({ instances, selectedDb: 8 });
    expect(options).toHaveLength(8);
    expect(options[7].db).toBe(8);
  });

  it('names the first occupant when two instances share a DB', () => {
    const options = buildRedisDbOptions({
      instances: [inst('Duel #1', 27960), inst('Duel #2', 27961, 1)],
      selectedDb: 2,
    });
    expect(options[0]).toEqual({ db: 1, inUse: true, instanceName: 'Duel #1' });
  });

  it('tolerates a missing instances list', () => {
    expect(buildRedisDbOptions({ instances: undefined, selectedDb: 1 })).toEqual([
      { db: 1, inUse: false, instanceName: null },
    ]);
  });
});
