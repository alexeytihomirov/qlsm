import { useState, useCallback } from 'react';
import { updateCommonPlugins } from '../services/api';

export function useUpdateCommonPlugins(showSuccess, showError, onSuccess) {
    const [isPluginsModalOpen, setIsPluginsModalOpen] = useState(false);
    const [hostForPluginsUpdate, setHostForPluginsUpdate] = useState(null);

    const openPluginsModal = useCallback((host) => {
        setHostForPluginsUpdate(host);
        setIsPluginsModalOpen(true);
    }, []);

    const closePluginsModal = useCallback(() => {
        setIsPluginsModalOpen(false);
    }, []);

    const handlePluginsUpdateSubmit = useCallback(async (restartInstanceIds) => {
        if (!hostForPluginsUpdate) return;

        try {
            const response = await updateCommonPlugins(hostForPluginsUpdate.id, {
                restart_instances: restartInstanceIds
            });
            showSuccess(response.message || 'Plugin pool update task queued');
            if (onSuccess) onSuccess();
            closePluginsModal();
        } catch (error) {
            console.error("Failed to update common plugins:", error);
            showError(error.error?.message || error.message || "Failed to update common plugins");
        }
    }, [hostForPluginsUpdate, showSuccess, showError, onSuccess, closePluginsModal]);

    return {
        isPluginsModalOpen,
        hostForPluginsUpdate,
        openPluginsModal,
        closePluginsModal,
        handlePluginsUpdateSubmit
    };
}
