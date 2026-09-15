import React, { useMemo } from 'react';
import ViewDemosModal from '../../../../../addons/demo-management/ui/ViewDemosModal';
import { addonDownload, addonRequest } from '../../../services/addons';

// Own module, loaded lazily -- see TelemetryRelayAddonModal for why.
function DemosAddonModal({ isOpen, onClose, entity }) {
  const api = useMemo(() => ({
    list: async (instanceId) =>
      addonRequest('demo-management', 'GET', `instances/${instanceId}/demos`),
    downloadOne: async (instanceId, name) => {
      const { blob } = await addonDownload(
        'demo-management', 'GET',
        `instances/${instanceId}/demos/download?filename=${encodeURIComponent(name)}`,
        { fallbackName: name },
      );
      return blob;
    },
    downloadBatch: async (instanceId, names) => {
      const { blob } = await addonDownload(
        'demo-management', 'POST', `instances/${instanceId}/demos/download-batch`,
        { data: { filenames: names }, fallbackName: 'demos.zip' },
      );
      return blob;
    },
  }), []);

  return <ViewDemosModal isOpen={isOpen} onClose={onClose} instance={entity} api={api} />;
}

export default DemosAddonModal;
