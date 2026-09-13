import { describe, expect, it } from 'vitest';
import { diffAdminLists } from '../adminChanges';

const A = '76561198012345678';
const B = '76561198087654321';
const C = '76561198000000009';

describe('diffAdminLists', () => {
  it('returns only added, re-levelled and removed admins', () => {
    const before = [{ steam_id64: A, level: 3 }, { steam_id64: B, level: 5 }, { steam_id64: C, level: 1 }];
    const after = [{ steam_id64: A, level: 3 }, { steam_id64: B, level: 2 }, { steam_id64: '76561198000000010', level: 4 }];
    expect(diffAdminLists(before, after)).toEqual([
      { steam_id64: B, level: 2 },
      { steam_id64: '76561198000000010', level: 4 },
      { steam_id64: C, level: 0 },
    ]);
  });

  it('is empty when nothing changed, and treats an unknown baseline as empty', () => {
    expect(diffAdminLists([{ steam_id64: A, level: 3 }], [{ steam_id64: A, level: '3' }])).toEqual([]);
    expect(diffAdminLists(null, [{ steam_id64: A, level: 3 }])).toEqual([{ steam_id64: A, level: 3 }]);
  });
});
