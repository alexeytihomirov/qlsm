import React from 'react';
import AddonComponentHost from './AddonComponentHost';
import AddonErrorBoundary from './AddonErrorBoundary';
import AddonFormPanel from './AddonFormPanel';
import AddonTablePanel from './AddonTablePanel';

/**
 * Renders whatever a mount point asked for -- a declarative panel (tier 1) or
 * the addon's own component (tier 2). Every mount point in QLSM goes through
 * this one component, which is what keeps "four places, one contract" true.
 */
function AddonPanel({ addon, entry, panel, scope, scopeId }) {
  let body;

  if (entry?.component) {
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
