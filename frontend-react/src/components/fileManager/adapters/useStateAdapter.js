import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { rewritePathPrefix, MAX_CONFIG_FOLDER_DEPTH, MAX_CONFIG_FILE_DEPTH } from '../fileManagerUtils';

function getExtension(path) {
  const dotIndex = path.lastIndexOf('.');
  return dotIndex === -1 ? '' : path.slice(dotIndex).toLowerCase();
}

function validatePath(path, allowedExtensions) {
  const segments = path.split('/');
  if (segments.length > MAX_CONFIG_FILE_DEPTH) {
    throw new Error(`Path too deep: ${path}`);
  }
  for (const segment of segments) {
    if (!segment || segment.includes('\\') || segment.includes('..') || segment.startsWith('.')) {
      throw new Error(`Invalid name: ${segment}`);
    }
  }
  const ext = getExtension(path);
  if (!allowedExtensions.includes(ext)) {
    throw new Error(`Disallowed extension ${ext}`);
  }
}

function validateFolderName(name, reservedFolderNames = []) {
  if (!name || typeof name !== 'string') throw new Error('Folder name required');
  if (!/^[A-Za-z0-9._-]+$/.test(name)) throw new Error(`Invalid folder name: ${name}`);
  if (name.length > 64) throw new Error('Folder name too long');
  if (reservedFolderNames.map(n => n.toLowerCase()).includes(name.toLowerCase())) {
    throw new Error(`Reserved folder name: ${name}`);
  }
}

function validateFolderPath(path, reservedFolderNames = []) {
  const segments = path.split('/');
  if (segments.length > MAX_CONFIG_FOLDER_DEPTH) {
    throw new Error(`Path too deep: ${path} (max depth ${MAX_CONFIG_FOLDER_DEPTH})`);
  }
  for (const segment of segments) {
    validateFolderName(segment, reservedFolderNames);
  }
}

function normalizeTreeItem(item) {
  const path = item.path || item.name;
  return {
    ...item,
    name: item.name || path,
    path,
    type: item.type || 'file',
    file_type: item.file_type || 'text',
  };
}

function buildHierarchicalTree(flatItems, folderPaths, protectedSet) {
  const root = { children: new Map() };

  function ensureFolderNode(path) {
    const segments = path.split('/');
    let node = root;
    let builtPath = '';
    for (const segment of segments) {
      builtPath = builtPath ? `${builtPath}/${segment}` : segment;
      if (!node.children.has(builtPath)) {
        node.children.set(builtPath, {
          name: segment,
          path: builtPath,
          type: 'folder',
          children: new Map(),
        });
      }
      node = node.children.get(builtPath);
    }
    return node;
  }

  for (const path of folderPaths) {
    ensureFolderNode(path);
  }

  for (const item of flatItems) {
    const segments = item.path.split('/');
    const entry = { ...item, protected: protectedSet.has(item.path) };
    if (segments.length === 1) {
      root.children.set(item.path, entry);
      continue;
    }
    const parentPath = segments.slice(0, -1).join('/');
    const parentNode = ensureFolderNode(parentPath);
    parentNode.children.set(item.path, entry);
  }

  function toSortedArray(node) {
    const items = [...node.children.values()].map(child => (
      child.type === 'folder'
        ? { ...child, children: toSortedArray(child) }
        : child
    ));
    return items.sort((a, b) => {
      if (a.type === 'folder' && b.type !== 'folder') return -1;
      if (a.type !== 'folder' && b.type === 'folder') return 1;
      return a.name.localeCompare(b.name);
    });
  }

  return toSortedArray(root);
}

