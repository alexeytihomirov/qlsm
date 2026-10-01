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

import { addonRequest, addonAssetUrl, isSafeAddonAssetPath } from '../addons';

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

describe('addonAssetUrl', () => {
  it('builds a URL under the addon own ui/ directory', () => {
    expect(addonAssetUrl('player-ranks', 'logos/qlstats.svg'))
      .toBe('/api/addons/player-ranks/ui/logos/qlstats.svg');
    expect(addonAssetUrl('player-ranks', '/logos/qlstats.svg'))
      .toBe('/api/addons/player-ranks/ui/logos/qlstats.svg');
  });

  it.each([
    '../../../hosts/1/x',
    'a/../../../hosts',
    '%2e%2e/%2e%2e/hosts',
    '..%2fx.svg',
    '..\\x.svg',
    './x.svg',
    'a//b.svg',
    'x.svg?a=1',
    'x.svg#f',
    '',
    '   ',
    null,
    undefined,
    42,
  ])('refuses a path that could leave the addon: %p', (path) => {
    // A live_status_columns cell's icon_url comes from the addon's JSON
    // response, which the manifest validator never sees, so this is the only
    // check it gets. The browser collapses dot segments, so without it
    // `../../../hosts/1/x` became a credentialed same-origin GET on a core
    // endpoint -- once per player, on every poll.
    expect(isSafeAddonAssetPath(path)).toBe(false);
    expect(addonAssetUrl('player-ranks', path)).toBeNull();
  });
});
