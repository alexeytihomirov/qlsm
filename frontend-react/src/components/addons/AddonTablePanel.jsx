import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Loader2, RefreshCw } from 'lucide-react';
import { addonRequest } from '../../services/addons';
import { resolveRoute } from './panelRoute';

/**
 * The `table` panel kind.
 *
 * Shaped by the feature it has to be able to express: the Demos modal --
 * a list of remote files with size/date, checkbox multi-select, a per-row
 * download, and a batch download of the selection. Anything that panel needs
 * is here; anything it does not is not.
 *
 * Manifest shape:
 *   { kind: "table",
 *     load: "GET demos?instance_id={instance_id}",
 *     rows: "demos",                       // key inside the response payload
 *     row_key: "name",
 *     selectable: true,
 *     empty: "No demos on this server yet.",
 *     columns: [{ key, label, format: "bytes"|"datetime"|"text", align }],
 *     row_actions:  [{ id, label, route: "GET demos/download?filename={name}", download: true }],
 *     bulk_actions: [{ id, label, route: "POST demos/download-batch", download: true }] }
 */

function formatCell(value, format) {
  if (value === null || value === undefined || value === '') return '-';
  if (format === 'bytes') {
    const bytes = Number(value);
    if (!Number.isFinite(bytes)) return String(value);
    const units = ['B', 'KB', 'MB', 'GB'];
    let n = bytes;
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
    return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
  }
  if (format === 'datetime') {
    // Accepts both an epoch (what SFTP mtime gives) and an ISO string.
    const asNumber = Number(value);
    const date = Number.isFinite(asNumber) && String(value).trim() !== ''
      ? new Date(asNumber * (asNumber > 1e11 ? 1 : 1000))
      : new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
  }
  return String(value);
}

function normalizeColumns(columns) {
  if (!Array.isArray(columns)) return [];
  return columns
    .filter(c => c && typeof c === 'object' && typeof c.key === 'string' && c.key.trim())
    .map(c => ({
      key: c.key.trim(),
      label: typeof c.label === 'string' && c.label.trim() ? c.label.trim() : c.key.trim(),
      format: ['bytes', 'datetime', 'text'].includes(c.format) ? c.format : 'text',
      align: c.align === 'right' ? 'right' : 'left',
    }));
}

function normalizeActions(actions) {
  if (!Array.isArray(actions)) return [];
  return actions
    .filter(a => a && typeof a === 'object' && typeof a.route === 'string' && a.route.trim())
    .map((a, i) => ({
      id: a.id || `action-${i}`,
      label: typeof a.label === 'string' && a.label.trim() ? a.label.trim() : 'Run',
      route: a.route,
      download: Boolean(a.download),
      danger: Boolean(a.danger),
      confirm: typeof a.confirm === 'string' ? a.confirm : null,
    }));
}

