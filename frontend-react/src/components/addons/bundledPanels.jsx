import { lazy } from 'react';

/**
 * Components that bundled addons mount instead of a declarative panel.
 *
 * Why this exists: the declarative `form`/`table` panels are fine for a new
 * addon, but they are a visible downgrade for a feature that already has a
 * purpose-built screen. The Demos modal alone has a filename filter, a
 * "N of M" counter, a refresh button, a header subtitle, monospace filenames
 * and a Recorded column that no generic table reproduces by accident.
 *
 * So a migration addon mounts the *same component the built-in menu mounts*,
 * with its data source swapped for the addon's endpoints. Parity is then true
 * by construction rather than by careful copying, and stays true when either
 * side changes.
 *
 * Only `bundled` addons may use this -- an addon installed from a .zip cannot
 * reach into core's build and must ship a pre-built component instead (see
 * AddonComponentHost). resolveBundledComponent enforces that.
 *
 * **Everything here is lazy on purpose.** This module sits in the import
 * chain of every host and instance action menu. Importing the wrappers
 * eagerly dragged TelemetryRelayModal, ViewDemosModal and all of services/api
 * into pages that only partially mock it, breaking 37 unrelated tests. Same
 * lesson as uiKit and CodeMirror: nothing heavy at module scope on this path.
 */
const LOADERS = {
  'telemetry-relay:relay-modal': () => import('./bundled/TelemetryRelayAddonModal'),
  'demo-management:demos-modal': () => import('./bundled/DemosAddonModal'),
};

// lazy() components are created once, at module load, so React sees a stable
// type across renders -- creating them inside resolve() would remount the
// dialog on every parent render.
export const BUNDLED_ADDON_COMPONENTS = Object.fromEntries(
  Object.entries(LOADERS).map(([key, loader]) => [key, lazy(loader)]),
);

export const BUNDLED_PREFIX = 'bundled:';

/** Component for a manifest entry's `component`, or null. */
export function resolveBundledComponent(addon, entry) {
  const spec = entry?.component;
  if (typeof spec !== 'string' || !spec.startsWith(BUNDLED_PREFIX)) return null;
  if (addon?.source !== 'bundled') return null;
  return BUNDLED_ADDON_COMPONENTS[`${addon.id}:${spec.slice(BUNDLED_PREFIX.length)}`] || null;
}

/** True when the entry renders its own dialog rather than a panel body. */
export function rendersOwnModal(entry) {
  return entry?.renders === 'modal';
}
