import { useState } from 'react';

/**
 * Modal state for viewing a single host's own lifecycle logs (Terraform/Ansible
 * output captured via append_log), opened from the host actions menu.
 */
export function useHostLogsModal() {
    const [isHostLogsModalOpen, setIsHostLogsModalOpen] = useState(false);
    const [hostForLogs, setHostForLogs] = useState(null);

    const openHostLogs = (host) => {
        setHostForLogs(host);
        setIsHostLogsModalOpen(true);
    };

    const closeHostLogs = () => {
        setIsHostLogsModalOpen(false);
        setHostForLogs(null);
    };

    return { hostForLogs, isHostLogsModalOpen, openHostLogs, closeHostLogs };
}
