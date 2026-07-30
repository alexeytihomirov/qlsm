import { describe, expect, it } from 'vitest';

import {
  FONT_EXTENSIONS,
  flattenFolders,
  getExtension,
  getFileType,
  getPathDepth,
  MAX_CONFIG_FILE_DEPTH,
  MAX_CONFIG_FOLDER_DEPTH,
} from '../fileManagerUtils';

describe('getExtension', () => {
  it('returns the lowercased extension including the dot', () => {
    expect(getExtension('server.CFG')).toBe('.cfg');
    expect(getExtension('a/b/map.Ent')).toBe('.ent');
  });

  it('returns empty string when there is no dot', () => {
    expect(getExtension('README')).toBe('');
  });
});

describe('getFileType', () => {
  it('classifies all supported font extensions case-insensitively', () => {
    expect(FONT_EXTENSIONS).toHaveLength(13);
    for (const extension of FONT_EXTENSIONS) {
      expect(getFileType(`fonts/example${extension.toUpperCase()}`)).toBe('font');
    }
  });
});

describe('depth constants', () => {
  it('caps folder depth at 3 and file depth at 4', () => {
    expect(MAX_CONFIG_FOLDER_DEPTH).toBe(3);
    expect(MAX_CONFIG_FILE_DEPTH).toBe(4);
  });
});

describe('getPathDepth', () => {
  it('counts path segments', () => {
    expect(getPathDepth('a')).toBe(1);
    expect(getPathDepth('a/b/c')).toBe(3);
    expect(getPathDepth('a/b/c/file.cfg')).toBe(4);
  });

  it('returns 0 for empty path', () => {
    expect(getPathDepth('')).toBe(0);
  });
});

describe('flattenFolders', () => {
  it('returns all folder nodes at any depth, excluding files', () => {
    const tree = [
      {
        type: 'folder', name: 'a', path: 'a', children: [
          { type: 'folder', name: 'b', path: 'a/b', children: [] },
          { type: 'file', name: 'x.cfg', path: 'a/x.cfg' },
        ],
      },
      { type: 'file', name: 'root.cfg', path: 'root.cfg' },
    ];
    const paths = flattenFolders(tree).map(f => f.path).sort();
    expect(paths).toEqual(['a', 'a/b']);
  });
});
