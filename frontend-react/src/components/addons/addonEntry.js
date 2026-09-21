// Small facts about a manifest mount-point entry that more than one renderer
// needs. Kept separate from AddonPanel/AddonMenuSection so neither has to
// import the other just to ask "does this entry supply its own dialog?".

/**
 * Reserved prefix for a component QLSM itself would provide, named in the
 * manifest instead of shipped with the addon. QLSM provides none, so nothing
 * resolves it -- the prefix is recognised only to explain that, instead of
 * rendering an empty panel.
 */
export const BUNDLED_PREFIX = 'bundled:';

/** True when the entry renders its own dialog rather than a panel body. */
export function rendersOwnModal(entry) {
  return entry?.renders === 'modal';
}
