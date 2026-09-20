import React, { useState } from 'react';
import {
  Trash2, RefreshCw, AlertTriangle, Loader2, Download, ChevronRight,
} from 'lucide-react';
import { downloadPluginRepositoryPlugins, installPluginRepositoryAddon } from '../../services/api';
import { useNotification } from '../NotificationProvider';
import { formatDateTime } from '../../utils/uiUtils';
import RuntimePicker from './RuntimePicker';
import OverwritePluginsModal from './OverwritePluginsModal';

// Local-vs-repo comparison verdicts, from GET /plugin-repositories/updates.
// 'unknown' (manifest lacks a sha256/version/runtime to compare) renders as
// nothing rather than a scary badge.
const STATUS_BADGES = {
  update_available: { text: 'Update available', className: 'text-amber-600 dark:text-amber-400' },
  up_to_date: { text: 'Up to date', className: 'text-[var(--text-muted)]' },
  not_installed: { text: 'Not installed', className: 'text-[var(--text-muted)]' },
};

function StatusBadge({ status }) {
  const badge = STATUS_BADGES[status];
  if (!badge) return null;
  return <span className={`text-xs whitespace-nowrap ${badge.className}`}>{badge.text}</span>;
}

// What the action button on an addon row should say. Keyed off the same
// verdict as the badge next to it, so a row reading "Up to date" can't also
// offer "Install" -- the one thing that button is still able to do there is
// put the repository's copy back over whatever is installed.
const ADDON_ACTION_LABEL = {
  update_available: 'Update',
  up_to_date: 'Reinstall',
  not_installed: 'Install',
};

// Returns { hidden: Set(filename), helpersFor: Map(filename -> [filename]) } --
// the rows to drop, and the resolvable helpers to name on each plugin that
// needs them. A helper a repo entry declares in `depends_on` is part of the
// plugin that needs it, not something to pick: the backend downloads the
// closure either way (expand_with_dependencies in ui/plugin_repositories.py).
// Same rule the Plugins tab already applies to the local pool
// (fileManager/pluginSelection.js).
function resolveRepoDependencies(plugins = []) {
  const known = new Set(plugins.map(p => p.filename));
  const hidden = new Set();
  const helpersFor = new Map();
  plugins.forEach((plugin) => {
    const helpers = (plugin.depends_on || []).filter(
      name => known.has(name) && name !== plugin.filename,
    );
    if (!helpers.length) return;
    helpersFor.set(plugin.filename, helpers);
    helpers.forEach(name => hidden.add(name));
  });
  return { hidden, helpersFor };
}