function AddonTablePanel({ addon, panel, scope, scopeId }) {
  const columns = useMemo(() => normalizeColumns(panel?.columns), [panel?.columns]);
  const rowActions = useMemo(() => normalizeActions(panel?.row_actions), [panel?.row_actions]);
  const bulkActions = useMemo(() => normalizeActions(panel?.bulk_actions), [panel?.bulk_actions]);
  const rowKey = panel?.row_key || columns[0]?.key || 'id';
  const selectable = Boolean(panel?.selectable) && bulkActions.length > 0;

  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState(() => new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyAction, setBusyAction] = useState(null);
  const [actionError, setActionError] = useState(null);

  const context = { scope, scopeId, addonId: addon.id };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const route = resolveRoute(panel.load, context);
      const data = await addonRequest(addon.id, route.method, route.path);
      const list = panel.rows ? data?.[panel.rows] : data;
      setRows(Array.isArray(list) ? list : []);
      setSelected(new Set());
    } catch (err) {
      setError(err?.response?.data?.error?.message || 'Failed to load');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addon.id, scope, scopeId, panel?.load, panel?.rows]);

  useEffect(() => { load(); }, [load]);

  const toggleRow = (key) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const allSelected = rows.length > 0 && selected.size === rows.length;
  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(rows.map(r => String(r[rowKey]))));
  };

  const runAction = async (action, row) => {
    if (action.confirm && !window.confirm(action.confirm)) return;
    setBusyAction(`${action.id}:${row ? row[rowKey] : 'bulk'}`);
    setActionError(null);
    try {
      // Row placeholders resolve from the row itself, so a route can say
      // {filename} or {id} and mean "this row's value".
      const rowContext = { ...context };
      let path = resolveRoute(action.route, rowContext);
      if (row) {
        path = {
          ...path,
          path: path.path.replace(/\{(\w+)\}/g, (whole, key) =>
            (row[key] === undefined || row[key] === null
              ? whole
              : encodeURIComponent(String(row[key])))),
        };
      }
      const payload = row ? undefined : { selected: Array.from(selected) };
      const result = await addonRequest(addon.id, path.method, path.path, { data: payload });
      if (action.download && result?.url) window.open(result.url, '_blank', 'noopener');
      if (!action.download) await load();
    } catch (err) {
      setActionError(err?.response?.data?.error?.message || 'Action failed');
    } finally {
      setBusyAction(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm text-theme-muted">
        <Loader2 size={15} className="animate-spin" /> Loading...
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-4">
        <p className="text-sm" style={{ color: 'var(--accent-danger)' }}>{error}</p>
        <button type="button" onClick={load}
                className="mt-2 inline-flex items-center gap-1.5 text-xs text-theme-secondary hover:text-theme-primary">
          <RefreshCw size={13} /> Retry
        </button>
      </div>
    );
  }

  if (rows.length === 0) {
    return <p className="py-6 text-sm text-theme-muted">{panel?.empty || 'Nothing to show.'}</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto rounded-md border" style={{ borderColor: 'var(--surface-border)' }}>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ background: 'var(--surface-elevated)' }}>
              {selectable && (
                <th className="w-10 px-3 py-2">
                  <input type="checkbox" checked={allSelected} onChange={toggleAll}
                         aria-label="Select all" className="h-4 w-4" />
                </th>
              )}
              {columns.map(col => (
                <th key={col.key}
                    className={`px-3 py-2 font-medium text-theme-secondary ${col.align === 'right' ? 'text-right' : 'text-left'}`}>
                  {col.label}
                </th>
              ))}
              {rowActions.length > 0 && <th className="px-3 py-2" />}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const key = String(row[rowKey] ?? index);
              return (
                <tr key={key} style={{ borderTop: '1px solid var(--surface-border)' }}>
                  {selectable && (
                    <td className="px-3 py-2">
                      <input type="checkbox" checked={selected.has(key)} onChange={() => toggleRow(key)}
                             aria-label={`Select ${key}`} className="h-4 w-4" />
                    </td>
                  )}
                  {columns.map(col => (
                    <td key={col.key}
                        className={`px-3 py-2 text-theme-primary ${col.align === 'right' ? 'text-right' : 'text-left'}`}>
                      {formatCell(row[col.key], col.format)}
                    </td>
                  ))}
                  {rowActions.length > 0 && (
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      {rowActions.map(action => (
                        <button key={action.id} type="button" onClick={() => runAction(action, row)}
                                disabled={busyAction !== null}
                                className="ml-2 text-xs underline-offset-2 hover:underline disabled:opacity-40"
                                style={{ color: action.danger ? 'var(--accent-danger)' : 'var(--accent-primary)' }}>
                          {busyAction === `${action.id}:${row[rowKey]}` ? '...' : action.label}
                        </button>
                      ))}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {actionError && (
        <p className="text-sm" style={{ color: 'var(--accent-danger)' }}>{actionError}</p>
      )}

      {selectable && (
        <div className="flex items-center gap-3">
          <span className="text-xs text-theme-muted">{selected.size} selected</span>
          {bulkActions.map(action => (
            <button key={action.id} type="button" onClick={() => runAction(action, null)}
                    disabled={selected.size === 0 || busyAction !== null}
                    className="rounded-md px-3 py-1.5 text-xs font-medium disabled:opacity-40"
                    style={{ background: 'var(--accent-primary)', color: 'var(--text-on-accent, #fff)' }}>
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default AddonTablePanel;
