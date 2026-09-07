import { useState } from 'react';

/**
 * Shared hook for view demos modal state management.
 * @returns {{
 *   selectedInstanceForDemos: object|null,
 *   isViewDemosModalOpen: boolean,
 *   openViewDemos: (instance: object) => void,
 *   closeViewDemos: () => void,
 * }}
 */
export function useViewDemos() {
    const [isViewDemosModalOpen, setIsViewDemosModalOpen] = useState(false);
    const [selectedInstanceForDemos, setSelectedInstanceForDemos] = useState(null);

    const openViewDemos = (instance) => {
        setSelectedInstanceForDemos(instance);
        setIsViewDemosModalOpen(true);
    };

    const closeViewDemos = () => {
        setIsViewDemosModalOpen(false);
        setSelectedInstanceForDemos(null);
    };

    return { selectedInstanceForDemos, isViewDemosModalOpen, openViewDemos, closeViewDemos };
}
