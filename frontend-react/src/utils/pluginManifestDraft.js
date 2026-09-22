// Shapes and helpers for the manifest editor's local draft of one
// repository's plugin list.

// A stable id per row, for @dnd-kit and for React keys.
//
// Plugin rows need one because `filename` can't serve that role the way it
// does for HookRow's SortableHookRow: a freshly-added plugin starts blank and
// two rows can briefly share (or lack) a filename while the operator edits.
//
// Cvar and command rows need one for a different reason. Keyed by array
// index, React reuses the same <input> DOM node when the operator switches
// plugins -- so a value typed into plugin A's cvar row stays on screen over
// plugin B's, and gets exported as B's if anything else on B is edited.
let rowKeySeed = 0;
export const makeRowKey = (prefix) => `${prefix}-${rowKeySeed++}`;

// Blank plugin/cvar/command shapes for "+ Add".
export const blankPlugin = () => ({
  _key: makeRowKey('plugin'),
  filename: '', label: '', description: '', runtime: '', requires_qlsm_version: '', cvars: [], commands: [],
});
export const blankCvar = () => ({
  _key: makeRowKey('cvar'), cvar: '', label: '', type: 'string', default: '', description: '',
});
export const blankCommand = () => ({
  _key: makeRowKey('command'), name: '', usage: '', description: '',
});

export function defaultForCvarType(type) {
  if (type === 'number') return 0;
  if (type === 'bool') return false;
  return '';
}

// Cvar/command entries are copied through untouched apart from the added
// `_key`. fetch_manifest() only checks that the field is a list and never
// looks inside the dicts, so an entry may be missing any key, or carry one
// this editor doesn't render -- copying verbatim keeps those in the exported
// file instead of quietly dropping them.
function withRowKeys(list, prefix) {
  if (!Array.isArray(list)) return [];
  return list.map((entry) => ({
    ...(entry && typeof entry === 'object' ? entry : {}),
    _key: makeRowKey(prefix),
  }));
}

/**
 * Builds the editable draft from a repository's known plugin list.
 *
 * Plugin-level fields are normalized to strings so every field renders as a
 * controlled input. Notably absent is `version_risk`, which qlsm adds itself
 * at sync time from requires_qlsm_version plus this install's own VERSION --
 * it is never something to author or ship in the file.
 *
 * @param {Array<object>} repoPlugins - `repo.plugins`, i.e. fetch_manifest() output
 */
export function buildManifestDraft(repoPlugins) {
  return (repoPlugins || []).map((p) => ({
    _key: makeRowKey('plugin'),
    filename: p.filename || '',
    label: p.label || '',
    description: p.description || '',
    runtime: p.runtime || '',
    requires_qlsm_version: p.requires_qlsm_version || '',
    cvars: withRowKeys(p.cvars, 'cvar'),
    commands: withRowKeys(p.commands, 'command'),
  }));
}
