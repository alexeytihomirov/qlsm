import React, { useCallback, useMemo } from 'react';
import TelemetryRelayModal from '../../../../../addons/telemetry-relay/ui/TelemetryRelayModal';
import { addonRequest } from '../../../services/addons';
import { publishAddonRuntime } from '../publishAddonRuntime';

// Its own module so ../bundledPanels can load it lazily. Importing it eagerly
// there pulled TelemetryRelayModal -- and everything it imports from
// services/api -- into the import chain of every action menu, which broke 37
// unrelated tests whose services/api mock is partial. Same lesson as uiKit.
function TelemetryRelayAddonModal({ isOpen, onClose, entity }) {
  // TelemetryRelayModal itself is written like a real addon component -- it
  // reads its UI primitives off window.__qlsm.ui rather than importing core
  // internals -- so the runtime has to be published before it renders, not
  // only when a tier-2 bundle loads through AddonComponentHost.
  publishAddonRuntime();

  // Routed through the addon's own endpoints, so opening this from the addon
  // entry exercises the addon's backend, not core's.
  const api = useMemo(() => ({
    getRelay: (hostId) => addonRequest('telemetry-relay', 'GET', `hosts/${hostId}`),
    getStatus: async (hostId) => {
      const data = await addonRequest('telemetry-relay', 'GET', `hosts/${hostId}/status`);
      // The shared modal renders the built-in status shape; the addon's
      // status endpoint is badge-shaped, so map it back here rather than
      // teaching the component two shapes.
      return {
        enabled: Boolean(data?.ok) || (data?.label || '') !== 'Sidecar disabled',
        reachable: Boolean(data?.ok),
        error: data?.ok ? null : data?.label,
        routed_instances: data?.routed_instances || [],
      };
    },
    getOverride: async (hostId) => {
      const data = await addonRequest('telemetry-relay', 'GET', `hosts/${hostId}`);
      return {
        url_override: data?.url_override || null,
        ingest_token_override: data?.ingest_token_override || null,
        effective_url: data?.url_override || null,
      };
    },
  }), []);

  const handleSubmit = useCallback(async (hostId, enabled, urlOverride, tokenOverride) => {
    await addonRequest('telemetry-relay', 'PUT', `hosts/${hostId}`, {
      data: {
        enabled,
        url_override: urlOverride,
        ingest_token_override: tokenOverride,
      },
    });
  }, []);

  return (
    <TelemetryRelayModal isOpen={isOpen} onClose={onClose} onSubmit={handleSubmit}
                         host={entity} api={api} />
  );
}

export default TelemetryRelayAddonModal;
