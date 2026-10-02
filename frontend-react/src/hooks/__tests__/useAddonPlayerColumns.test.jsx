import React from 'react';
import { act, configure, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../services/addons', async () => {
  const actual = await vi.importActual('../../services/addons');
  return { ...actual, listAddons: vi.fn(), addonRequest: vi.fn() };
});
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true }) }));

import { listAddons, addonRequest } from '../../services/addons';
import { AddonsProvider } from '../../contexts/AddonsContext';
import { useAddonPlayerColumns, playerSteamId, normalizeCell } from '../useAddonPlayerColumns';

const RATING_ADDON = {
  id: 'player-ranks', name: 'Player Ranks', version: '1.0.0',
  loaded: true, ui_mountable: true, enabled: true,
  ui: {
    live_status_columns: [
      { id: 'rating', label: 'Rating', align: 'right', route: 'GET instances/{instance_id}/ranks' },
    ],
  },
};

const wrapper = ({ children }) => <AddonsProvider>{children}</AddonsProvider>;

const players = [{ steam: '76561197993968023' }, { steam: '76561197960287930' }];

// Matches the hook's own constants; the debounce/interval assertions below
// drive them through fake timers rather than waiting in real time.
const POLL_INTERVAL_MS = 30000;
const ROSTER_DEBOUNCE_MS = 3000;

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useAddonPlayerColumns', () => {
  it('returns nothing while the addon has not answered yet', async () => {
    listAddons.mockResolvedValue([RATING_ADDON]);
    addonRequest.mockResolvedValue(new Promise(() => {})); // never resolves

    const { result } = renderHook(
      () => useAddonPlayerColumns(true, 1, players),
      { wrapper },
    );

    await waitFor(() => expect(listAddons).toHaveBeenCalled());
    expect(result.current).toEqual([]);
  });

  it('exposes a configured column with fetched data', async () => {
    listAddons.mockResolvedValue([RATING_ADDON]);
    addonRequest.mockResolvedValue({
      data: { '76561197993968023': { display: '2181', title: 'duel, 13732 games' } },
      configured: true,
    });

    const { result } = renderHook(
      () => useAddonPlayerColumns(true, 1, players),
      { wrapper },
    );

    await waitFor(() => expect(result.current).toHaveLength(1));
    expect(result.current[0]).toMatchObject({ key: 'player-ranks:live_status_columns:rating', label: 'Rating', align: 'right' });
    expect(result.current[0].data['76561197993968023'].display).toBe('2181');
  });

  it('still shows the column under StrictMode, whose dev double-mount runs the unmount cleanup once', async () => {
    // The Vite dev server renders the app in <StrictMode>, which mounts,
    // runs every effect cleanup, and mounts again. A liveness flag cleared in
    // that cleanup and never set back made the hook discard every response,
    // so the column never appeared in development.
    listAddons.mockResolvedValue([RATING_ADDON]);
    addonRequest.mockResolvedValue({
      data: { '76561197993968023': { display: '2181' } },
      configured: true,
    });
    // A <StrictMode> in the wrapper is not enough: Testing Library only
    // double-mounts when told to through its own config.
    configure({ reactStrictMode: true });
    try {
      const { result } = renderHook(
        () => useAddonPlayerColumns(true, 1, players),
        { wrapper },
      );

      await waitFor(() => expect(result.current).toHaveLength(1));
      expect(result.current[0].data['76561197993968023'].display).toBe('2181');
    } finally {
      configure({ reactStrictMode: false });
    }
  });

  it('hides the column entirely when the addon reports configured: false', async () => {
    listAddons.mockResolvedValue([RATING_ADDON]);
    addonRequest.mockResolvedValue({ data: {}, configured: false });

    const { result } = renderHook(
      () => useAddonPlayerColumns(true, 1, players),
      { wrapper },
    );

    await waitFor(() => expect(addonRequest).toHaveBeenCalled());
    expect(result.current).toEqual([]);
  });

  it('does not fetch when the modal is closed', async () => {
    listAddons.mockResolvedValue([RATING_ADDON]);

    renderHook(() => useAddonPlayerColumns(false, 1, players), { wrapper });

    await waitFor(() => expect(listAddons).toHaveBeenCalled());
    expect(addonRequest).not.toHaveBeenCalled();
  });

  it('resets data when the instance changes', async () => {
    listAddons.mockResolvedValue([RATING_ADDON]);
    addonRequest.mockResolvedValue({
      data: { '76561197993968023': { display: '2181' } },
      configured: true,
    });

    const { result, rerender } = renderHook(
      ({ instanceId }) => useAddonPlayerColumns(true, instanceId, players),
      { wrapper, initialProps: { instanceId: 1 } },
    );

    await waitFor(() => expect(result.current).toHaveLength(1));

    addonRequest.mockResolvedValue(new Promise(() => {}));
    act(() => rerender({ instanceId: 2 }));

    expect(result.current).toEqual([]);
  });

  it('retries a previously-unconfigured column on reopen, same instance', async () => {
    // Real incident: an operator fixed an instance's rating source while its
    // Live Status modal had ever been opened. The modal never unmounts on
    // close (see LiveServerStatusModal), so without a re-arm on reopen the
    // column would stay hidden forever despite the fix.
    listAddons.mockResolvedValue([RATING_ADDON]);
    addonRequest.mockResolvedValue({ data: {}, configured: false });

    const { result, rerender } = renderHook(
      ({ isOpen }) => useAddonPlayerColumns(isOpen, 1, players),
      { wrapper, initialProps: { isOpen: true } },
    );

    await waitFor(() => expect(addonRequest).toHaveBeenCalledTimes(1));
    expect(result.current).toEqual([]);

    // Operator closes the modal, fixes the source server-side, reopens it.
    act(() => rerender({ isOpen: false }));
    addonRequest.mockResolvedValue({
      data: { '76561197993968023': { display: '2181' } },
      configured: true,
    });
    act(() => rerender({ isOpen: true }));

    await waitFor(() => expect(result.current).toHaveLength(1));
    expect(result.current[0].data['76561197993968023'].display).toBe('2181');
  });

  it('shows a later-declared column even when earlier ones are unconfigured', async () => {
    // Real bug this guards against: one addon declaring more columns than
    // MAX_COLUMNS fit (e.g. one per rating source, only some enabled per
    // instance). Capping the *declared* list before fetching would make the
    // 4th-declared column permanently invisible no matter what an operator
    // actually turns on -- it must be capped by what comes back configured.
    const FOUR_COLUMN_ADDON = {
      id: 'player-ranks', name: 'Player Ranks', version: '1.0.0',
      loaded: true, ui_mountable: true, enabled: true,
      ui: {
        live_status_columns: [
          { id: 'qlstats', label: 'qlstats', align: 'right', route: 'GET instances/{instance_id}/ranks/qlstats' },
          { id: 'slipgate', label: 'Slipgate', align: 'right', route: 'GET instances/{instance_id}/ranks/slipgate' },
          { id: 'elo_service', label: 'ELO', align: 'right', route: 'GET instances/{instance_id}/ranks/elo_service' },
          { id: 'server_status', label: 'Status', align: 'right', route: 'GET instances/{instance_id}/ranks/server_status' },
        ],
      },
    };
    listAddons.mockResolvedValue([FOUR_COLUMN_ADDON]);
    addonRequest.mockImplementation((addonId, method, path) => {
      if (path.endsWith('/server_status')) {
        return Promise.resolve({ data: { '1': { display: '42' } }, configured: true });
      }
      return Promise.resolve({ data: {}, configured: false });
    });

    const { result } = renderHook(
      () => useAddonPlayerColumns(true, 1, players),
      { wrapper },
    );

    await waitFor(() => expect(result.current).toHaveLength(1));
    expect(result.current[0].key).toBe('player-ranks:live_status_columns:server_status');
  });

  it('caps at 3 shown columns by actually-configured count, not declaration order', async () => {
    const FOUR_COLUMN_ADDON = {
      id: 'player-ranks', name: 'Player Ranks', version: '1.0.0',
      loaded: true, ui_mountable: true, enabled: true,
      ui: {
        live_status_columns: [
          { id: 'qlstats', label: 'qlstats', align: 'right', route: 'GET instances/{instance_id}/ranks/qlstats' },
          { id: 'slipgate', label: 'Slipgate', align: 'right', route: 'GET instances/{instance_id}/ranks/slipgate' },
          { id: 'elo_service', label: 'ELO', align: 'right', route: 'GET instances/{instance_id}/ranks/elo_service' },
          { id: 'server_status', label: 'Status', align: 'right', route: 'GET instances/{instance_id}/ranks/server_status' },
        ],
      },
    };
    listAddons.mockResolvedValue([FOUR_COLUMN_ADDON]);
    addonRequest.mockResolvedValue({ data: {}, configured: true });

    const { result } = renderHook(
      () => useAddonPlayerColumns(true, 1, players),
      { wrapper },
    );

    await waitFor(() => expect(result.current).toHaveLength(3));
  });

  it('does not fetch, and keeps showing the last value, when the roster is momentarily empty', async () => {
    // Real incident: useServerStatus replaces its whole map on every 15s
    // poll rather than merging it, so an instance briefly missing from one
    // poll response makes `players` empty for a render or two. Without this
    // guard, that blip sends steam_ids='', every provider answers with
    // `configured: true, data: {}` (addons/README.md contract), and the
    // hook would blank out an already-shown value for a poll cycle.
    listAddons.mockResolvedValue([RATING_ADDON]);
    addonRequest.mockResolvedValue({
      data: { '76561197993968023': { display: '2181' } },
      configured: true,
    });

    const { result, rerender } = renderHook(
      ({ roster }) => useAddonPlayerColumns(true, 1, roster),
      { wrapper, initialProps: { roster: players } },
    );

    await waitFor(() => expect(result.current).toHaveLength(1));
    expect(result.current[0].data['76561197993968023'].display).toBe('2181');

    const callsBeforeBlip = addonRequest.mock.calls.length;
    act(() => rerender({ roster: [] }));

    // No roster -> no request at all, and the value from the last good
    // fetch is still there instead of being replaced with a dash.
    expect(addonRequest.mock.calls.length).toBe(callsBeforeBlip);
    expect(result.current).toHaveLength(1);
    expect(result.current[0].data['76561197993968023'].display).toBe('2181');
  });

  it('passes steam_ids as a sorted, deduplicated comma-joined string', async () => {
    listAddons.mockResolvedValue([RATING_ADDON]);
    addonRequest.mockResolvedValue({ data: {}, configured: true });

    renderHook(
      () => useAddonPlayerColumns(true, 1, [
        { steam: '2' }, { steam: '1' }, { steam: '2' },
      ]),
      { wrapper },
    );

    await waitFor(() => expect(addonRequest).toHaveBeenCalled());
    // raw: true matters here -- this route's body carries `configured`
    // alongside `data`, not nested under it. addonRequest's default unwrap
    // (services/addons.test.js) strips to response.data.data, which would
    // silently drop `configured` and leave `data` undefined: every column
    // would read as "configured" (undefined !== false) with an empty cell
    // regardless of what the source actually reported -- the exact bug a
    // live operator hit (qlstats returning a real rating, every cell still
    // showing a dash).
    expect(addonRequest).toHaveBeenCalledWith(
      'player-ranks', 'GET', 'instances/1/ranks', { params: { steam_ids: '1,2' }, raw: true },
    );
  });

  it('keeps the column and its last values when a poll fails transiently', async () => {
    // A 500/timeout is not the source saying "nothing to report": marking it
    // unconfigured pulled the whole column -- header included -- out of the
    // table for a full 30s poll interval on a single hiccup, which is exactly
    // what the empty-roster guard above exists to avoid.
    listAddons.mockResolvedValue([RATING_ADDON]);
    addonRequest.mockResolvedValue({
      data: { '76561197993968023': { display: '2181' } },
      configured: true,
    });

    const { result, rerender } = renderHook(
      ({ roster }) => useAddonPlayerColumns(true, 1, roster),
      { wrapper, initialProps: { roster: players } },
    );

    await waitFor(() => expect(result.current).toHaveLength(1));

    const boom = new Error('gateway timeout');
    boom.response = { status: 500 };
    addonRequest.mockRejectedValue(boom);
    act(() => rerender({ roster: [...players, { steam: '76561197000000001' }] }));
    await act(() => vi.advanceTimersByTimeAsync(ROSTER_DEBOUNCE_MS + 10));

    expect(result.current).toHaveLength(1);
    expect(result.current[0].data['76561197993968023'].display).toBe('2181');
  });

  it('drops the column on a 404 and stops asking', async () => {
    listAddons.mockResolvedValue([RATING_ADDON]);
    const gone = new Error('not found');
    gone.response = { status: 404 };
    addonRequest.mockRejectedValue(gone);

    const { result } = renderHook(() => useAddonPlayerColumns(true, 1, players), { wrapper });

    await waitFor(() => expect(addonRequest).toHaveBeenCalledTimes(1));
    expect(result.current).toEqual([]);

    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 10));
    expect(addonRequest).toHaveBeenCalledTimes(1);   // latched, not re-asked
  });

  it('coalesces roster churn into one fetch and does not restart the interval', async () => {
    listAddons.mockResolvedValue([RATING_ADDON]);
    addonRequest.mockResolvedValue({ data: {}, configured: true });

    const { rerender } = renderHook(
      ({ roster }) => useAddonPlayerColumns(true, 1, roster),
      { wrapper, initialProps: { roster: players } },
    );

    await waitFor(() => expect(addonRequest).toHaveBeenCalledTimes(1));

    // Four joins inside the debounce window -> one extra fetch, not four.
    for (let i = 0; i < 4; i += 1) {
      act(() => rerender({ roster: [...players, ...Array.from({ length: i + 1 }, (_, n) => ({ steam: `900${n}` }))] }));
      await act(() => vi.advanceTimersByTimeAsync(ROSTER_DEBOUNCE_MS / 4));
    }
    await act(() => vi.advanceTimersByTimeAsync(ROSTER_DEBOUNCE_MS + 10));
    expect(addonRequest).toHaveBeenCalledTimes(2);
  });

  it('normalizes a malformed cell instead of handing it to the renderer', async () => {
    // entries: [null] used to reach JSX and crash the Live Status drawer with
    // "Cannot read properties of null (reading 'title')".
    listAddons.mockResolvedValue([RATING_ADDON]);
    addonRequest.mockResolvedValue({
      configured: true,
      data: {
        '76561197993968023': { entries: [null, 'nope', { display: '1357', icon_url: 'a.svg' }] },
        '76561197960287930': 'not an object',
      },
    });

    const { result } = renderHook(() => useAddonPlayerColumns(true, 1, players), { wrapper });

    await waitFor(() => expect(result.current).toHaveLength(1));
    const data = result.current[0].data;
    expect(data['76561197993968023'].entries).toEqual([
      { display: '1357', title: '', icon: null, iconUrl: 'a.svg', color: null },
    ]);
    expect(data['76561197960287930']).toBeUndefined();
  });
});

