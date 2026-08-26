import React, { useState, useEffect, useCallback } from 'react';
import { Dialog, DialogBackdrop } from '@headlessui/react';
import { Radio, X, RefreshCw, CheckCircle2, XCircle, Loader2 } from 'lucide-react';
import {
    getTelemetryRelay,
    getTelemetryRelayStatus,
    getHostStatsHubOverride,
} from '../../services/api';

function StatusBadge({ status, statusLoading }) {
    if (statusLoading) {
        return (
            <span className="inline-flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
                <Loader2 size={13} className="animate-spin" /> Checking...
            </span>
        );
    }
    if (!status || !status.enabled) {
        return <span className="text-xs text-[var(--text-muted)]">Sidecar disabled</span>;
    }
    if (status.reachable) {
        return (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-400">
                <CheckCircle2 size={13} /> Reachable
            </span>
        );
    }
    return (
        <span className="inline-flex items-center gap-1.5 text-xs font-medium" style={{ color: 'var(--accent-danger)' }}>
            <XCircle size={13} /> {status.error || 'Unreachable'}
        </span>
    );
}

function TelemetryRelayModal({ isOpen, onClose, onSubmit, host }) {
    const [enabled, setEnabled] = useState(false);
    const [urlOverride, setUrlOverride] = useState('');
    const [tokenOverride, setTokenOverride] = useState('');
    const [effectiveUrl, setEffectiveUrl] = useState(null);
    const [status, setStatus] = useState(null);
    const [statusLoading, setStatusLoading] = useState(false);
    const [loaded, setLoaded] = useState(false);

    const refreshStatus = useCallback(async (hostId) => {
        setStatusLoading(true);
        try {
            const data = await getTelemetryRelayStatus(hostId);
            setStatus(data);
        } catch {
            setStatus(null);
        } finally {
            setStatusLoading(false);
        }
    }, []);

    useEffect(() => {
        if (!isOpen || !host) return;
        setLoaded(false);
        let cancelled = false;
        (async () => {
            try {
                const [relay, override] = await Promise.all([
                    getTelemetryRelay(host.id),
                    getHostStatsHubOverride(host.id),
                ]);
                if (cancelled) return;
                setEnabled(!!relay.enabled);
                setUrlOverride(override.url_override || '');
                setTokenOverride(override.ingest_token_override || '');
                setEffectiveUrl(override.effective_url || null);
            } finally {
                if (!cancelled) setLoaded(true);
            }
        })();
        refreshStatus(host.id);
        return () => { cancelled = true; };
    }, [isOpen, host, refreshStatus]);

    const handleClose = () => onClose();

    const handleSubmit = (e) => {
        e.preventDefault();
        onSubmit(host?.id, enabled, urlOverride.trim(), tokenOverride.trim());
        handleClose();
    };

    const routedInstances = status?.routed_instances || [];

    return (
        <Dialog open={isOpen} as="div" className="relative z-50" onClose={handleClose}>
            <DialogBackdrop transition className="modal-backdrop fixed inset-0 transition data-[enter]:ease-out data-[enter]:duration-300 data-[leave]:ease-in data-[leave]:duration-200 data-[closed]:opacity-0" />

            <div className="fixed inset-0 overflow-y-auto scrollbar-thick">
                <div className="flex min-h-full items-center justify-center p-4">
                    <Dialog.Panel transition className="modal-panel w-full max-w-[560px] transform p-6 text-left align-middle transition-all transition data-[enter]:ease-out data-[enter]:duration-300 data-[leave]:ease-in data-[leave]:duration-200 data-[closed]:opacity-0 data-[closed]:translate-y-4 data-[closed]:scale-95">
                        <div className="accent-line-top" />

                        <Dialog.Title as="h3" className="relative z-10 flex items-center gap-3 mb-6">
                            <span className="status-pulse status-pulse-active" />
                            <Radio size={18} className="text-[var(--accent-primary)]" />
                            <span className="font-display text-base font-semibold tracking-wider uppercase text-[var(--text-primary)]">
                                Telemetry Relay
                            </span>
                            <button type="button" onClick={handleClose} className="ml-auto logs-modal-close-btn">
                                <X size={18} />
                            </button>
                        </Dialog.Title>

                        <form onSubmit={handleSubmit}>
                            <div className="space-y-6">
                                <p className="text-sm text-[var(--text-muted)]">
                                    ql-telemetry-relay sidecar on <strong>{host?.name}</strong> forwards instance
                                    telemetry to ql-stats-hub. Instances only talk to this local relay - the
                                    stats-hub URL/ingest token live here, not on any instance.
                                </p>

                                <div className="flex items-center justify-between p-3 rounded-lg border border-[var(--surface-border)] bg-[var(--surface-raised)]">
                                    <span className="text-sm font-medium text-[var(--text-primary)]">Sidecar Enabled</span>
                                    <button
                                        type="button"
                                        onClick={() => setEnabled((v) => !v)}
                                        className="neu-toggle"
                                        aria-pressed={enabled}
                                    >
                                        <span className="sr-only">Toggle telemetry relay</span>
                                        <span className={`neu-toggle__track ${enabled ? 'neu-toggle__track--on' : 'neu-toggle__track--off'}`}>
                                            <span className={`neu-toggle__knob ${enabled ? 'neu-toggle__knob--on' : 'neu-toggle__knob--off'}`} />
                                        </span>
                                    </button>
                                </div>

                                <div className="p-3 rounded-lg border border-[var(--surface-border)] bg-[var(--surface-raised)] space-y-2">
                                    <div className="flex items-center justify-between">
                                        <span className="text-sm font-medium text-[var(--text-primary)]">Status</span>
                                        <div className="flex items-center gap-3">
                                            <StatusBadge status={status} statusLoading={statusLoading} />
                                            <button
                                                type="button"
                                                onClick={() => host && refreshStatus(host.id)}
                                                disabled={statusLoading}
                                                className="text-[var(--text-muted)] hover:text-[var(--text-primary)] disabled:opacity-40"
                                                title="Refresh status"
                                            >
                                                <RefreshCw size={13} className={statusLoading ? 'animate-spin' : ''} />
                                            </button>
                                        </div>
                                    </div>
                                    <div className="text-xs text-[var(--text-muted)]">
                                        {routedInstances.length === 0 && 'No instances routed through this relay yet.'}
                                        {routedInstances.length > 0 && (
                                            <ul className="space-y-0.5">
                                                {routedInstances.map((inst) => (
                                                    <li key={inst.id} className="flex items-center justify-between">
                                                        <span>{inst.name}</span>
                                                        <span className="font-mono">#{inst.server_id}</span>
                                                    </li>
                                                ))}
                                            </ul>
                                        )}
                                    </div>
                                </div>

                                <div className="space-y-4 border-t border-[var(--surface-border)] pt-5">
                                    <div>
                                        <label htmlFor="relay-url-override" className="label-tech mb-1.5 block">
                                            Stats Hub URL Override
                                        </label>
                                        <input
                                            type="text"
                                            id="relay-url-override"
                                            value={urlOverride}
                                            onChange={(e) => setUrlOverride(e.target.value)}
                                            placeholder={effectiveUrl ? `Inherits global: ${effectiveUrl}` : 'Not configured globally either'}
                                            className="input-base w-full font-mono text-sm"
                                            disabled={!loaded}
                                        />
                                    </div>
                                    <div>
                                        <label htmlFor="relay-token-override" className="label-tech mb-1.5 block">
                                            Ingest Token Override
                                        </label>
                                        <input
                                            type="text"
                                            id="relay-token-override"
                                            value={tokenOverride}
                                            onChange={(e) => setTokenOverride(e.target.value)}
                                            placeholder="Blank = inherit the global ingest token"
                                            className="input-base w-full font-mono text-sm"
                                            disabled={!loaded}
                                        />
                                    </div>
                                    <p className="text-xs text-[var(--text-muted)]">
                                        Leave both blank to use the cluster-wide stats-hub target from Settings.
                                        Set either to point this host at a different stats-hub instance.
                                    </p>
                                </div>
                            </div>

                            <div className="flex justify-end items-center gap-3 mt-8 pt-4 border-t border-[var(--surface-border)]">
                                <button type="button" onClick={handleClose} className="btn btn-secondary">
                                    Cancel
                                </button>
                                <button type="submit" className="btn btn-primary" disabled={!loaded}>
                                    Save
                                </button>
                            </div>
                        </form>
                    </Dialog.Panel>
                </div>
            </div>
        </Dialog>
    );
}

export default TelemetryRelayModal;
