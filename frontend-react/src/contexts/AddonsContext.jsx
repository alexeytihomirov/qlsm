import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { listAddons } from '../services/addons';
import { useAuth } from './AuthContext';
import { MOUNT_SCOPES } from '../components/addons/panelRoute';

// One catalog fetch per session, shared by every mount point. Menus render on
// every row of the servers table, so per-menu fetching would mean dozens of
// identical requests on one page.
const AddonsContext = createContext({
  addons: [],
  loading: false,
  error: null,
  reload: () => {},
  mounts: () => [],
});

export function AddonsProvider({ children }) {
  const [addons, setAddons] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const { isAuthenticated } = useAuth();

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setAddons(await listAddons());
    } catch (err) {
      // Non-fatal by design: qlsm's own pages must keep working when the
      // addon catalog cannot be read. The UI simply shows no addon entries.
      setAddons([]);
      setError(err?.response?.data?.error?.message || 'Failed to load addons');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isAuthenticated) reload();
    else setAddons([]);
  }, [isAuthenticated, reload]);

  /**
   * Entries mounted at one extension point, flattened across addons.
   *
   * Only addons that actually loaded and whose declared ui_api this core
   * implements contribute. A broken or too-new addon stays visible on the
   * Addons list with its reason, but must not inject half-working UI into a
   * host's action menu.
   */
  const mounts = useCallback((point) => {
    const scope = MOUNT_SCOPES[point];
    const out = [];
    for (const addon of addons) {
      if (!addon.loaded || !addon.ui_mountable) continue;
      const declared = addon.ui?.[point];
      if (!declared) continue;
      const entries = Array.isArray(declared) ? declared : [declared];
      entries.forEach((entry, index) => {
        if (!entry || typeof entry !== 'object') return;
        const panel = entry.panel ? addon.ui?.panels?.[entry.panel] : null;
        if (entry.panel && !panel) return;  // manifest validation should have caught this
        out.push({
          key: `${addon.id}:${point}:${entry.id || index}`,
          addon,
          entry,
          panel,
          scope,
          label: entry.label || addon.name || addon.id,
          icon: entry.icon,
        });
      });
    }
    return out;
  }, [addons]);

  const value = useMemo(
    () => ({ addons, loading, error, reload, mounts }),
    [addons, loading, error, reload, mounts],
  );

  return <AddonsContext.Provider value={value}>{children}</AddonsContext.Provider>;
}

export function useAddons() {
  return useContext(AddonsContext);
}

export function useAddonMounts(point) {
  const { mounts } = useAddons();
  return mounts(point);
}

export default AddonsContext;