describe('playerSteamId', () => {
  it('skips an empty value and falls through to the next key', () => {
    // The hook and the players table must agree exactly: when they did not,
    // a player with steam: '' was asked about under no key at all and looked
    // up under steamid, so the cell stayed empty forever.
    expect(playerSteamId({ steam: '', steamid: '765' })).toBe('765');
    expect(playerSteamId({ steam: '  ', steam_id: 765 })).toBe('765');
    expect(playerSteamId({})).toBeNull();
    expect(playerSteamId(null)).toBeNull();
  });
});

describe('normalizeCell', () => {
  it('reduces a cell to renderable text and drops unusable entries', () => {
    expect(normalizeCell(null)).toBeNull();
    expect(normalizeCell('1802')).toBeNull();
    expect(normalizeCell({ display: 1802 })).toEqual({ display: '1802', title: '', color: null, entries: null });
    expect(normalizeCell({ entries: [] })).toEqual({ display: '', title: '', color: null, entries: null });
    expect(normalizeCell({ entries: [{ display: 'a', icon: 'gauge' }] })).toEqual({
      display: '', title: '', color: null,
      entries: [{ display: 'a', title: '', icon: 'gauge', iconUrl: null, color: null }],
    });
  });

  it('keeps a color from the fixed palette and drops anything else', () => {
    expect(normalizeCell({ display: 'Gold III', color: 'yellow' }).color).toBe('yellow');
    expect(normalizeCell({ entries: [{ display: 'Gold III', color: 'yellow' }] }).entries[0].color).toBe('yellow');
    // Not a palette name: a raw CSS value, a class name, a non-string.
    expect(normalizeCell({ display: 'x', color: '#ff0000' }).color).toBeNull();
    expect(normalizeCell({ display: 'x', color: 'text-red-500' }).color).toBeNull();
    expect(normalizeCell({ entries: [{ display: 'x', color: { a: 1 } }] }).entries[0].color).toBeNull();
    // An Object.prototype key must not pass as a palette name.
    expect(normalizeCell({ display: 'x', color: 'constructor' }).color).toBeNull();
  });
});