// One repository's contents: expand/collapse, per-plugin checkboxes (and a
// per-plugin runtime pick for selected entries that declare no runtime), plus
// the addon packages the repository offers for one-click install/update.
function PluginRepositoryCard({ repo, updates, onSync, onDelete, onDownloaded, onAddonInstalled, syncing }) {
  const [expanded, setExpanded] = useState(false);
  const [checked, setChecked] = useState(new Set());
  const [downloading, setDownloading] = useState(false);
  const [installingAddon, setInstallingAddon] = useState(null);
  const [pickedRuntimes, setPickedRuntimes] = useState({});
  const addons = repo.addons || [];
  const pluginStatuses = updates?.plugins || {};
  const addonStatuses = updates?.addons || {};
  const allPlugins = repo.plugins || [];
  const { hidden: helperFilenames, helpersFor } = resolveRepoDependencies(allPlugins);
  // The list the operator actually sees and counts: plugins, not the helper
  // modules some of them are built from.
  const plugins = allPlugins.filter(p => !helperFilenames.has(p.filename));
  // Files a download attempt reported as already present in the local pool
  // ({ code: 'exists' } from the backend) -- offered as an overwrite confirm
  // rather than a dead-end error, since that's the one failure mode with an
  // obvious next step. Shape: { files: [{filename, runtime}] }.
  const [overwriteConfirm, setOverwriteConfirm] = useState(null);
  const { showSuccess, showError } = useNotification();

  const toggle = (filename) => {
    setChecked(prev => {
      const next = new Set(prev);
      if (next.has(filename)) next.delete(filename);
      else next.add(filename);
      return next;
    });
  };

  // `errors` here is always a plain array (never undefined), whether it came
  // back in a 2xx body or from the catch block below -- the two shapes are
  // {downloaded, errors} either way, just carried differently by axios.
  const reportResult = (result) => {
    const downloaded = result.downloaded || [];
    const errors = result.errors || [];
    // Helpers the backend pulled in on its own (`depends_on`), and helpers it
    // left alone because the pool already had this repository's version.
    const autoAdded = result.auto_added || [];
    const skippedHelpers = result.skipped || [];
    if (downloaded.length) {
      const push = result.push || { queued: [], skipped: [] };
      const queuedNames = (push.queued || []).map(h => h.name);
      // Say what came along besides the picks: helpers written, and helpers
      // the pool already had at this version.
      const helpers = autoAdded.filter(f => downloaded.includes(f));
      const extras = [
        helpers.length ? `with ${helpers.join(', ')}` : null,
        skippedHelpers.length ? `${skippedHelpers.join(', ')} already current` : null,
      ].filter(Boolean);
      const what = `Downloaded ${downloaded.length} plugin(s)`
        + (extras.length ? ` (${extras.join('; ')})` : '');
      showSuccess(queuedNames.length
        ? `${what}. Pushing to ${queuedNames.join(', ')}.`
        : `${what}. No active host to push to.`);
      const skipped = push.skipped || [];
      if (skipped.length) {
        showError(`Not pushed to ${skipped.map(h => `${h.name} (${h.reason})`).join(', ')}. Run Check for Updates on those hosts later.`);
      }
    }
    const existing = errors.filter(e => e.code === 'exists');
    const otherErrors = errors.filter(e => e.code !== 'exists');
    if (otherErrors.length) {
      showError(otherErrors.map(e => `${e.filename}: ${e.error}`).join(' · '));
    }
    if (existing.length) {
      setOverwriteConfirm({
        files: existing.map(e => ({ filename: e.filename, runtime: pickedRuntimes[e.filename] ?? null })),
      });
    }
    if (downloaded.length || !existing.length) {
      setChecked(prev => {
        const next = new Set(prev);
        downloaded.forEach(f => next.delete(f));
        otherErrors.forEach(e => next.delete(e.filename));
        return next;
      });
    }
    if (downloaded.length) onDownloaded?.();
  };

  const runDownload = async (filenames, overwrite = false) => {
    setDownloading(true);
    try {
      const runtimes = {};
      filenames.forEach(f => { if (pickedRuntimes[f]) runtimes[f] = pickedRuntimes[f]; });
      const result = await downloadPluginRepositoryPlugins(repo.id, filenames, runtimes, overwrite);
      reportResult(result);
    } catch (err) {
      // A request where every file failed lands here (non-2xx), but the
      // backend still sent {downloaded: [], errors: [...]} as the body --
      // show those reasons instead of a generic message when present.
      if (Array.isArray(err?.errors)) {
        reportResult(err);
      } else {
        showError(err.error?.message || err.message || 'Failed to download plugins.');
      }
    } finally {
      setDownloading(false);
    }
  };

  // Selected plugins that declare no runtime and have no pick yet -- Download
  // stays disabled until each one has a runtime.
  const missingRuntime = plugins
    .filter(p => checked.has(p.filename) && !p.runtime && !pickedRuntimes[p.filename])
    .map(p => p.filename);

  const handleDownload = () => {
    if (checked.size === 0 || missingRuntime.length) return;
    runDownload([...checked]);
  };

  // Unticked files are simply not downloaded; they stay ticked in the list,
  // the same as after Cancel.
  const handleConfirmOverwrite = (filenames) => {
    setOverwriteConfirm(null);
    runDownload(filenames, true);
  };

  const handleInstallAddon = async (addon) => {
    setInstallingAddon(addon.id);
    try {
      const result = await installPluginRepositoryAddon(repo.id, addon.id);
      showSuccess(result.message || `"${addon.id}" installed. Restart QLSM to activate it.`);
      onDownloaded?.();
      // A toast cannot carry the restart button, so the page shows the same
      // banner the Addons page uses once anything here needs one.
      onAddonInstalled?.();
    } catch (err) {
      showError(err.error?.message || err.message || `Failed to install "${addon.id}".`);
    } finally {
      setInstallingAddon(null);
    }
  };

  return (
    <div className="users-table-container">
      <div className="flex items-center justify-between gap-3 p-4">
        <button
          type="button"
          onClick={() => setExpanded(v => !v)}
          className="flex items-center gap-2 min-w-0 text-left"
        >
          <span className={`expand-icon${expanded ? ' is-expanded' : ''}`}>
            <ChevronRight size={16} />
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="users-td-username">{repo.name}</span>
              <span className="text-xs text-[var(--text-muted)]">
                {plugins.length} plugin{plugins.length === 1 ? '' : 's'}
                {addons.length > 0 && ` · ${addons.length} addon${addons.length === 1 ? '' : 's'}`}
              </span>
            </div>
            <div className="font-mono text-xs text-[var(--text-muted)] truncate">{repo.url}</div>
          </div>
        </button>
        <div className="flex items-center gap-3 flex-shrink-0">
          {repo.last_sync_error ? (
            <span className="flex items-center gap-1 text-xs text-red-500 dark:text-[#FF3366]" title={repo.last_sync_error}>
              <AlertTriangle size={14} /> Sync failed
            </span>
          ) : (
            <span className="text-xs text-[var(--text-muted)]">
              Synced {formatDateTime(repo.last_synced_at)}
            </span>
          )}
          <button
            onClick={() => onSync(repo)}
            disabled={syncing}
            className="users-action-btn"
            title="Sync"
          >
            <RefreshCw size={16} strokeWidth={2} className={syncing ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={() => onDelete(repo)}
            className="users-action-btn users-action-btn-delete"
            title="Delete Repository"
          >
            <Trash2 size={16} strokeWidth={2} />
          </button>
        </div>
      </div>

      <div className={`collapsible-section${expanded ? ' is-expanded' : ''}`} inert={!expanded}>
        <div className="collapsible-inner">
        <div className="px-4 pb-4 border-t border-[var(--surface-border)]">
          {plugins.length === 0 && addons.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)] pt-3">
              {repo.last_sync_error ? 'Last sync failed — nothing to show.' : 'Nothing in this repository.'}
            </p>
          ) : (
            <>
              {plugins.length > 0 && (
              <>
              <table className="users-table mt-2">
                <thead>
                  <tr>
                    <th className="users-th" style={{ width: '2rem' }} />
                    <th className="users-th">Plugin</th>
                    <th className="users-th w-40">Runtime</th>
                    <th className="users-th">Status</th>
                    <th className="users-th">Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {plugins.map((plugin) => (
                    <tr key={plugin.filename} className="users-tr">
                      <td className="users-td">
                        <input
                          type="checkbox"
                          checked={checked.has(plugin.filename)}
                          onChange={() => toggle(plugin.filename)}
                          aria-label={plugin.label || plugin.filename}
                          className="h-3.5 w-3.5 rounded border-gray-500 text-blue-500 focus:ring-blue-500"
                        />
                      </td>
                      <td className="users-td">
                        <div>
                          {plugin.label || plugin.filename}
                          {plugin.label && plugin.label !== plugin.filename && (
                            <span className="ml-2 font-mono text-xs text-[var(--text-muted)]">{plugin.filename}</span>
                          )}
                        </div>
                        {plugin.description && (
                          <div className="text-xs text-[var(--text-muted)]">{plugin.description}</div>
                        )}
                        {/* The helpers this plugin drags in. Named rather than
                            hidden entirely, so a download that writes three
                            files into the pool isn't a surprise. */}
                        {helpersFor.has(plugin.filename) && (
                          <div className="text-xs text-[var(--text-muted)] mt-0.5">
                            Includes:{' '}
                            <span className="font-mono">{helpersFor.get(plugin.filename).join(', ')}</span>
                          </div>
                        )}
                      </td>
                      <td className="users-td">
                        {plugin.runtime ? (
                          <span className="font-mono text-xs">{plugin.runtime}</span>
                        ) : (
                          <RuntimePicker
                            value={pickedRuntimes[plugin.filename]}
                            onChange={(value) => setPickedRuntimes(prev => ({ ...prev, [plugin.filename]: value }))}
                            ariaLabel={`Runtime for ${plugin.filename}`}
                          />
                        )}
                      </td>
                      <td className="users-td">
                        <StatusBadge status={pluginStatuses[plugin.filename]} />
                      </td>
                      <td className="users-td">
                        {plugin.version_risk ? (
                          <span className="flex items-center gap-1 text-xs text-red-500 dark:text-[#FF3366]">
                            <AlertTriangle size={13} /> {plugin.version_risk.message}
                          </span>
                        ) : plugin.requires_qlsm_version ? (
                          <span className="text-xs text-[var(--text-muted)]">
                            Requires qlsm &gt;= {plugin.requires_qlsm_version}
                          </span>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="flex items-center gap-3 mt-3">
                <button
                  onClick={handleDownload}
                  disabled={checked.size === 0 || missingRuntime.length > 0 || downloading}
                  className="btn btn-primary"
                >
                  {downloading ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Download size={16} />
                  )}
                  Download selected ({checked.size})
                </button>
                {missingRuntime.length > 0 && (
                  <span className="text-xs text-[var(--text-muted)]">
                    Pick a runtime for {missingRuntime.join(', ')}
                  </span>
                )}
              </div>
              </>
              )}

              {addons.length > 0 && (
                <>
                  <h3 className="text-sm font-medium mt-4">Addons</h3>
                  <p className="text-xs text-[var(--text-muted)] mt-1">
                    Installed into the addon packages volume, like an uploaded .zip.
                    A freshly installed or updated addon needs a QLSM restart to go live.
                  </p>
                  <table className="users-table mt-2">
                    <thead>
                      <tr>
                        <th className="users-th">Addon</th>
                        <th className="users-th">Version</th>
                        <th className="users-th">Status</th>
                        <th className="users-th">Notes</th>
                        <th className="users-th" style={{ width: '6rem' }} />
                      </tr>
                    </thead>
                    <tbody>
                      {addons.map((addon) => {
                        const state = addonStatuses[addon.id];
                        return (
                          <tr key={addon.id} className="users-tr">
                            <td className="users-td">
                              <div>
                                {addon.label || addon.id}
                                {addon.label && addon.label !== addon.id && (
                                  <span className="ml-2 font-mono text-xs text-[var(--text-muted)]">{addon.id}</span>
                                )}
                              </div>
                              {addon.description && (
                                <div className="text-xs text-[var(--text-muted)]">{addon.description}</div>
                              )}
                            </td>
                            <td className="users-td">
                              <span className="font-mono text-xs">
                                {addon.version || '—'}
                                {state?.installed_version && state.installed_version !== addon.version
                                  && ` (installed: ${state.installed_version})`}
                              </span>
                            </td>
                            <td className="users-td">
                              <StatusBadge status={state?.status} />
                            </td>
                            <td className="users-td">
                              {addon.version_risk ? (
                                <span className="flex items-center gap-1 text-xs text-red-500 dark:text-[#FF3366]">
                                  <AlertTriangle size={13} /> {addon.version_risk.message}
                                </span>
                              ) : addon.requires_qlsm_version ? (
                                <span className="text-xs text-[var(--text-muted)]">
                                  Requires qlsm &gt;= {addon.requires_qlsm_version}
                                </span>
                              ) : null}
                            </td>
                            <td className="users-td">
                              <button
                                onClick={() => handleInstallAddon(addon)}
                                disabled={installingAddon !== null}
                                className={`btn ${state?.status === 'up_to_date' ? 'btn-secondary' : 'btn-primary'}`}
                                title={state?.status === 'up_to_date'
                                  ? "Already installed at this version — writes the repository's copy over it again."
                                  : undefined}
                              >
                                {installingAddon === addon.id ? (
                                  <Loader2 size={16} className="animate-spin" />
                                ) : (
                                  <Download size={16} />
                                )}
                                {ADDON_ACTION_LABEL[state?.status] || 'Install'}
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </>
              )}
            </>
          )}
        </div>
        </div>
      </div>

      {overwriteConfirm && (
        <OverwritePluginsModal
          isOpen
          repo={repo}
          files={overwriteConfirm.files}
          onConfirm={handleConfirmOverwrite}
          onClose={() => setOverwriteConfirm(null)}
        />
      )}
    </div>
  );
}

export default PluginRepositoryCard;
