import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  requestUse: vi.fn(),
  responseUse: vi.fn(),
  create: vi.fn(),
}));

vi.mock('axios', () => ({
  default: {
    create: mocks.create.mockReturnValue({
      request: mocks.request,
      interceptors: {
        request: { use: mocks.requestUse },
        response: { use: mocks.responseUse },
      },
    }),
  },
}));

import { addonRequest } from '../addons';

describe('addonRequest', () => {
  beforeEach(() => {
    mocks.request.mockReset();
  });

  it('unwraps the response body\'s top-level "data" key by default', async () => {
    // Every declarative panel route (load/submit) follows this convention --
    // the body is {"data": {...the actual payload...}}.
    mocks.request.mockResolvedValue({ data: { data: { foo: 'bar' } } });

    const result = await addonRequest('player-ranks', 'GET', 'instances/1/config');

    expect(result).toEqual({ foo: 'bar' });
  });

  it('returns the whole response body when raw is true', async () => {
    // Real incident: live_status_columns route bodies carry `configured`
    // as a sibling of `data`, not nested under it. The default unwrap
    // silently dropped `configured`, so useAddonPlayerColumns read
    // `undefined !== false` as "configured" for every column regardless of
    // what the source actually reported, and `result.data` (now missing
    // the outer wrapper) was always undefined -- every rating cell showed
    // a dash no matter what was toggled on.
    mocks.request.mockResolvedValue({
      data: { configured: false, data: { '123': { display: '1357' } } },
    });

    const result = await addonRequest('player-ranks', 'GET', 'instances/1/ranks/qlstats', { raw: true });

    expect(result).toEqual({ configured: false, data: { '123': { display: '1357' } } });
  });
});
