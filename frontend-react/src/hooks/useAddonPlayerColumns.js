import { useEffect, useMemo, useRef, useState } from 'react';
import { useAddonMounts } from '../contexts/AddonsContext';
import { resolveRoute } from '../components/addons/panelRoute';
import { addonRequest } from '../services/addons';

// Independent from the 15s server-status poll on purpose (design: qlsm addon
// live_status_columns contract) -- a rating source is far slower-moving than
// the match state, and coupling the two would mean re-fetching ratings on
// every status tick for no reason.
const POLL_INTERVAL_MS = 30000;

// "не более 3 contributing columns" -- past that the narrow players table
// turns into noise. Extras are dropped with a console warning, not an error:
// the table still works, just without the overflow columns.
//
// This caps what's actually *shown* (columns that came back configured:
// true), not what's declared. An addon may declare more columns than fit
// (e.g. one per rating source, only some enabled per instance) -- every
// declared column is still fetched, since whether a given instance has it
// configured is only known after that fetch; capping the declared list
// upfront would make an addon's 4th-declared column permanently invisible
// regardless of which ones an operator actually turned on.
const MAX_COLUMNS = 3;

function playerSteamId(player) {
  const raw = player?.steam ?? player?.steamid ?? player?.steam_id;
  return raw === undefined || raw === null ? null : String(raw);
}

/** Sorted, joined steam_id string -- a stable primitive, not an array, so it
 * can be an effect dependency without the array-identity-changes-every-poll
 * trap `useServerStatus` already ran into once (see design doc 8.3). */
function steamIdsKey(players) {
  const ids = new Set((players || []).map(playerSteamId).filter(Boolean));
  return Array.from(ids).sort().join(',');
}

/**
 * Addon-contributed player rating/status columns for LiveServerStatusModal.
 *
 * Core has no idea what a "rating" is -- it just renders whatever
 * `live_status_columns` entries the loaded addons declare and fetches
 * whatever their route returns. See addons/README.md.
 */
export function useAddonPlayerColumns(isOpen, instanceId, players) {
  const rawColumns = useAddonMounts('live_status_columns');

  // rawColumns is a fresh array every render (AddonsContext.mounts() rebuilds
  // it each call); derive a stable primitive key from its actual content so
  // effects below don't re-fire on every unrelated re-render.
  const columnsKey = useMemo(
    () => rawColumns.map((c) => c.key).join('|'),
    [rawColumns],
  );
  const columnsRef = useRef(rawColumns);
  columnsRef.current = rawColumns;

  const idsKey = useMemo(() => steamIdsKey(players), [players]);

  const [state, setState] = useState({});
  // "configured: false"/404 means the source genuinely has nothing to say
  // for this instance -- stop asking until the instance changes or the
  // operator looks again. A transient error (timeout, 500) does not set
  // this; the next poll tries again.
  const stoppedRef = useRef({});
  const instanceRef = useRef(instanceId);

  useEffect(() => {
    instanceRef.current = instanceId;
    stoppedRef.current = {};
    setState({});
  }, [instanceId]);

  // Re-arm the latch on every isOpen false->true transition, not just on an
  // instanceId change. LiveServerStatusModal is mounted unconditionally (see
  // its own comment), so closing and reopening it does not remount this
  // hook -- without this, an operator who fixes an instance's rating source
  // while that instance's Live Status has ever been open would never see
  // the column start working without a full page reload: the first poll
  // already latched every column "stopped" and nothing here asked again.
  // One extra request per modal-open is cheap; the 30s interval below still
  // only runs while the modal stays open.
  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (isOpen && !wasOpenRef.current) {
      stoppedRef.current = {};
    }
    wasOpenRef.current = isOpen;
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || !instanceId || !columnsKey) return undefined;
    let cancelled = false;

    const fetchAll = async () => {
      const columns = columnsRef.current;
      await Promise.all(columns.map(async (col) => {
        if (stoppedRef.current[col.key]) return;
        const resolved = resolveRoute(col.entry.route, {
          scope: col.scope, scopeId: instanceId, addonId: col.addon.id,
        });
        if (!resolved) return;
        try {
          const result = await addonRequest(col.addon.id, resolved.method, resolved.path, {
            params: { steam_ids: idsKey },
          });
          if (cancelled || instanceRef.current !== instanceId) return;
          const configured = result?.configured !== false;
          if (!configured) stoppedRef.current[col.key] = true;
          setState((prev) => ({
            ...prev,
            [col.key]: { data: result?.data || {}, configured },
          }));
        } catch (err) {
          if (cancelled || instanceRef.current !== instanceId) return;
          if (err?.response?.status === 404) stoppedRef.current[col.key] = true;
          setState((prev) => ({
            ...prev,
            [col.key]: { data: prev[col.key]?.data || {}, configured: false },
          }));
        }
      }));
    };

    fetchAll();
    const interval = setInterval(fetchAll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [isOpen, instanceId, idsKey, columnsKey]);

  return useMemo(() => {
    const configuredColumns = rawColumns
      .map((col) => ({
        key: col.key,
        label: col.entry.label,
        align: col.entry.align === 'right' ? 'right' : 'left',
        icon: col.entry.icon,
        iconUrl: col.entry.icon_url,
        addonId: col.addon.id,
        configured: state[col.key]?.configured ?? false,
        data: state[col.key]?.data ?? {},
      }))
      .filter((col) => col.configured);

    if (configuredColumns.length > MAX_COLUMNS) {
      // eslint-disable-next-line no-console
      console.warn(
        `[live_status_columns] ${configuredColumns.length} columns configured, `
        + `only the first ${MAX_COLUMNS} are shown: ${configuredColumns.map((c) => c.key).join(', ')}`,
      );
    }

    return configuredColumns.slice(0, MAX_COLUMNS);
  }, [rawColumns, state]);
}
