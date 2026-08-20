import { describe, expect, it } from 'vitest';

import {
  getPluginDescription,
  getPluginDisplayLabel,
  getPluginManifest,
  getPluginRequires,
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

describe('getPluginRequires', () => {
  it('returns the requires list, trimmed', () => {
    const item = { plugin_manifest: { requires: ['balance.py', ' permission.py '] } };
    expect(getPluginRequires(item)).toEqual(['balance.py', 'permission.py']);
  });

  it('drops non-string / blank entries', () => {
    const item = { plugin_manifest: { requires: ['balance.py', '', 42, null] } };
    expect(getPluginRequires(item)).toEqual(['balance.py']);
  });

  it('returns an empty array when requires is missing or not an array', () => {
    expect(getPluginRequires({})).toEqual([]);
    expect(getPluginRequires({ plugin_manifest: { requires: 'balance.py' } })).toEqual([]);
  });
});
