import { FONT_EXTENSIONS } from './fileManagerUtils';

export const CONFIG_CAPS = {
  canCreate: true,
  canUpload: true,
  canDelete: true,
  canRename: true,
  canFolders: true,
  canCreateFolder: true,
  canCheckEnable: false,
  canValidate: false,
  allowedExtensions: ['.cfg', '.txt', '.ent'],
  newFileTemplate: () => '',
  protectedFiles: ['server.cfg', 'mappool.txt', 'access.txt', 'workshop.txt'],
  reservedFolderNames: ['scripts', 'factories'],
};

export const PLUGIN_CAPS = {
  canCreate: true,
  canUpload: true,
  canDelete: true,
  canRename: true,
  canFolders: true,
  canCreateFolder: true,
  canCheckEnable: true,
  canValidate: true,
  // Only root-level .py files (excluding __init__.py) can be enabled — see
  // pluginSelection.js. Everything else renders a hint instead of a checkbox.
  rootOnlyCheckable: true,
  allowedExtensions: ['.py', '.txt', '.so', ...FONT_EXTENSIONS],
  nonEditableExtensions: ['.so', ...FONT_EXTENSIONS],
  newFileTemplate: () => '',
  protectedFiles: [],
  reservedFolderNames: [],
};

export const FACTORY_CAPS = {
  canCreate: true,
  canUpload: true,
  canDelete: true,
  canRename: true,
  canFolders: false,
  canCreateFolder: false,
  canCheckEnable: true,
  canValidate: false,
  allowedExtensions: ['.factories'],
  newFileTemplate: () => '{\n  \n}',
  protectedFiles: [],
  reservedFolderNames: [],
};
