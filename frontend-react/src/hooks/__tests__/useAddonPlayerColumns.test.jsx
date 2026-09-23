import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../services/addons', async () => {
  const actual = await vi.importActual('../../services/addons');
  return { ...actual, listAddons: vi.fn(), addonRequest: vi.fn() };
});
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true }) }));

import { listAddons, addonRequest } from '../../services/addons';
import { AddonsProvider } from '../../contexts/AddonsContext';
import { useAddonPlayerColumns } from '../useAddonPlayerColumns';

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

beforeEach(() => {
  vi.clearAllMocks();
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
    expect(addonRequest).toHaveBeenCalledWith(
      'player-ranks', 'GET', 'instances/1/ranks', { params: { steam_ids: '1,2' } },
    );
  });
});
