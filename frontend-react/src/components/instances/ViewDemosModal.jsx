import React from 'react';
import { Dialog, DialogBackdrop } from '@headlessui/react';
import { X, RefreshCw, Film, AlertCircle, FolderOpen, Download, Search } from 'lucide-react';
import { listInstanceDemos, downloadInstanceDemo, downloadInstanceDemosBatch } from '../../services/api';

/**
 * Modal for viewing server-side demo files (.dm_91, plus .qlmatch - the
 * native-demo addon's zipped multi-POV match package) recorded by
 * minqlxtended on the remote QLDS instance. Ground truth is the demos/
 * directory on disk (fs_homepath/sv_demoDir) fetched over the same
 * ansible-playbook find pattern used by the MinQLX/server log listers, so
 * the result reflects what the engine actually wrote, not what a plugin or
 * cvar claims.
 */

function formatBytes(bytes) {
    if (!Number.isFinite(bytes)) return '—';
    if (bytes < 1024) return `${bytes} B`;
    const units = ['KB', 'MB', 'GB'];
    let value = bytes / 1024;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
        value /= 1024;
        unitIndex += 1;
    }
    return `${value.toFixed(1)} ${units[unitIndex]}`;
}

function formatMtime(mtime) {
    if (!Number.isFinite(mtime)) return '—';
    return new Date(mtime * 1000).toLocaleString();
}

function triggerBlobDownload(blob, filename) {
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
}

