// Read/write `set <cvar> "<value>"` lines in a server.cfg draft. Generalizes
// the ad hoc sv_hostname sync already used for the Hostname field
// (EditInstanceConfigModal.jsx / AddInstanceForm.jsx) to any cvar a plugin
// manifest declares.

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function buildCvarRegex(cvar) {
  return new RegExp(`^set\\s+${escapeRegExp(cvar)}\\s+"([^"]*)"`, 'm');
}

export function readCvarFromConfig(cfgText, cvar) {
  if (!cvar) return null;
  const match = (cfgText || '').match(buildCvarRegex(cvar));
  return match ? match[1] : null;
}

// No quote-escaping, matching the existing sv_hostname sync's behavior.
export function upsertCvarInConfig(cfgText, cvar, value) {
  const cfg = cfgText || '';
  const line = `set ${cvar} "${value}"`;
  const regex = buildCvarRegex(cvar);
  if (regex.test(cfg)) return cfg.replace(regex, () => line);
  return cfg ? `${cfg}\n${line}` : line;
}

// server.cfg stores everything as a quoted string; these translate a typed
// manifest value to/from that string form.
export function serializeCvarValue(type, value) {
  if (type === 'bool') return value ? '1' : '0';
  if (value === null || value === undefined) return '';
  return String(value);
}

export function parseCvarValue(type, rawValue) {
  if (rawValue === null || rawValue === undefined) return null;
  if (type === 'bool') return rawValue === '1' || rawValue.toLowerCase() === 'true';
  if (type === 'number') {
    const parsed = Number(rawValue);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return rawValue;
}
