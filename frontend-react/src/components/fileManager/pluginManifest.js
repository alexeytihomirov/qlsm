// Optional per-plugin metadata: <plugin>.ql-plugin.json next to <plugin>.py.
// The backend (script_routes.py) reads the sibling file and attaches its
// parsed content as `plugin_manifest` on the .py tree node — it never
// appears as its own row. Everything here is read-only display enrichment;
// a plugin with no manifest still works exactly as a plain checkbox.
//
// Schema (all fields optional):
//   { label, description,
//     commands: [{ name, usage, permission, description }, ...] }
// `name` is what the player/admin types after ! (a plugin registering
// aliases, e.g. ("lobby", "servers"), gets one entry per alias so each shows
// up distinctly). `permission` is the minqlx permission level required
// (0 = anyone), omitted when the plugin doesn't gate the command.
// No cvars/settings and no plugin-to-plugin dependency graph — deliberately
// dropped, that's exactly the complexity ql-server-core's addon-manifest
// system carried that this was meant to avoid re-inventing.

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

// Commands the plugin registers, filtered/normalized to a safe shape. A
// malformed entry (missing name, wrong types) is dropped rather than
// thrown, since this only ever powers an advisory UI list.
export function getPluginCommands(item) {
  const manifest = getPluginManifest(item);
  const commands = manifest?.commands;
  if (!Array.isArray(commands)) return [];
  return commands
    .filter(c => c && typeof c === 'object' && typeof c.name === 'string' && c.name.trim())
    .map(c => ({
      name: c.name.trim(),
      usage: typeof c.usage === 'string' && c.usage.trim() ? c.usage.trim() : null,
      permission: Number.isInteger(c.permission) ? c.permission : null,
      description: typeof c.description === 'string' && c.description.trim() ? c.description.trim() : null,
    }));
}

// One-line-per-command text block, for contexts (like a tooltip) that only
// render a plain string. `!name usage — description (perm N)`.
export function formatPluginCommandsText(item) {
  return getPluginCommands(item)
    .map(c => {
      const usage = c.usage ? ` ${c.usage}` : '';
      const perm = c.permission ? ` (perm ${c.permission})` : '';
      const desc = c.description ? ` — ${c.description}` : '';
      return `!${c.name}${usage}${desc}${perm}`;
    })
    .join('  ·  ');
}
