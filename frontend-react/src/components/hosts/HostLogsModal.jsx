import React, { useState, useEffect, useCallback } from 'react';
import { Dialog, DialogBackdrop } from '@headlessui/react';
import { X, RefreshCw, Terminal, AlertCircle, Maximize } from 'lucide-react';
import CodeMirrorEditor from '../CodeMirrorEditor';
import ExpandedEditorModal from '../ExpandedEditorModal';
import { logLanguage } from '../../utils/logLanguage';
import { getHostLogs } from '../../services/api';

/**
 * Popup for a single host's own lifecycle logs (Terraform/Ansible output
 * captured via append_log during provisioning, setup, restart, etc), opened
 * from the host actions menu. The full standalone /host-logs page (with the
 * host picker) covers browsing logs across hosts; this modal is scoped to
 * whichever host the operator was already looking at.
 */
function HostLogsModal({ isOpen, onClose, host }) {
    const [logs, setLogs] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const [isExpandedEditorOpen, setIsExpandedEditorOpen] = useState(false);

    const fetchLogs = useCallback(async () => {
        if (!host?.id) return;
        setIsLoading(true);
        setError(null);
        try {
            const data = await getHostLogs(host.id);
            setLogs(data.logs || '-- No entries --');
        } catch (err) {
            console.error('Error fetching host logs:', err);
            setError(err?.message || err?.error?.message || 'Failed to fetch host logs.');
            setLogs('');
        } finally {
            setIsLoading(false);
        }
    }, [host?.id]);

    useEffect(() => {
        if (isOpen && host?.id) {
            fetchLogs();
        } else if (!isOpen) {
            setLogs('');
            setError(null);
            setIsExpandedEditorOpen(false);
        }
    }, [isOpen, host?.id, fetchLogs]);

    // Scroll to bottom of logs after load
    useEffect(() => {
        if (!isLoading && logs) {
            const timer = setTimeout(() => {
                const cmEditor = document.querySelector('.host-logs-modal .cm-editor .cm-scroller');
                if (cmEditor) {
                    cmEditor.scrollTop = cmEditor.scrollHeight;
                }
            }, 100);
            return () => clearTimeout(timer);
        }
    }, [logs, isLoading]);

    return (
        <>
            <Dialog open={isOpen} as="div" className="relative z-50" onClose={onClose}>
                <DialogBackdrop transition className="fixed inset-0 bg-black/60 backdrop-blur-sm transition data-[enter]:ease-out data-[enter]:duration-300 data-[leave]:ease-in data-[leave]:duration-200 data-[closed]:opacity-0" />

                <div className="fixed inset-0 overflow-y-auto">
                    <div className="flex min-h-full items-center justify-center p-4 text-center">
                        <Dialog.Panel transition className="host-logs-modal w-full transform overflow-hidden rounded-xl bg-theme-raised border border-theme-strong text-left align-middle shadow-xl transition-all flex flex-col relative transition data-[enter]:ease-out data-[enter]:duration-300 data-[leave]:ease-in data-[leave]:duration-200 data-[closed]:opacity-0 data-[closed]:scale-95" style={{ height: '80vh', maxWidth: '1400px' }}>
                            <div className="accent-line-top" />

                            {/* Header */}
                            <div className="flex items-center justify-between px-6 py-4 border-b border-theme flex-shrink-0 relative">
                                <div className="flex items-center gap-3">
                                    <div className="logs-modal-icon-wrapper">
                                        <div className="logs-modal-icon-glow" />
                                        <Terminal className="logs-modal-icon" strokeWidth={2.5} />
                                    </div>
                                    <Dialog.Title
                                        as="h3"
                                        className="font-display text-lg font-bold tracking-wide text-theme-primary uppercase"
                                    >
                                        {host?.name || 'Host'}
                                    </Dialog.Title>
                                </div>
                                <div className="flex items-center gap-2">
                                    <button
                                        onClick={fetchLogs}
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

                            {/* Content */}
                            <div className="flex-1 p-4 overflow-hidden bg-theme-base">
                                {isLoading ? (
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
                                    <div className="h-full flex flex-col">
                                        <div className="flex items-center justify-between gap-2 mb-3 px-2">
                                            <div className="flex items-center gap-2">
                                                <div className="logs-modal-tip-icon">
                                                    <Terminal className="h-3 w-3" strokeWidth={2.5} />
                                                </div>
                                                <p className="font-mono text-xs text-theme-secondary">
                                                    Press <kbd className="logs-modal-kbd">Ctrl+F</kbd> to search
                                                </p>
                                            </div>
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
                            </div>
                        </Dialog.Panel>
                    </div>
                </div>
            </Dialog>

            {isExpandedEditorOpen && (
                <ExpandedEditorModal
                    isOpen={isExpandedEditorOpen}
                    onClose={() => setIsExpandedEditorOpen(false)}
                    fileName={`${host?.name || 'Host'} Logs`}
                    fileContent={logs}
                    language={logLanguage}
                    readOnly={true}
                    titlePrefix="Viewing:"
                />
            )}
        </>
    );
}

export default HostLogsModal;
