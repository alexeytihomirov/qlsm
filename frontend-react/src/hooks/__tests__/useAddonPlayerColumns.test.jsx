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