export function useStateAdapter({
  initialFiles = {},
  initialFolders = [],
  allowedExtensions = [],
  protectedFiles = [],
  reservedFolderNames = [],
  serverTree = null,
  readServerContent = null,
  onFilesChange = null,
} = {}) {
  const [files, setFiles] = useState(initialFiles);
  const [folders, setFolders] = useState(() => new Set(initialFolders));
  const [deletedPaths, setDeletedPaths] = useState(() => new Set());
  const [resetCount, setResetCount] = useState(0);
  const initialFilesRef = useRef(initialFiles);
  const initialFoldersRef = useRef(new Set(initialFolders));
  const protectedSet = useMemo(() => new Set(protectedFiles), [protectedFiles]);

  useEffect(() => {
    onFilesChange?.(files);
  }, [files, onFilesChange]);

  const tree = useMemo(() => {
    const byPath = new Map();
    for (const item of serverTree || []) {
      const normalized = normalizeTreeItem(item);
      if (!deletedPaths.has(normalized.path)) {
        byPath.set(normalized.path, normalized);
      }
    }
    for (const path of Object.keys(files)) {
      const existing = byPath.get(path) || {};
      byPath.set(path, {
        ...existing,
        name: existing.name || path.split('/').pop(),
        path,
        type: 'file',
        file_type: existing.file_type || 'text',
      });
    }
    return buildHierarchicalTree([...byPath.values()], folders, protectedSet);
  }, [files, folders, serverTree, deletedPaths, protectedSet]);

  const checkedFiles = useMemo(() => new Set(Object.keys(files)), [files]);

  const readContent = useCallback(async (path) => {
    if (files[path] !== undefined) return files[path] ?? '';
    if (readServerContent) return await readServerContent(path);
    return '';
  }, [files, readServerContent]);

  const writeContent = useCallback(async (path, content) => {
    validatePath(path, allowedExtensions);
    setFiles(prev => ({ ...prev, [path]: content ?? '' }));
    setDeletedPaths(prev => {
      const next = new Set(prev);
      next.delete(path);
      return next;
    });
  }, [allowedExtensions]);

  const upload = useCallback(async (file, targetDir = '') => {
    const targetPath = targetDir ? `${targetDir}/${file.name}` : file.name;
    validatePath(targetPath, allowedExtensions);
    const content = await file.text();
    setFiles(prev => ({ ...prev, [targetPath]: content }));
    setDeletedPaths(prev => {
      const next = new Set(prev);
      next.delete(targetPath);
      return next;
    });
    return { path: targetPath, content };
  }, [allowedExtensions]);

  const deleteFile = useCallback(async (path) => {
    if (protectedSet.has(path)) {
      throw new Error(`Cannot delete protected file: ${path}`);
    }
    setFiles(prev => {
      const next = { ...prev };
      delete next[path];
      return next;
    });
    setDeletedPaths(prev => new Set(prev).add(path));
  }, [protectedSet]);

  const setChecked = useCallback(async (path, checked) => {
    if (checked) {
      if (files[path] !== undefined) return;
      const content = readServerContent ? await readServerContent(path) : '';
      setFiles(prev => prev[path] !== undefined ? prev : { ...prev, [path]: content || '' });
      return;
    }
    if (protectedSet.has(path)) {
      throw new Error(`Cannot uncheck protected file: ${path}`);
    }
    setFiles(prev => {
      const next = { ...prev };
      delete next[path];
      return next;
    });
  }, [files, readServerContent, protectedSet]);

  const renameFile = useCallback(async (oldPath, newPath) => {
    if (protectedSet.has(oldPath)) {
      throw new Error(`Cannot rename protected file: ${oldPath}`);
    }
    validatePath(newPath, allowedExtensions);
    if (Object.prototype.hasOwnProperty.call(files, newPath)) {
      throw new Error(`Target exists: ${newPath}`);
    }
    const content = files[oldPath] !== undefined ? files[oldPath] : await readContent(oldPath);
    setFiles(prev => {
      const next = { ...prev };
      delete next[oldPath];
      next[newPath] = content ?? '';
      return next;
    });
    setDeletedPaths(prev => {
      const next = new Set(prev);
      next.add(oldPath);
      next.delete(newPath);
      return next;
    });
  }, [allowedExtensions, protectedSet, readContent, files]);

  const createFolder = useCallback((path) => {
    validateFolderPath(path, reservedFolderNames);
    if (folders.has(path)) throw new Error(`Folder already exists: ${path}`);
    setFolders(prev => {
      const next = new Set(prev);
      next.add(path);
      return next;
    });
  }, [folders, reservedFolderNames]);

  const deleteFolder = useCallback((path) => {
    setFiles(prev => {
      const next = {};
      for (const [filePath, content] of Object.entries(prev)) {
        if (filePath === path || filePath.startsWith(path + '/')) continue;
        next[filePath] = content;
      }
      return next;
    });
    setDeletedPaths(prev => {
      const next = new Set(prev);
      for (const filePath of Object.keys(files)) {
        if (filePath === path || filePath.startsWith(path + '/')) next.add(filePath);
      }
      return next;
    });
    setFolders(prev => {
      const next = new Set(prev);
      for (const folderPath of prev) {
        if (folderPath === path || folderPath.startsWith(path + '/')) next.delete(folderPath);
      }
      return next;
    });
  }, [files]);

  const renameFolder = useCallback((oldPath, newPath) => {
    const newSegments = newPath.split('/');
    validateFolderName(newSegments[newSegments.length - 1], reservedFolderNames);
    if (folders.has(newPath)) throw new Error(`Folder already exists: ${newPath}`);
    setFiles(prev => {
      const next = {};
      for (const [filePath, content] of Object.entries(prev)) {
        const rewritten = rewritePathPrefix(filePath, oldPath, newPath);
        next[rewritten ?? filePath] = content;
      }
      return next;
    });
    setFolders(prev => {
      const next = new Set();
      for (const folderPath of prev) {
        const rewritten = rewritePathPrefix(folderPath, oldPath, newPath);
        next.add(rewritten ?? folderPath);
      }
      return next;
    });
  }, [folders, reservedFolderNames]);

  const hasChanges = useMemo(
    () =>
      JSON.stringify(files) !== JSON.stringify(initialFilesRef.current) ||
      deletedPaths.size > 0 ||
      JSON.stringify([...folders].sort()) !== JSON.stringify([...initialFoldersRef.current].sort()),
    [files, deletedPaths, folders],
  );

  const serialize = useCallback(() => ({
    files: { ...files },
    folders: [...folders],
  }), [files, folders]);

  const reset = useCallback((newInitialFiles = {}, newInitialFolders = []) => {
    setFiles(newInitialFiles);
    setFolders(new Set(newInitialFolders));
    setDeletedPaths(new Set());
    initialFilesRef.current = newInitialFiles;
    initialFoldersRef.current = new Set(newInitialFolders);
    setResetCount(c => c + 1);
  }, []);

  return {
    resetCount,
    tree,
    readContent,
    writeContent,
    upload,
    deleteFile,
    renameFile,
    createFolder,
    deleteFolder,
    renameFolder,
    checkedFiles,
    setChecked,
    hasChanges,
    serialize,
    reset,
    loading: false,
    error: null,
  };
}
