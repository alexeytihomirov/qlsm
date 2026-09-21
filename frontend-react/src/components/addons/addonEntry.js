// Small facts about a manifest mount-point entry that more than one renderer
// needs. Kept separate from AddonPanel/AddonMenuSection so neither has to
// import the other just to ask "does this entry supply its own dialog?".

/** True when the entry renders its own dialog rather than a panel body. */
export function rendersOwnModal(entry) {
  return entry?.renders === 'modal';
}
