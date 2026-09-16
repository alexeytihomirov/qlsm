import React from 'react';
import * as addonUi from './uiKit';

/**
 * Publishes React and the shared UI kit on window.__qlsm so any addon
 * component -- a tier-2 pre-built bundle (AddonComponentHost) or a bundled
 * addon's own component compiled straight into core (bundledPanels) -- can
 * read them off the runtime instead of importing core internals directly.
 *
 * Idempotent and cheap (three property assignments), so it is safe to call
 * on every render path that might mount an addon component rather than only
 * once at app start.
 */
export function publishAddonRuntime() {
  if (typeof window === 'undefined') return;
  if (!window.__qlsm) window.__qlsm = {};
  window.__qlsm.react = React;
  window.__qlsm.ui = addonUi;
  window.__qlsm.version = 1;
}

export default publishAddonRuntime;
