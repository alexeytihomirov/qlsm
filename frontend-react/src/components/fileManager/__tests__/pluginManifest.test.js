import { describe, expect, it } from 'vitest';

import {
  formatPluginCommandsText,
  getPluginCommands,
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
