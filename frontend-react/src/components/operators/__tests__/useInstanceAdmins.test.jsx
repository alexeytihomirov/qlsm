import { useState } from 'react';
import { renderHook, act, waitFor } from '@testing-library/react';
import { expect, it, vi, beforeEach } from 'vitest';
import useInstanceAdmins from '../useInstanceAdmins';

const getInstanceAdmins = vi.fn();
vi.mock('../../../services/api', () => ({
  getInstanceAdmins: (...args) => getInstanceAdmins(...args),
}));

const A = '76561198012345678';
const B = '76561198087654321';

beforeEach(() => getInstanceAdmins.mockReset());

// The parent owns the list, so render the hook the way real callers do:
// entries in state, onChange writing it back.
function renderAdmins(props = {}) {
  const onChange = vi.fn();
  const view = renderHook(
    ({ entries }) => useInstanceAdmins({ instanceId: 1, active: true, entries, onChange, ...props }),
    { initialProps: { entries: null } },
  );
  onChange.mockImplementation((next) => view.rerender({ entries: next }));
  return { ...view, onChange };
}

it('shows exactly what the server has', async () => {
  getInstanceAdmins.mockResolvedValue({ admins: [{ steam_id64: A, level: 3 }, { steam_id64: B, level: 5 }], error: null });
  const { result } = renderAdmins();
  await waitFor(() => expect(result.current.rows).toEqual([{ steamId: A, level: 3 }, { steamId: B, level: 5 }]));
  expect(result.current.editable).toBe(true);
  expect(result.current.error).toBeNull();
});

it('shows the error, no rows, and is not editable when the server cannot be read', async () => {
  getInstanceAdmins.mockResolvedValue({ admins: null, error: 'The server is unreachable.' });
  const { result } = renderAdmins();
  await waitFor(() => expect(result.current.error).toMatch(/unreachable/));
  expect(result.current.rows).toEqual([]);
  expect(result.current.editable).toBe(false);
});

it('reports nothing upward until a mutator runs, then edits the server list', async () => {
  getInstanceAdmins.mockResolvedValue({ admins: [{ steam_id64: A, level: 3 }], error: null });
  const { result, onChange } = renderAdmins();
  await waitFor(() => expect(result.current.rows).toHaveLength(1));
  expect(onChange).not.toHaveBeenCalled();

  act(() => result.current.addAdmin(B, '4'));
  expect(onChange).toHaveBeenLastCalledWith([{ steam_id64: A, level: 3 }, { steam_id64: B, level: 4 }]);
  act(() => result.current.removeAdmin(A));
  expect(onChange).toHaveBeenLastCalledWith([{ steam_id64: B, level: 4 }]);
});

it('refresh keeps unsaved edits', async () => {
  getInstanceAdmins.mockResolvedValue({ admins: [{ steam_id64: A, level: 3 }], error: null });
  const { result } = renderAdmins();
  await waitFor(() => expect(result.current.rows).toHaveLength(1));
  act(() => result.current.removeAdmin(A));
  await act(async () => { await result.current.refresh(); });
  expect(result.current.rows).toHaveLength(0);
});

it('reports the server list through onLoaded, once, with an inline callback', async () => {
  getInstanceAdmins.mockResolvedValue({ admins: [{ steam_id64: A, level: 3 }], error: null });
  function Wrapper() {
    const [loaded, setLoaded] = useState(null);
    const hook = useInstanceAdmins({
      instanceId: 1, active: true, entries: null, onChange: () => {}, onLoaded: (l) => setLoaded(l),
    });
    return { ...hook, loaded };
  }
  const { result } = renderHook(() => Wrapper());
  await waitFor(() => expect(result.current.loaded).toEqual([{ steam_id64: A, level: 3 }]));
  expect(getInstanceAdmins).toHaveBeenCalledTimes(1);
});

it('without an instance the list is local and editable', () => {
  const { result } = renderHook(() => useInstanceAdmins({
    instanceId: null, active: false, entries: [{ steam_id64: A, level: 2 }], onChange: () => {},
  }));
  expect(getInstanceAdmins).not.toHaveBeenCalled();
  expect(result.current.rows).toEqual([{ steamId: A, level: 2 }]);
  expect(result.current.editable).toBe(true);
});

it('awaits a preload promise instead of fetching, and Refresh refetches', async () => {
  const preload = Promise.resolve({ admins: [{ steam_id64: A, level: 3 }], error: null });
  getInstanceAdmins.mockResolvedValue({ admins: [], error: null });
  const { result } = renderHook(() => useInstanceAdmins({
    instanceId: 1, active: true, entries: null, onChange: () => {}, preload,
  }));
  await waitFor(() => expect(result.current.rows).toHaveLength(1));
  expect(getInstanceAdmins).not.toHaveBeenCalled();

  await act(async () => { await result.current.refresh(); });
  expect(getInstanceAdmins).toHaveBeenCalledWith(1);
});
