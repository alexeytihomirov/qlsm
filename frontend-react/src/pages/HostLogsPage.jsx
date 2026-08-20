import React, { Fragment, useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Listbox, Transition } from '@headlessui/react';
import { ChevronDown, Check, FileText, Maximize, RefreshCw, AlertCircle, Server } from 'lucide-react';
import CodeMirrorEditor from '../components/CodeMirrorEditor';
import ExpandedEditorModal from '../components/ExpandedEditorModal';
import { logLanguage } from '../utils/logLanguage';
import { useHosts } from '../hooks/useHosts';
import { getHostLogs } from '../services/api';

/**
 * Standalone page for viewing a host's own lifecycle logs (Terraform/Ansible
 * output captured via append_log during provisioning, setup, restart, etc).
 * Not to be confused with the per-instance remote QLDS server log viewer
 * (ViewLogsModal), which fetches from the target host over SSH.
 */
function HostLogsPage() {
    const { hostId: hostIdParam } = useParams();
    const navigate = useNavigate();
    const { sortedHosts: hosts, loading: hostsLoading } = useHosts();

    const selectedHostId = hostIdParam ? Number(hostIdParam) : null;
    const selectedHost = hosts.find((h) => h.id === selectedHostId) || null;

    const [logs, setLogs] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const [isExpandedEditorOpen, setIsExpandedEditorOpen] = useState(false);

    const fetchLogs = useCallback(async () => {
        if (!selectedHostId) return;
        setIsLoading(true);
        setError(null);
        try {
            const data = await getHostLogs(selectedHostId);
            setLogs(data.logs || '-- No entries --');
        } catch (err) {
            console.error('Error fetching host logs:', err);
            setError(err?.message || err?.error?.message || 'Failed to fetch host logs.');
            setLogs('');
        } finally {
            setIsLoading(false);
        }
    }, [selectedHostId]);

    useEffect(() => {
        fetchLogs();
    }, [fetchLogs]);

    const handleSelectHost = (id) => {
        navigate(`/host-logs/${id}`);
    };

    return (
        <div className="users-page" style={{ maxWidth: '1200px' }}>
            <div className="users-page-header">
                <div className="users-page-title-row">
                    <div className="users-page-title-wrapper">
                        <FileText className="users-page-title-icon" strokeWidth={2} />
                        <h1 className="users-page-title">Host Logs</h1>
                    </div>
                </div>
            </div>

            <div className="flex items-center gap-3 mb-4">
                <div className="relative w-72">
                    <Listbox value={selectedHostId} onChange={handleSelectHost} disabled={hostsLoading || hosts.length === 0}>
                        <div className="relative">
                            <Listbox.Button className="relative w-full cursor-default rounded-lg bg-theme-base/50 py-2 pl-3 pr-10 text-left shadow-md focus:outline-none sm:text-sm border border-white/10 disabled:opacity-50">
                                <span className="flex items-center gap-2 truncate text-theme-primary">
                                    <Server className="h-4 w-4 text-theme-muted flex-shrink-0" />
                                    {selectedHost ? selectedHost.name : (hostsLoading ? 'Loading hosts...' : 'Select a host')}
                                </span>
                                <span className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2">
                                    <ChevronDown className="h-4 w-4 text-gray-400" aria-hidden="true" />
                                </span>
                            </Listbox.Button>
                            <Transition
                                as={Fragment}
                                leave="transition ease-in duration-100"
                                leaveFrom="opacity-100"
                                leaveTo="opacity-0"
                            >
                                <Listbox.Options className="absolute mt-1 max-h-72 w-full overflow-auto rounded-md bg-theme-bg/95 backdrop-blur-md py-1 text-base shadow-lg ring-1 ring-black/5 focus:outline-none sm:text-sm z-50 border border-white/10 scrollbar-thick">
                                    {hosts.map((host) => (
                                        <Listbox.Option
                                            key={host.id}
                                            value={host.id}
                                            className={({ active }) =>
                                                `relative cursor-default select-none py-2 pl-10 pr-4 ${active ? 'bg-theme-secondary/20 text-theme-primary' : 'text-theme-secondary'
                                                }`
                                            }
                                        >
                                            {({ selected }) => (
                                                <>
                                                    <span className={`block truncate ${selected ? 'font-medium text-theme-primary' : 'font-normal'}`}>
                                                        {host.name}
                                                    </span>
                                                    <span className="absolute inset-y-0 left-0 flex items-center pl-3">
                                                        {selected && <Check className="h-4 w-4 text-amber-500" aria-hidden="true" />}
                                                    </span>
                                                </>
                                            )}
                                        </Listbox.Option>
                                    ))}
                                </Listbox.Options>
                            </Transition>
                        </div>
                    </Listbox>
                </div>

                {selectedHostId && (
                    <button
                        onClick={fetchLogs}
                        disabled={isLoading}
                        className="logs-modal-refresh-btn"
                    >
                        <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} strokeWidth={2} />
                        <span>Refresh</span>
                    </button>
                )}
            </div>

            {!selectedHostId ? (
                <div className="logs-modal-loading-state">
                    <p className="font-mono text-sm text-theme-secondary uppercase tracking-wide">Select a host above to view its logs.</p>
                </div>
            ) : isLoading ? (
                <div className="logs-modal-loading-state">
                    <div className="logs-modal-spinner-wrapper">
                        <RefreshCw className="logs-modal-spinner" strokeWidth={2} />
                    </div>
                    <p className="font-mono text-sm text-theme-secondary uppercase tracking-wide">Fetching host logs...</p>
                </div>
            ) : error ? (
                <div className="logs-modal-error-state">
                    <AlertCircle className="h-10 w-10 mb-4" style={{ color: 'var(--accent-danger)' }} strokeWidth={2} />
                    <p className="font-display text-lg font-bold uppercase tracking-wide" style={{ color: 'var(--accent-danger)' }}>Error Fetching Logs</p>
                    <p className="text-sm text-theme-secondary mt-2 max-w-md text-center">{error}</p>
                    <button
                        onClick={fetchLogs}
                        className="logs-modal-retry-btn"
                    >
                        Try Again
                    </button>
                </div>
            ) : (
                <div className="flex flex-col" style={{ height: '65vh' }}>
                    <div className="flex items-center justify-end gap-2 mb-3 px-2">
                        <button
                            type="button"
                            onClick={() => setIsExpandedEditorOpen(true)}
                            className="p-1 hover:bg-[var(--surface-elevated)] rounded transition-colors text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                            title="Expand logs editor"
                            aria-label="Expand logs editor"
                        >
                            <Maximize size={14} />
                        </button>
                    </div>
                    <div className="flex-1 border-2 border-theme-strong rounded-lg overflow-hidden logs-modal-editor-container">
                        <CodeMirrorEditor
                            value={logs}
                            onChange={() => { }}
                            language={logLanguage}
                            height="100%"
                            readOnly={true}
                        />
                    </div>
                </div>
            )}

            {isExpandedEditorOpen && (
                <ExpandedEditorModal
                    isOpen={isExpandedEditorOpen}
                    onClose={() => setIsExpandedEditorOpen(false)}
                    fileName={`${selectedHost?.name || 'Host'} Logs`}
                    fileContent={logs}
                    language={logLanguage}
                    readOnly={true}
                    titlePrefix="Viewing:"
                />
            )}
        </div>
    );
}

export default HostLogsPage;