function ViewDemosModal({ isOpen, onClose, instance }) {
    const [demos, setDemos] = React.useState([]);
    const [isLoading, setIsLoading] = React.useState(false);
    const [error, setError] = React.useState(null);
    const [filterText, setFilterText] = React.useState('');
    const [selected, setSelected] = React.useState(() => new Set());
    const [downloadingNames, setDownloadingNames] = React.useState(() => new Set());
    const [isBatchDownloading, setIsBatchDownloading] = React.useState(false);
    const [downloadError, setDownloadError] = React.useState(null);

    const fetchDemos = React.useCallback(async () => {
        if (!instance?.id) return;

        setIsLoading(true);
        setError(null);

        try {
            const data = await listInstanceDemos(instance.id);
            setDemos(data.demos || []);
        } catch (err) {
            console.error('Error listing demos:', err);
            setError(err?.message || err?.error?.message || 'Failed to list demos from the remote server.');
            setDemos([]);
        } finally {
            setIsLoading(false);
        }
    }, [instance?.id]);

    React.useEffect(() => {
        if (isOpen && instance?.id) {
            fetchDemos();
        } else {
            setDemos([]);
            setError(null);
            setFilterText('');
            setSelected(new Set());
            setDownloadingNames(new Set());
            setDownloadError(null);
        }
    }, [isOpen, instance?.id, fetchDemos]);

    const filteredDemos = React.useMemo(() => {
        const needle = filterText.trim().toLowerCase();
        if (!needle) return demos;
        return demos.filter((d) => d.name.toLowerCase().includes(needle));
    }, [demos, filterText]);

    // Drop any selected filenames that no longer exist after a refresh/filter
    // change, so "Download selected (N)" never counts a stale name.
    React.useEffect(() => {
        const visible = new Set(filteredDemos.map((d) => d.name));
        setSelected((prev) => {
            const next = new Set([...prev].filter((name) => visible.has(name)));
            return next.size === prev.size ? prev : next;
        });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [demos]);

    const allFilteredSelected = filteredDemos.length > 0
        && filteredDemos.every((d) => selected.has(d.name));

    const toggleSelectAll = () => {
        setSelected((prev) => {
            if (allFilteredSelected) {
                const next = new Set(prev);
                filteredDemos.forEach((d) => next.delete(d.name));
                return next;
            }
            const next = new Set(prev);
            filteredDemos.forEach((d) => next.add(d.name));
            return next;
        });
    };

    const toggleSelectOne = (name) => {
        setSelected((prev) => {
            const next = new Set(prev);
            if (next.has(name)) next.delete(name);
            else next.add(name);
            return next;
        });
    };

    const downloadOne = async (name) => {
        setDownloadError(null);
        setDownloadingNames((prev) => new Set(prev).add(name));
        try {
            const blob = await downloadInstanceDemo(instance.id, name);
            triggerBlobDownload(blob, name);
        } catch (err) {
            console.error('Error downloading demo:', err);
            setDownloadError(err?.message || err?.error?.message || `Failed to download ${name}.`);
        } finally {
            setDownloadingNames((prev) => {
                const next = new Set(prev);
                next.delete(name);
                return next;
            });
        }
    };

    const downloadSelected = async () => {
        if (selected.size === 0) return;
        setDownloadError(null);
        setIsBatchDownloading(true);
        try {
            const names = [...selected];
            const blob = await downloadInstanceDemosBatch(instance.id, names);
            const safeName = (instance?.name || 'instance').replace(/[^A-Za-z0-9._-]+/g, '-');
            triggerBlobDownload(blob, `${safeName}-demos.zip`);
        } catch (err) {
            console.error('Error batch-downloading demos:', err);
            setDownloadError(err?.message || err?.error?.message || 'Failed to download selected demos.');
        } finally {
            setIsBatchDownloading(false);
        }
    };

    return (
        <Dialog open={isOpen} as="div" className="relative z-50" onClose={onClose}>
            <DialogBackdrop transition className="fixed inset-0 bg-black/60 backdrop-blur-sm transition data-[enter]:ease-out data-[enter]:duration-300 data-[leave]:ease-in data-[leave]:duration-200 data-[closed]:opacity-0" />

            <div className="fixed inset-0 overflow-y-auto">
                <div className="flex min-h-full items-center justify-center p-4 text-center">
                    <Dialog.Panel transition className="view-demos-modal w-full transform overflow-hidden rounded-xl bg-theme-raised border border-theme-strong text-left align-middle shadow-xl transition-all flex flex-col relative transition data-[enter]:ease-out data-[enter]:duration-300 data-[leave]:ease-in data-[leave]:duration-200 data-[closed]:opacity-0 data-[closed]:scale-95" style={{ height: '75vh', maxWidth: '960px' }}>
                        <div className="accent-line-top" />

                        <div className="flex items-center justify-between px-6 py-4 border-b border-theme flex-shrink-0 relative">
                            <div className="flex items-center gap-3">
                                <div className="logs-modal-icon-wrapper">
                                    <div className="logs-modal-icon-glow" />
                                    <Film className="logs-modal-icon" strokeWidth={2.5} />
                                </div>
                                <div>
                                    <Dialog.Title
                                        as="h3"
                                        className="font-display text-lg font-bold tracking-wide text-theme-primary uppercase"
                                    >
                                        Demos
                                    </Dialog.Title>
                                    <p className="font-mono text-xs text-theme-secondary mt-0.5">
                                        {instance?.name} <span className="text-theme-muted">•</span> Port {instance?.port} <span className="text-theme-muted">•</span> demos/ on disk
                                    </p>
                                </div>
                            </div>

                            <div className="flex items-center gap-2">
                                <button
                                    onClick={fetchDemos}
                                    disabled={isLoading}
                                    className="logs-modal-refresh-btn"
                                >
                                    <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} strokeWidth={2} />
                                    <span>Refresh</span>
                                </button>
                                <button
                                    onClick={onClose}
                                    className="logs-modal-close-btn"
                                >
                                    <X className="h-5 w-5" strokeWidth={2} />
                                </button>
                            </div>
                        </div>

                        {!isLoading && !error && demos.length > 0 && (
                            <div className="flex items-center gap-3 px-6 py-3 border-b border-theme flex-shrink-0">
                                <div className="relative flex-1 max-w-xs">
                                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-theme-muted" />
                                    <input
                                        type="text"
                                        value={filterText}
                                        onChange={(e) => setFilterText(e.target.value)}
                                        placeholder="Filter by filename..."
                                        className="w-full pl-8 pr-3 py-1.5 text-sm font-mono rounded-md bg-theme-base border border-theme-strong text-theme-primary placeholder:text-theme-muted focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)]"
                                    />
                                </div>
                                <span className="text-xs font-mono text-theme-muted whitespace-nowrap">
                                    {filteredDemos.length} of {demos.length}
                                </span>
                                <div className="flex-1" />
                                <button
                                    onClick={downloadSelected}
                                    disabled={selected.size === 0 || isBatchDownloading}
                                    className="logs-modal-refresh-btn disabled:opacity-40 disabled:cursor-not-allowed"
                                >
                                    <Download className={`h-4 w-4 ${isBatchDownloading ? 'animate-pulse' : ''}`} strokeWidth={2} />
                                    <span>Download selected {selected.size > 0 ? `(${selected.size})` : ''}</span>
                                </button>
                            </div>
                        )}

                        {downloadError && (
                            <div className="px-6 py-2 flex-shrink-0 text-sm text-center" style={{ color: 'var(--accent-danger)' }}>
                                {downloadError}
                            </div>
                        )}

                        <div className="flex-1 p-4 overflow-auto bg-theme-base">
                            {isLoading ? (
                                <div className="logs-modal-loading-state">
                                    <div className="logs-modal-spinner-wrapper">
                                        <RefreshCw className="logs-modal-spinner" strokeWidth={2} />
                                    </div>
                                    <p className="font-mono text-sm text-theme-secondary uppercase tracking-wide">Listing demos on remote server...</p>
                                </div>
                            ) : error ? (
                                <div className="logs-modal-error-state">
                                    <AlertCircle className="h-10 w-10 mb-4" style={{ color: 'var(--accent-danger)' }} strokeWidth={2} />
                                    <p className="font-display text-lg font-bold uppercase tracking-wide" style={{ color: 'var(--accent-danger)' }}>Error Listing Demos</p>
                                    <p className="text-sm text-theme-secondary mt-2 max-w-md text-center">{error}</p>
                                    <button
                                        onClick={fetchDemos}
                                        className="logs-modal-retry-btn"
                                    >
                                        Try Again
                                    </button>
                                </div>
                            ) : demos.length === 0 ? (
                                <div className="logs-modal-loading-state">
                                    <FolderOpen className="h-10 w-10 mb-4 text-theme-muted" strokeWidth={2} />
                                    <p className="font-display text-base font-bold uppercase tracking-wide text-theme-primary">No demos found</p>
                                    <p className="text-sm text-theme-secondary mt-2 max-w-md text-center">
                                        No .dm_91, .qlmatch or .packer.log files in this instance's demos/ directory. Recording
                                        needs sv_demoRecord or qlx_nativeDemoRecordEnabled set, and a match to arm
                                        the capture — check View MinQLX Logs / View Server Logs for "demo:" lines
                                        after a manual test.
                                    </p>
                                </div>
                            ) : filteredDemos.length === 0 ? (
                                <div className="logs-modal-loading-state">
                                    <Search className="h-10 w-10 mb-4 text-theme-muted" strokeWidth={2} />
                                    <p className="text-sm text-theme-secondary">No demos match "{filterText}".</p>
                                </div>
                            ) : (
                                <table className="w-full text-sm">
                                    <thead>
                                        <tr className="text-left text-theme-muted uppercase text-xs tracking-wide border-b border-theme">
                                            <th className="py-2 pr-2 w-8">
                                                <input
                                                    type="checkbox"
                                                    checked={allFilteredSelected}
                                                    onChange={toggleSelectAll}
                                                    aria-label="Select all demos"
                                                />
                                            </th>
                                            <th className="py-2 pr-4 font-medium">File</th>
                                            <th className="py-2 pr-4 font-medium">Size</th>
                                            <th className="py-2 pr-4 font-medium">Recorded</th>
                                            <th className="py-2 pr-2 w-10" />
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {filteredDemos.map((demo) => (
                                            <tr key={demo.name} className="border-b border-theme/50 hover:bg-black/[0.02] dark:hover:bg-white/[0.02]">
                                                <td className="py-2 pr-2">
                                                    <input
                                                        type="checkbox"
                                                        checked={selected.has(demo.name)}
                                                        onChange={() => toggleSelectOne(demo.name)}
                                                        aria-label={`Select ${demo.name}`}
                                                    />
                                                </td>
                                                <td className="py-2 pr-4 font-mono text-theme-primary break-all">{demo.name}</td>
                                                <td className="py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap">{formatBytes(demo.size)}</td>
                                                <td className="py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap">{formatMtime(demo.mtime)}</td>
                                                <td className="py-2 pr-2">
                                                    <button
                                                        onClick={() => downloadOne(demo.name)}
                                                        disabled={downloadingNames.has(demo.name)}
                                                        title={`Download ${demo.name}`}
                                                        aria-label={`Download ${demo.name}`}
                                                        className="p-1.5 rounded-md text-theme-muted hover:text-theme-primary hover:bg-black/[0.04] dark:hover:bg-white/[0.06] disabled:opacity-40 disabled:cursor-not-allowed"
                                                    >
                                                        <Download className={`h-4 w-4 ${downloadingNames.has(demo.name) ? 'animate-pulse' : ''}`} strokeWidth={2} />
                                                    </button>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            )}
                        </div>
                    </Dialog.Panel>
                </div>
            </div>
        </Dialog>
    );
}

export default ViewDemosModal;
