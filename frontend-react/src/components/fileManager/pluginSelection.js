// Which plugin files the Plugins tab lets you enable.
//
// minqlx loads every qlx_plugins entry as a top-level module out of
// qlx_pluginsPath, so only root-level .py files can ever be enabled. Files in
// subfolders are helper modules imported by a root plugin (e.g.
// discord_extensions/* is imported by mydiscordbot.py), and __init__.py is a
// package marker. Both used to render a checkbox that silently did nothing.
import { basename } from './fileManagerUtils';

export const PLUGIN_HINT_TEXT = {
  subfolder: "Plugins in subfolders can't be enabled directly. Import them from a plugin in the root folder instead.",
  'package-marker': "__init__.py marks a package and can't be enabled as a plugin.",
};

export function isEnableablePluginPath(path = '') {
  if (!path.endsWith('.py')) return false;
  if (path.includes('/')) return false;
  return path !== '__init__.py';
}

export function getPluginHintReason(path = '') {
  if (!path.endsWith('.py')) return null;
  if (basename(path) === '__init__.py') return 'package-marker';
  if (path.includes('/')) return 'subfolder';
  return null;
}

export function partitionCheckedPaths(paths = []) {
  const selectable = new Set();
  const dropped = [];
  for (const path of paths) {
    if (isEnableablePluginPath(path)) selectable.add(path);
    else dropped.push(path);
  }
  return { selectable, dropped };
}

// Maps bare qlx_plugins names back onto tree paths. Only root-level files can
// match, so a name that resolves solely to a subfolder file is reported as
// dropped rather than silently ticking the wrong node.
export function resolveRootPluginPaths(tree = [], rawNames = []) {
  const wanted = new Set(rawNames);
  const rootPaths = new Set();
  const unusableNames = new Set();

  const walk = (node) => {
    if (node.type === 'folder') {
      (node.children || []).forEach(walk);
      return;
    }
    const path = node.path || '';
    if (!path.endsWith('.py')) return;
    const name = basename(path).replace(/\.py$/, '');
    if (!wanted.has(name)) return;
    if (isEnableablePluginPath(path)) rootPaths.add(path);
    else unusableNames.add(name);
  };
  tree.forEach(walk);

  const paths = [...rootPaths];
  const resolved = new Set(paths.map(path => path.replace(/\.py$/, '')));
  return {
    paths,
    droppedNames: [...unusableNames].filter(name => !resolved.has(name)),
  };
}

export function toQlxPluginNames(checked = []) {
  return Array.from(checked)
    .filter(isEnableablePluginPath)
    .map(path => path.replace(/\.py$/, ''));
}
