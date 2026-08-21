import { describe, expect, it } from 'vitest';

import {
  formatPluginCommandsText,
  getPluginCommands,
  getPluginCvars,
  getPluginDescription,
  getPluginDisplayLabel,
  getPluginManifest,
} from '../pluginManifest';

describe('getPluginManifest', () => {
  it('returns the manifest object when present', () => {
    const item = { name: 'balance.py', plugin_manifest: { label: 'Balance' } };
    expect(getPluginManifest(item)).toEqual({ label: 'Balance' });
  });

  it('returns null when absent', () => {
    expect(getPluginManifest({ name: 'balance.py' })).toBeNull();
  });

  it('returns null for a non-object manifest (backend guards this, but be defensive)', () => {
    expect(getPluginManifest({ name: 'balance.py', plugin_manifest: 'oops' })).toBeNull();
  });

  it('returns null for a null/undefined item', () => {
    expect(getPluginManifest(null)).toBeNull();
    expect(getPluginManifest(undefined)).toBeNull();
  });
});

describe('getPluginDisplayLabel', () => {
  it('uses the manifest label when present', () => {
    const item = { name: 'balance.py', plugin_manifest: { label: 'Team Balance' } };
    expect(getPluginDisplayLabel(item)).toBe('Team Balance');
  });

  it('falls back to the filename with no manifest', () => {
    expect(getPluginDisplayLabel({ name: 'balance.py' })).toBe('balance.py');
  });

  it('falls back to the filename when label is blank/whitespace', () => {
    expect(getPluginDisplayLabel({ name: 'balance.py', plugin_manifest: { label: '   ' } })).toBe('balance.py');
  });

  it('falls back to the filename when label is not a string', () => {
    expect(getPluginDisplayLabel({ name: 'balance.py', plugin_manifest: { label: 42 } })).toBe('balance.py');
  });
});

describe('getPluginDescription', () => {
  it('returns a trimmed description when present', () => {
    const item = { plugin_manifest: { description: '  In-game team balance.  ' } };
    expect(getPluginDescription(item)).toBe('In-game team balance.');
  });

  it('returns null with no manifest or blank description', () => {
    expect(getPluginDescription({})).toBeNull();
    expect(getPluginDescription({ plugin_manifest: { description: '' } })).toBeNull();
  });
});

describe('getPluginCommands', () => {
  it('normalizes a full command entry', () => {
    const item = {
      plugin_manifest: {
        commands: [{ name: 'setperm', usage: '<id> <level>', permission: 5, description: "Sets a player's permission level." }],
      },
    };
    expect(getPluginCommands(item)).toEqual([
      { name: 'setperm', usage: '<id> <level>', permission: 5, description: "Sets a player's permission level." },
    ]);
  });

  it('defaults missing usage/permission/description to null', () => {
    const item = { plugin_manifest: { commands: [{ name: 'myperm' }] } };
    expect(getPluginCommands(item)).toEqual([{ name: 'myperm', usage: null, permission: null, description: null }]);
  });

  it('drops entries with no name', () => {
    const item = { plugin_manifest: { commands: [{ description: 'no name' }, { name: '' }, { name: 'ok' }] } };
    expect(getPluginCommands(item)).toEqual([{ name: 'ok', usage: null, permission: null, description: null }]);
  });

  it('returns an empty array when commands is missing or not an array', () => {
    expect(getPluginCommands({})).toEqual([]);
    expect(getPluginCommands({ plugin_manifest: { commands: 'setperm' } })).toEqual([]);
  });
});

describe('getPluginCvars', () => {
  it('normalizes a full cvar entry for each supported type', () => {
    const item = {
      plugin_manifest: {
        cvars: [
          { cvar: 'qlx_enabled', label: 'Enabled', description: 'Turns it on.', type: 'bool', default: true },
          { cvar: 'qlx_refPerm', label: 'Ref Perm', type: 'number', default: 3, min: 0, max: 5 },
          { cvar: 'qlx_deny', type: 'string', default: 'a,b,c' },
        ],
      },
    };
    expect(getPluginCvars(item)).toEqual([
      { cvar: 'qlx_enabled', label: 'Enabled', description: 'Turns it on.', type: 'bool', default: true, min: null, max: null },
      { cvar: 'qlx_refPerm', label: 'Ref Perm', description: null, type: 'number', default: 3, min: 0, max: 5 },
      { cvar: 'qlx_deny', label: 'qlx_deny', description: null, type: 'string', default: 'a,b,c', min: null, max: null },
    ]);
  });

  it('falls back to the cvar name when label is missing', () => {
    const item = { plugin_manifest: { cvars: [{ cvar: 'qlx_foo', type: 'bool' }] } };
    expect(getPluginCvars(item)[0].label).toBe('qlx_foo');
  });

  it('drops entries with no cvar name', () => {
    const item = { plugin_manifest: { cvars: [{ type: 'bool' }, { cvar: '', type: 'bool' }, { cvar: 'qlx_ok', type: 'bool' }] } };
    expect(getPluginCvars(item)).toEqual([{ cvar: 'qlx_ok', label: 'qlx_ok', description: null, type: 'bool', default: null, min: null, max: null }]);
  });

  it('drops entries with an unrecognized type', () => {
    const item = { plugin_manifest: { cvars: [{ cvar: 'qlx_bad', type: 'array' }, { cvar: 'qlx_missing' }] } };
    expect(getPluginCvars(item)).toEqual([]);
  });

  it('ignores min/max on non-number types and a mistyped default', () => {
    const item = {
      plugin_manifest: {
        cvars: [
          { cvar: 'qlx_str', type: 'string', default: 42, min: 1, max: 9 },
          { cvar: 'qlx_num', type: 'number', default: 'not-a-number' },
        ],
      },
    };
    expect(getPluginCvars(item)).toEqual([
      { cvar: 'qlx_str', label: 'qlx_str', description: null, type: 'string', default: null, min: null, max: null },
      { cvar: 'qlx_num', label: 'qlx_num', description: null, type: 'number', default: null, min: null, max: null },
    ]);
  });

  it('returns an empty array when cvars is missing or not an array', () => {
    expect(getPluginCvars({})).toEqual([]);
    expect(getPluginCvars({ plugin_manifest: { cvars: 'nope' } })).toEqual([]);
  });
});

describe('formatPluginCommandsText', () => {
  it('formats name, usage, description, and permission', () => {
    const item = {
      plugin_manifest: {
        commands: [{ name: 'setperm', usage: '<id> <level>', permission: 5, description: "Sets a player's permission level." }],
      },
    };
    expect(formatPluginCommandsText(item)).toBe("!setperm <id> <level> — Sets a player's permission level. (perm 5)");
  });

  it('joins multiple commands with a separator', () => {
    const item = { plugin_manifest: { commands: [{ name: 'a' }, { name: 'b' }] } };
    expect(formatPluginCommandsText(item)).toBe('!a  ·  !b');
  });

  it('omits missing usage/description/permission cleanly', () => {
    const item = { plugin_manifest: { commands: [{ name: 'myperm' }] } };
    expect(formatPluginCommandsText(item)).toBe('!myperm');
  });

  it('returns an empty string with no commands', () => {
    expect(formatPluginCommandsText({})).toBe('');
  });
});
