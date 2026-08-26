import { useState, useCallback } from 'react';
import { configureTelemetryRelay, updateHostStatsHubOverride } from '../services/api';

export function useTelemetryRelay(showSuccess, showError, onSuccess) {
    const [isRelayModalOpen, setIsRelayModalOpen] = useState(false);
    const [hostForRelay, setHostForRelay] = useState(null);

    const openRelayModal = useCallback((host) => {
        setHostForRelay(host);
        setIsRelayModalOpen(true);
    }, []);

    const closeRelayModal = useCallback(() => {
        setIsRelayModalOpen(false);
        setHostForRelay(null);
    }, []);

    const handleRelaySubmit = useCallback(async (hostId, enabled, urlOverride, ingestTokenOverride) => {
        if (!hostForRelay) return;

        try {
            await Promise.all([
                configureTelemetryRelay(hostForRelay.id, enabled),
                updateHostStatsHubOverride(hostForRelay.id, urlOverride, ingestTokenOverride),
            ]);
            showSuccess(`Telemetry relay updated for "${hostForRelay.name}".`);
            if (onSuccess) onSuccess();
            closeRelayModal();
        } catch (error) {
            console.error("Failed to update telemetry relay:", error);
            showError(error.error?.message || error.message || "Failed to update telemetry relay");
        }
    }, [hostForRelay, showSuccess, showError, onSuccess, closeRelayModal]);

    return {
        isRelayModalOpen,
        hostForRelay,
        openRelayModal,
        closeRelayModal,
        handleRelaySubmit,
    };
}
