// Small facts about a manifest mount-point entry that more than one renderer
// needs. Kept separate from AddonPanel/AddonMenuSection so neither has to
// import the other just to ask "does this entry supply its own dialog?".

/**
 * Prefix an entry's `component` used to carry when a *bundled* addon could
 * name a component QLSM itself builds ("tier 1.5"). No addon ships in the
 * image any more, so nothing resolves it -- the prefix is still recognised
 * only to explain the failure instead of rendering an empty panel.
 */
export const BUNDLED_PREFIX = 'bundled:';

/** True when the entry renders its own dialog rather than a panel body. */
export function rendersOwnModal(entry) {
  return entry?.renders === 'modal';
}
