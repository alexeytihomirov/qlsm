import { renderHook, act } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { useStateAdapter } from '../adapters/useStateAdapter';

const opts = {
  initialFiles: { 'server.cfg': '' },
  allowedExtensions: ['.cfg', '.txt', '.ent'],
  protectedFiles: ['server.cfg'],
};

describe('useStateAdapter folders', () => {
  it('createFolder adds to folder set and serializes', () => {
    const { result } = renderHook(() => useStateAdapter(opts));
    act(() => { result.current.createFolder('extras'); });
    expect(result.current.tree.some(i => i.type === 'folder' && i.name === 'extras')).toBe(true);
    const { folders } = result.current.serialize();
    expect(folders).toContain('extras');
  });

  it('createFolder rejects duplicates and reserved names', () => {
    const { result } = renderHook(() => useStateAdapter({
      ...opts,
      reservedFolderNames: ['scripts'],
    }));
    act(() => { result.current.createFolder('extras'); });
    expect(() => { result.current.createFolder('extras'); }).toThrow();
    expect(() => { result.current.createFolder('scripts'); }).toThrow();
  });

  it('deleteFolder removes folder and child files', async () => {
    const { result } = renderHook(() => useStateAdapter(opts));
    act(() => { result.current.createFolder('extras'); });
    await act(async () => { await result.current.writeContent('extras/a.ent', '// a'); });
    act(() => { result.current.deleteFolder('extras'); });
    expect(result.current.tree.some(i => i.type === 'folder' && i.name === 'extras')).toBe(false);
    const { files } = result.current.serialize();
    expect(files['extras/a.ent']).toBeUndefined();
  });

  it('renameFolder rewrites child paths', async () => {
    const { result } = renderHook(() => useStateAdapter(opts));
    act(() => { result.current.createFolder('old'); });
    await act(async () => { await result.current.writeContent('old/x.cfg', 'data'); });
    act(() => { result.current.renameFolder('old', 'new'); });
    const { files, folders } = result.current.serialize();
    expect(files['new/x.cfg']).toBe('data');
    expect(files['old/x.cfg']).toBeUndefined();
    expect(folders).toContain('new');
    expect(folders).not.toContain('old');
  });
});

describe('useStateAdapter nested folders', () => {
  it('createFolder accepts a 3-level-deep path', () => {
    const { result } = renderHook(() => useStateAdapter(opts));
    act(() => { result.current.createFolder('a'); });
    act(() => { result.current.createFolder('a/b'); });
    act(() => { result.current.createFolder('a/b/c'); });
    const { folders } = result.current.serialize();
    expect(folders).toEqual(expect.arrayContaining(['a', 'a/b', 'a/b/c']));
  });

  it('createFolder rejects a path deeper than 3 levels', () => {
    const { result } = renderHook(() => useStateAdapter(opts));
    act(() => { result.current.createFolder('a'); });
    act(() => { result.current.createFolder('a/b'); });
    act(() => { result.current.createFolder('a/b/c'); });
    expect(() => { result.current.createFolder('a/b/c/d'); }).toThrow();
  });

  it('buildHierarchicalTree nests folders and files at the correct depth', async () => {
    const { result } = renderHook(() => useStateAdapter(opts));
    act(() => { result.current.createFolder('a'); });
    act(() => { result.current.createFolder('a/b'); });
    await act(async () => { await result.current.writeContent('a/b/deep.cfg', 'x'); });

    const topA = result.current.tree.find(i => i.path === 'a');
    expect(topA.type).toBe('folder');
    const nestedB = topA.children.find(i => i.path === 'a/b');
    expect(nestedB.type).toBe('folder');
    expect(nestedB.children.map(i => i.path)).toEqual(['a/b/deep.cfg']);
  });

  it('deleteFolder removes all descendant folders and files at any depth', async () => {
    const { result } = renderHook(() => useStateAdapter(opts));
    act(() => { result.current.createFolder('a'); });
    act(() => { result.current.createFolder('a/b'); });
    await act(async () => { await result.current.writeContent('a/b/deep.cfg', 'x'); });
    act(() => { result.current.deleteFolder('a'); });

    const { files, folders } = result.current.serialize();
    expect(folders).not.toContain('a');
    expect(folders).not.toContain('a/b');
    expect(files['a/b/deep.cfg']).toBeUndefined();
  });

  it('renameFolder rewrites nested descendant paths and folder set entries', async () => {
    const { result } = renderHook(() => useStateAdapter(opts));
    act(() => { result.current.createFolder('a'); });
    act(() => { result.current.createFolder('a/b'); });
    await act(async () => { await result.current.writeContent('a/b/deep.cfg', 'x'); });
    act(() => { result.current.renameFolder('a/b', 'a/renamed'); });

    const { files, folders } = result.current.serialize();
    expect(files['a/renamed/deep.cfg']).toBe('x');
    expect(files['a/b/deep.cfg']).toBeUndefined();
    expect(folders).toContain('a/renamed');
    expect(folders).not.toContain('a/b');
  });
});
