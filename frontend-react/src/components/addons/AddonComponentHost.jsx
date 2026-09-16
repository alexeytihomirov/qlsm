import React, { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import * as addonUi from './uiKit';
import { addonAssetUrl, addonRequest } from '../../services/addons';
import { ensureAddonCss } from './addonCss';
import { publishAddonRuntime } from './publishAddonRuntime';

/**
 * Tier-2: mounts an addon's own pre-built component (spec section 5.2).
 *
 * The bundle is built by the addon's author, shipped inside the addon
 * package, and served by core from /api/addons/<id>/ui/. It is loaded with a
 * dynamic import() at the moment the mount point is rendered -- never at app
 * start, so an addon nobody opens costs nothing.
 *
 * The bundle must NOT contain its own React. Core publishes React and the
 * shared UI kit on window.__qlsm so an addon's build can mark them external;
 * two React copies on one page break hooks in ways that are miserable to
 * debug. Publishing happens here rather than in main.jsx so the globals only
 * exist once an addon actually needs them.
 */
function AddonComponentHost({ addon, entry, scope, scopeId }) {
  const [Component, setComponent] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    publishAddonRuntime();
    ensureAddonCss(addon.id, entry.component);
    const url = addonAssetUrl(addon.id, entry.component);

    import(/* @vite-ignore */ url)
      .then((module) => {
        if (cancelled) return;
        const exported = module?.default || module?.[entry.export || 'Panel'];
        if (typeof exported !== 'function') {
          setError('The component bundle has no default export.');
          return;
        }
        // Wrapped in an object so React treats it as a value, not an updater.
        setComponent(() => exported);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message || 'Failed to load component');
      });

    return () => { cancelled = true; };
  }, [addon.id, entry.component, entry.export]);

  if (error) {
    return (
      <p className="py-4 text-sm" style={{ color: 'var(--accent-danger)' }}>
        Could not load this addon's component: {error}
      </p>
    );
  }

  if (!Component) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm text-theme-muted">
        <Loader2 size={15} className="animate-spin" /> Loading component...
      </div>
    );
  }

  // The context an addon component receives. `api` is pre-pinned to the
  // addon's own prefix, so the component cannot call a core endpoint through
  // the handle it is given.
  const ctx = {
    addonId: addon.id,
    scope: { kind: scope, id: scopeId },
    api: (method, path, options) => addonRequest(addon.id, method, path, options),
    ui: addonUi,
    manifest: addon,
  };

  return <Component ctx={ctx} />;
}

export default AddonComponentHost;
