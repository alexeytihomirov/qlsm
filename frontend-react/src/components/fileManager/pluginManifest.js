// Optional per-plugin metadata: <plugin>.ql-plugin.json next to <plugin>.py.
// The backend (script_routes.py) reads the sibling file and attaches its
// parsed content as `plugin_manifest` on the .py tree node — it never
// appears as its own row. Everything here is read-only display enrichment;
// a plugin with no manifest still works exactly as a plain checkbox.
//
// Schema (all fields optional):
//   { id, label, description,
//     cvars: { CVAR_NAME: "default value", ... },
//     settings: [{ key, cvar, type: "number"|"string"|"bool", default, min, max }] }
// No plugin-to-plugin dependency graph — deliberately dropped, real-world
// plugins (minqlxtended-plugins included) essentially never need one, and
// modeling it was the main source of complexity in ql-server-core's
// addon-manifest system this replaces.

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
