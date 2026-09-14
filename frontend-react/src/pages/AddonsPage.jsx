import React from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, Loader2, RefreshCw } from 'lucide-react';
import { useAddons } from '../contexts/AddonsContext';
import { resolveAddonIcon } from '../components/addons/addonIcons';

/**
 * The installed-addons list.
 *
 * Shows broken addons too, with their errors. An addon that silently vanished
 * because its manifest has a typo is far harder to diagnose than one listed
 * with the reason attached -- the same principle the backend catalog follows.
 */
function AddonCard({ addon }) {
  const Icon = resolveAddonIcon(addon.ui?.icon);
  const hasPage = Boolean(addon.ui?.page);
  const broken = !addon.loaded;
  const tooNew = addon.loaded && !addon.ui_mountable;

  return (
    <div className="rounded-lg border p-4"
         style={{ borderColor: 'var(--surface-border)', background: 'var(--surface-elevated)' }}>
      <div className="flex items-start gap-3">
        <Icon size={20} className="mt-0.5 flex-shrink-0 text-theme-muted" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <h3 className="text-sm font-semibold text-theme-primary">{addon.name}</h3>
            <span className="text-xs text-theme-muted">v{addon.version || '?'}</span>
            <span className="rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-theme-muted"
                  style={{ border: '1px solid var(--surface-border)' }}>
              {addon.source}
            </span>
          </div>
          {addon.description && (
            <p className="mt-1 text-sm text-theme-secondary">{addon.description}</p>
          )}

          {broken && (
            <div className="mt-2 rounded-md p-2 text-xs" style={{ background: 'rgba(239,68,68,0.08)' }}>
              <div className="flex items-center gap-1.5 font-medium" style={{ color: 'var(--accent-danger)' }}>
                <AlertTriangle size={13} /> Failed to load
              </div>
              <ul className="mt-1 list-disc pl-5 text-theme-secondary">
                {(addon.errors || []).map((err, i) => <li key={i}>{err}</li>)}
              </ul>
            </div>
          )}

          {tooNew && (
            <p className="mt-2 text-xs" style={{ color: 'var(--accent-warning, #d97706)' }}>
              This addon needs a newer QLSM to show its interface (it asks for UI API
              {' '}{addon.ui_api}). Its API still works.
            </p>
          )}

          {hasPage && !broken && (
            <Link to={`/addons/${addon.id}`}
                  className="mt-2 inline-block text-xs font-medium"
                  style={{ color: 'var(--accent-primary)' }}>
              Open
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

function AddonsPage() {
  const { addons, loading, error, reload } = useAddons();

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-theme-primary">Addons</h1>
          <p className="mt-1 text-sm text-theme-secondary">
            Optional features installed into this QLSM.
          </p>
        </div>
        <button type="button" onClick={reload} disabled={loading}
                className="inline-flex items-center gap-1.5 text-sm text-theme-secondary hover:text-theme-primary disabled:opacity-50">
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {loading && addons.length === 0 && (
        <div className="flex items-center gap-2 py-8 text-sm text-theme-muted">
          <Loader2 size={15} className="animate-spin" /> Loading...
        </div>
      )}

      {error && (
        <p className="mb-4 text-sm" style={{ color: 'var(--accent-danger)' }}>{error}</p>
      )}

      {!loading && addons.length === 0 && !error && (
        <p className="py-8 text-sm text-theme-muted">
          No addons installed. Drop an addon package into the addons directory and restart QLSM.
        </p>
      )}

      <div className="flex flex-col gap-3">
        {addons.map(addon => <AddonCard key={addon.id} addon={addon} />)}
      </div>
    </div>
  );
}

export default AddonsPage;
