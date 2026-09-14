// Addon API client.
//
// Kept out of services/api.js on purpose: everything here talks to a single
// URL prefix (/api/addons/...) that core owns and no addon can escape, and
// api.js is already ~1200 lines of per-resource functions.
//
// Design: docs/superpowers/specs/2026-09-14-qlsm-addon-system-design.md (monorepo).
import apiClient from './api';

export const listAddons = async () => {
  const response = await apiClient.get('/addons');
  return response.data.data.addons;
};

export const getAddonState = async (addonId, scope = 'global', scopeId = 0) => {
  const response = await apiClient.get(`/addons/${addonId}/state`, {
    params: { scope, scope_id: scopeId },
  });
  return response.data.data;
};

export const updateAddonState = async (addonId, scope, scopeId, body) => {
  const response = await apiClient.put(`/addons/${addonId}/state`, body, {
    params: { scope, scope_id: scopeId },
  });
  return response.data.data;
};

// Generic call to an addon's own endpoint, used by declarative panels.
// `path` is always relative to /addons/<id>/ -- the manifest validator
// already rejects absolute paths, and building the URL here rather than
// letting a panel supply one means a panel physically cannot reach a core
// endpoint even if validation were ever bypassed.
export const addonRequest = async (addonId, method, path, { params, data } = {}) => {
  const clean = String(path || '').replace(/^\/+/, '');
  const response = await apiClient.request({
    url: `/addons/${addonId}/${clean}`,
    method: (method || 'GET').toLowerCase(),
    params,
    data,
  });
  return response.data?.data;
};

// URL for a tier-2 component bundle. Not fetched through axios: the browser's
// dynamic import() needs a real URL, and the JWT travels as an HttpOnly cookie
// on the same origin anyway.
export const addonAssetUrl = (addonId, filename) =>
  `/api/addons/${addonId}/ui/${String(filename).replace(/^\/+/, '')}`;
