import React, { Suspense } from 'react';
import AddonComponentHost from './AddonComponentHost';
import AddonErrorBoundary from './AddonErrorBoundary';
import AddonFormPanel from './AddonFormPanel';
import AddonTablePanel from './AddonTablePanel';
import { BUNDLED_PREFIX, resolveBundledComponent } from './bundledPanels';

/**
 * Renders whatever a mount point asked for -- a declarative panel (tier 1) or
 * the addon's own component (tier 2). Every mount point in QLSM goes through
 * this one component, which is what keeps "four places, one contract" true.
 */
function AddonPanel({ addon, entry, panel, scope, scopeId }) {
  let body;

  const Bundled = resolveBundledComponent(addon, entry);
  if (Bundled) {
    // A component core already builds. Mounted as a panel body here (the
    // whole-dialog case is handled by useAddonMenu, which skips this shell).
    body = (
      <Suspense fallback={<p className="py-4 text-sm text-theme-muted">Loading...</p>}>
        <Bundled scope={scope} scopeId={scopeId} />
      </Suspense>
    );
  } else if (entry?.component?.startsWith(BUNDLED_PREFIX)) {
    // Named a bundled component that this core does not have -- almost always
    // an installed addon trying to borrow core's build, which it cannot.
    body = (
      <p className="py-4 text-sm text-theme-muted">
        This addon asks for a built-in component ({entry.component}) that this QLSM does not
        provide. Only addons shipped with QLSM can reference one.
      </p>
    );
  } else if (entry?.component) {
    body = <AddonComponentHost addon={addon} entry={entry} scope={scope} scopeId={scopeId} />;
  } else if (panel?.kind === 'form') {
    body = <AddonFormPanel addon={addon} panel={panel} scope={scope} scopeId={scopeId} />;
  } else if (panel?.kind === 'table') {
    body = <AddonTablePanel addon={addon} panel={panel} scope={scope} scopeId={scopeId} />;
  } else {
    // Reachable when an addon declares a panel kind this core predates. Say
    // so plainly instead of rendering an empty box the operator has to guess at.
    body = (
      <p className="py-4 text-sm text-theme-muted">
        This addon asked for a "{panel?.kind || 'unknown'}" panel, which this version of QLSM
        does not know how to render. Updating QLSM may add it.
      </p>
    );
  }

  return <AddonErrorBoundary addonId={addon?.id}>{body}</AddonErrorBoundary>;
}

export default AddonPanel;
