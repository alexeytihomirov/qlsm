import React from 'react';
import AddonComponentHost from './AddonComponentHost';
import AddonErrorBoundary from './AddonErrorBoundary';
import AddonFormPanel from './AddonFormPanel';
import AddonTablePanel from './AddonTablePanel';
import { BUNDLED_PREFIX } from './addonEntry';

/**
 * Renders whatever a mount point asked for -- a declarative panel (tier 1) or
 * the addon's own component (tier 2). Every mount point in QLSM goes through
 * this one component, which is what keeps "four places, one contract" true.
 */
function AddonPanel({ addon, entry, panel, scope, scopeId }) {
  let body;

  if (entry?.component?.startsWith(BUNDLED_PREFIX)) {
    // Named a component compiled into QLSM's own build. Nothing does that any
    // more -- QLSM ships no feature addon in its image, so there is no such
    // component to borrow. Say so instead of rendering an empty panel.
    body = (
      <p className="py-4 text-sm text-theme-muted">
        This addon asks for a built-in component ({entry.component}) that this QLSM does not
        provide. Ship the component with the addon instead (see addons/README.md, "tier 2").
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
