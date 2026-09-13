import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getInstanceAdmins } from '../../services/api';

// Admin list for the Owner & Admins tab. Redis on the game server is the only
// source of truth: with an instance, the list is whatever the server has right
// now (including levels set in-game with !setperm). The *parent* owns edits:
// `entries` is null until the user touches something, and only the mutators
// call onChange. Nothing is mirrored upward from an effect -- that loops
// (parent setState -> new prop -> effect again) and would mark the modal dirty
// on open.
//
// `preload`, when given, is an in-flight getInstanceAdmins promise the parent
// started earlier (Edit Configuration starts it on open). The first load awaits
// it instead of making its own SSH round trip; Refresh always refetches.
export default function useInstanceAdmins({ instanceId, active, entries, onChange, onLoaded, preload = null }) {
  const [live, setLive] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  // onLoaded is usually an inline callback; keep it out of load's dependencies
  // so a new identity every render cannot re-trigger the fetch.
  const onLoadedRef = useRef(onLoaded);
  useEffect(() => { onLoadedRef.current = onLoaded; });

  // Refresh replaces the server list only. Pending edits live in the parent
  // and stay: Refresh shows in-game changes, it is not a discard button.
  const load = useCallback(async (pending = null) => {
    if (!instanceId) return;
    setLoading(true);
    try {
      const data = await (pending || getInstanceAdmins(instanceId));
      const admins = Array.isArray(data?.admins) ? data.admins : null;
      setLive(admins);
      setError(admins ? null : (data?.error || 'Could not read the admin list.'));
      if (admins && onLoadedRef.current) onLoadedRef.current(admins);
    } catch (err) {
      setLive(null);
      setError(err?.error?.message || 'Could not read the admin list.');
    } finally {
      setLoading(false);
    }
  }, [instanceId]);

  useEffect(() => { if (active) load(preload); }, [active, load, preload]);

  const effectiveEntries = useMemo(() => entries ?? live ?? [], [entries, live]);
  const rows = useMemo(
    () => effectiveEntries.map(({ steam_id64: steamId, level }) => ({ steamId, level })),
    [effectiveEntries],
  );

  const emit = useCallback((next) => { if (onChange) onChange(next); }, [onChange]);

  const addAdmin = useCallback((steamId, level) => {
    emit([
      ...effectiveEntries.filter((e) => e.steam_id64 !== steamId),
      { steam_id64: steamId, level: Number(level) },
    ]);
  }, [effectiveEntries, emit]);

  const removeAdmin = useCallback((steamId) => {
    emit(effectiveEntries.filter((e) => e.steam_id64 !== steamId));
  }, [effectiveEntries, emit]);

  return {
    rows,
    loading,
    error,
    // Without an instance (Add Instance, presets) the list is local and always
    // editable. With one, only once the server list is known: editing blind
    // would turn every unseen admin into a removal.
    editable: !instanceId || live !== null,
    refresh: () => load(),
    addAdmin,
    removeAdmin,
  };
}
