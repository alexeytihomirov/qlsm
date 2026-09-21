// Builds and triggers the browser download for a locally-edited
// qlsm-plugins.json draft. Mirrors utils/presetDownload.js's
// createObjectURL/anchor-click mechanics.

const stripRowKey = (entry) => {
  const copy = { ...entry };
  delete copy._key;
  return copy;
};

/**
 * A plugin ready to write into qlsm-plugins.json: empty optional fields and
 * empty cvars/commands lists are left out entirely rather than written as ''
 * or [], matching the shape real qlsm-plugins.json files already use.
 */
export function cleanPluginForExport(p) {
  const out = { filename: p.filename || '' };
  if (p.label) out.label = p.label;
  if (p.description) out.description = p.description;
  if (p.runtime) out.runtime = p.runtime;
  if (p.requires_qlsm_version) out.requires_qlsm_version = p.requires_qlsm_version;
  // `_key` is the editor's own row id (utils/pluginManifestDraft.js) and
  // must never reach the exported file.
  if (Array.isArray(p.cvars) && p.cvars.length) out.cvars = p.cvars.map(stripRowKey);
  if (Array.isArray(p.commands) && p.commands.length) out.commands = p.commands.map(stripRowKey);
  return out;
}

/**
 * A safe qlsm-plugins.json-style filename: falls back when blank, and always
 * ends in .json.
 *
 * The operator types this into the export box, so it is stripped to the same
 * character set as utils/presetDownload.js's safePresetDownloadName rather
 * than trusting the browser to make sense of a value like "../x".
 */
export function safeManifestFilename(name) {
  const base = String(name || '')
    .trim()
    .replace(/\s+/g, '-')
    .replace(/[^A-Za-z0-9._-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^[.-]+|[.-]+$/g, '');
  if (!base) return 'qlsm-plugins.json';
  return /\.json$/i.test(base) ? base : `${base}.json`;
}

export function manifestJsonBody(plugins) {
  return JSON.stringify({ plugins: (plugins || []).map(cleanPluginForExport) }, null, 2);
}

export function triggerManifestDownload(filename, plugins) {
  const blob = new Blob([manifestJsonBody(plugins)], { type: 'application/json' });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = safeManifestFilename(filename);
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(url);
}
