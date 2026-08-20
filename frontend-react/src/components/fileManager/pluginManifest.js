// Optional per-plugin metadata: <plugin>.ql-plugin.json next to <plugin>.py.
// The backend (script_routes.py) reads the sibling file and attaches its
// parsed content as `plugin_manifest` on the .py tree node — it never
// appears as its own row. Everything here is read-only display enrichment;
// a plugin with no manifest still works exactly as a plain checkbox.
//
// Schema (all fields optional):
//   { id, label, description, requires: [pluginBasename, ...],
//     cvars: { CVAR_NAME: "default value", ... },
//     settings: [{ key, cvar, type: "number"|"string"|"bool", default, min, max }] }

export function getPluginManifest(item) {
  return item?.plugin_manifest && typeof item.plugin_manifest === 'object'
    ? item.plugin_manifest
    : null;
}

export function getPluginDisplayLabel(item) {
  const manifest = getPluginManifest(item);
  const label = manifest?.label;
  return typeof label === 'string' && label.trim() ? label.trim() : item?.name;
}

export function getPluginDescription(item) {
  const manifest = getPluginManifest(item);
  const description = manifest?.description;
  return typeof description === 'string' && description.trim() ? description.trim() : null;
}

// Basenames (without .py) this plugin's manifest declares it needs enabled
// alongside it. Best-effort — malformed entries are dropped rather than
// thrown, since this only ever powers an advisory UI hint.
export function getPluginRequires(item) {
  const manifest = getPluginManifest(item);
  const requires = manifest?.requires;
  if (!Array.isArray(requires)) return [];
  return requires.filter(name => typeof name === 'string' && name.trim()).map(name => name.trim());
}
