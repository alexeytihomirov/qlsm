import { describe, it, expect } from 'vitest';
import { parseAdminEntries, upsertAdminLine, removeAdminLine } from './operatorConfigSync';

describe('upsertAdminLine', () => {
  it('adds the first admin to an empty access.txt', () => {
    // Regression: lines[lines.length - 1] = line assigns a "-1" property on
    // an empty array instead of growing it, so the result used to silently
    // stay ''.
    const result = upsertAdminLine('', '76561198012345678', 3);
    expect(result).toBe('76561198012345678|3');
    expect(parseAdminEntries(result)).toEqual([
      { steamId: '76561198012345678', level: '3', lineIndex: 0 },
    ]);
  });

  it('appends onto a trailing blank line', () => {
    const result = upsertAdminLine('76561198012345678|3\n', '76561198000000001', 1);
    expect(result).toBe('76561198012345678|3\n76561198000000001|1');
  });

  it('appends a new line when the file has no trailing blank line', () => {
    const result = upsertAdminLine('76561198012345678|3', '76561198000000001', 1);
    expect(result).toBe('76561198012345678|3\n76561198000000001|1');
  });

  it('updates an existing SteamID in place instead of duplicating it', () => {
    const result = upsertAdminLine('76561198012345678|3', '76561198012345678', 5);
    expect(result).toBe('76561198012345678|5');
  });
});

describe('removeAdminLine', () => {
  it('drops only the matching SteamID', () => {
    const result = removeAdminLine('76561198012345678|3\n76561198000000001|1', '76561198012345678');
    expect(result).toBe('76561198000000001|1');
  });
});
