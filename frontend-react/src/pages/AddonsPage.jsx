import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, Clock, Loader2, RefreshCw, Settings, Trash2, Upload } from 'lucide-react';
import AddonInstallModal from '../components/addons/AddonInstallModal';
import AddonSettingsModal from '../components/addons/AddonSettingsModal';
import ConfirmationModal from '../components/ConfirmationModal';
import RestartQlsmBanner from '../components/system/RestartQlsmBanner';
import { useNotification } from '../components/NotificationProvider';
import { mountEntriesForAddon, useAddons } from '../contexts/AddonsContext';
import { resolveAddonIcon } from '../components/addons/addonIcons';
import { uninstallAddon, updateAddonState } from '../services/addons';

/**
 * Enabled/disabled state pill, for any loaded addon regardless of source.
 *
 * Mirrors the active/inactive indicator used for server instances
 * (StatusIndicator) so an addon's on/off state reads the same way at a
 * glance, without pulling in that component's status-string vocabulary
 * ("running", "stopped", ...) which does not apply here.
 */
function AddonStatusPill({ enabled }) {
  const color = enabled ? '#0D9668' : '#3E4C5E';
  const bg = enabled ? 'rgba(13, 150, 104, 0.1)' : 'rgba(62, 76, 94, 0.08)';
  return (
    <span className="inline-flex flex-shrink-0 items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
          style={{ background: bg, color }}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {enabled ? 'Enabled' : 'Disabled'}
    </span>
  );
}

/**
 * Whole-addon on/off switch, for any loaded addon regardless of source.
 *
 * Backed by AddonState('global', 0), the same row a managed settings panel's
 * "Enabled for this global" checkbox would use; this is a second UI onto the
 * same switch, needed because most addons here (all three migrated built-in
 * features) use custom, not managed, settings panels and so never surface
 * that checkbox on their own. Shown only once an addon has actually loaded --
 * a pending-install/pending-uninstall entry has no AddonContext to read or
 * write the state through yet.
 */
