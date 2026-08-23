import { useState, useCallback } from 'react';
import { configureWatchdog } from '../services/api';

export function useHostWatchdog(showSuccess, showError, onSuccess) {
    const [isWatchdogModalOpen, setIsWatchdogModalOpen] = useState(false);
    const [hostForWatchdog, setHostForWatchdog] = useState(null);

    const openWatchdogModal = useCallback((host) => {
        setHostForWatchdog(host);
        setIsWatchdogModalOpen(true);
    }, []);

    const closeWatchdogModal = useCallback(() => {
        setIsWatchdogModalOpen(false);
        setHostForWatchdog(null);
    }, []);

    const handleWatchdogSubmit = useCallback(async (hostId, enabled, config) => {
        if (!hostForWatchdog) return;

        try {
            const response = await configureWatchdog(hostForWatchdog.id, enabled, config);
            showSuccess(response.message || `ql-watchdog updated for host`);
            if (onSuccess) onSuccess();
            closeWatchdogModal();
        } catch (error) {
            console.error("Failed to update ql-watchdog config:", error);
            showError(error.error?.message || error.message || "Failed to update ql-watchdog");
        }
    }, [hostForWatchdog, showSuccess, showError, onSuccess, closeWatchdogModal]);

    return {
        isWatchdogModalOpen,
        hostForWatchdog,
        openWatchdogModal,
        closeWatchdogModal,
        handleWatchdogSubmit
    };
}