function AddonEnableToggle({ addon, disabled, onChanged }) {
  const { showError } = useNotification();
  const [busy, setBusy] = useState(false);

  const handleClick = async () => {
    const next = !addon.enabled;
    setBusy(true);
    try {
      await updateAddonState(addon.id, 'global', 0, { enabled: next });
      onChanged();
    } catch (err) {
      showError(err?.response?.data?.error?.message || 'Failed to update addon state.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <button type="button" onClick={handleClick} disabled={disabled || busy}
            className="inline-flex flex-shrink-0 items-center justify-center rounded-md border px-3 py-1.5 text-xs font-medium text-theme-secondary transition-colors hover:text-theme-primary hover:bg-black/[0.04] disabled:opacity-40 dark:hover:bg-white/[0.04]"
            style={{ borderColor: 'var(--surface-border-strong)' }}>
      {busy ? '...' : (addon.enabled ? 'Disable' : 'Enable')}
    </button>
  );
}

/**
 * The installed-addons list, plus install / uninstall.
 *
 * Shows broken addons too, with their errors. An addon that silently vanished
 * because its manifest has a typo is far harder to diagnose than one listed
 * with the reason attached -- the same principle the backend catalog follows.
 */
function AddonCard({ addon, onUninstall, onOpenSettings, onToggled, busy }) {
  const Icon = resolveAddonIcon(addon.ui?.icon);
  const hasPage = Boolean(addon.ui?.page);
  const broken = !addon.loaded && !addon.pending_restart;
  const tooNew = addon.loaded && !addon.ui_mountable;
  const hasSettings = mountEntriesForAddon(addon, 'settings_section').length > 0;

  return (
    <div className="rounded-lg border p-4"
         style={{ borderColor: 'var(--surface-border)', background: 'var(--surface-elevated)' }}>
      <div className="flex items-start gap-3">
        <Icon size={20} className="mt-0.5 flex-shrink-0 text-theme-muted" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <h3 className="text-sm font-semibold text-theme-primary">{addon.name}</h3>
            {addon.version && <span className="text-xs text-theme-muted">v{addon.version}</span>}
            <span className="rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-theme-muted"
                  style={{ border: '1px solid var(--surface-border)' }}>
              {addon.source}
            </span>
            {addon.loaded && <AddonStatusPill enabled={Boolean(addon.enabled)} />}
          </div>
          {addon.description && (
            <p className="mt-1 text-sm text-theme-secondary">{addon.description}</p>
          )}
          {addon.loaded && !addon.enabled && (
            <p className="mt-1 text-xs text-theme-muted">
              Disabled - hidden from host/instance menus until switched on.
            </p>
          )}

          {/* Honest about the one thing this system cannot do: Flask cannot
              hot-add or drop a blueprint, so a fresh install is inert until
              the process restarts. Saying so beats an entry whose endpoints 404. */}
          {addon.pending_restart && (
            <p className="mt-2 inline-flex items-center gap-1.5 text-xs"
               style={{ color: 'var(--accent-warning, #d97706)' }}>
              <Clock size={13} />
              {addon.pending_action === 'uninstall'
                ? 'Removed from disk. Restart QLSM to unload it.'
                : addon.pending_action === 'update'
                ? 'Updated on disk. Restart QLSM to run the new version.'
                : 'Installed. Restart QLSM to activate it.'}
            </p>
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

        </div>
        {hasSettings && (
          <button type="button" onClick={() => onOpenSettings(addon)} aria-label={`${addon.name} settings`}
                  title="Addon settings"
                  className="flex-shrink-0 rounded-md p-1.5 text-theme-muted hover:text-theme-primary hover:bg-black/[0.04] dark:hover:bg-white/[0.04]">
            <Settings size={16} />
          </button>
        )}
      </div>

      <div className="mt-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          {hasPage && !broken && !addon.pending_restart && (
            <Link to={`/addons/${addon.id}`} className="text-xs font-medium"
                  style={{ color: 'var(--accent-primary)' }}>
              Open
            </Link>
          )}
          {addon.source === 'installed' && !addon.pending_restart && (
            <button type="button" onClick={() => onUninstall(addon)} disabled={busy}
                    className="inline-flex items-center gap-1 text-xs disabled:opacity-40"
                    style={{ color: 'var(--accent-danger)' }}>
              <Trash2 size={13} /> Uninstall
            </button>
          )}
        </div>
        {addon.loaded && (
          <AddonEnableToggle addon={addon} disabled={!addon.loaded} onChanged={onToggled} />
        )}
      </div>
    </div>
  );
}

function AddonsPage() {
  const { addons, loading, error, reload } = useAddons();
  const { showSuccess, showError } = useNotification();
  const [installOpen, setInstallOpen] = useState(false);
  const [pendingUninstall, setPendingUninstall] = useState(null);
  const [settingsAddon, setSettingsAddon] = useState(null);
  const [busy, setBusy] = useState(false);

  const anyPending = addons.some(a => a.pending_restart);

  const handleInstalled = (result) => {
    setInstallOpen(false);
    showSuccess(`"${result.name || result.id}" installed. Restart QLSM to activate it.`);
    reload();
  };

  const handleUninstall = async () => {
    const addon = pendingUninstall;
    setPendingUninstall(null);
    if (!addon) return;
    setBusy(true);
    try {
      await uninstallAddon(addon.id);
      showSuccess(`"${addon.name}" removed. Restart QLSM to unload it.`);
      reload();
    } catch (err) {
      showError(err?.response?.data?.error?.message || 'Failed to uninstall the addon.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-theme-primary">Addons</h1>
          <p className="mt-1 text-sm text-theme-secondary">
            Optional features installed into this QLSM. An addon runs with full access -
            install only what you trust.
          </p>
        </div>
        <div className="flex flex-shrink-0 items-center gap-3">
          <button type="button" onClick={reload} disabled={loading}
                  className="inline-flex items-center gap-1.5 text-sm text-theme-secondary hover:text-theme-primary disabled:opacity-50">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
          <button type="button" onClick={() => setInstallOpen(true)} className="users-add-btn">
            <Upload size={15} /> <span>Install</span>
          </button>
        </div>
      </div>

      {anyPending && (
        <RestartQlsmBanner message="Some changes need a QLSM restart before they take effect." />
      )}

      {loading && addons.length === 0 && (
        <div className="flex items-center gap-2 py-8 text-sm text-theme-muted">
          <Loader2 size={15} className="animate-spin" /> Loading...
        </div>
      )}

      {error && <p className="mb-4 text-sm" style={{ color: 'var(--accent-danger)' }}>{error}</p>}

      {!loading && addons.length === 0 && !error && (
        <p className="py-8 text-sm text-theme-muted">
          No addons installed yet. Use Install to upload an addon package.
        </p>
      )}

      <div className="flex flex-col gap-3">
        {addons.map(addon => (
          <AddonCard key={addon.id} addon={addon} busy={busy} onToggled={reload}
                     onUninstall={setPendingUninstall} onOpenSettings={setSettingsAddon} />
        ))}
      </div>

      <AddonInstallModal isOpen={installOpen} onClose={() => setInstallOpen(false)}
                         onInstalled={handleInstalled} />

      <AddonSettingsModal addon={settingsAddon} isOpen={Boolean(settingsAddon)}
                          onClose={() => setSettingsAddon(null)} />

      <ConfirmationModal
        isOpen={Boolean(pendingUninstall)}
        onClose={() => setPendingUninstall(null)}
        onConfirm={handleUninstall}
        title={`Uninstall "${pendingUninstall?.name || ''}"?`}
        message={'Its package is deleted, but anything it already did - rows it wrote, files it put on a game host, cvars it set - is not undone. Its settings are kept so a reinstall finds them again.'}
        confirmButtonText="Uninstall"
        confirmButtonVariant="danger"
      />
    </div>
  );
}

export default AddonsPage;
