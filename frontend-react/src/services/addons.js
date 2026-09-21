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

export const installAddon = async (file) => {
  const form = new FormData();
  form.append('file', file);
  // Content-Type is left unset on purpose: the browser has to add the
  // multipart boundary itself, and apiClient's JSON default would break it.
  const response = await apiClient.post('/addons/install', form, {
    headers: { 'Content-Type': undefined },
  });
  return response.data.data;
};

export const uninstallAddon = async (addonId) => {
  const response = await apiClient.delete(`/addons/${addonId}`);
  return response.data.data;
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

/** Filename from a Content-Disposition header, or null. */
export function filenameFromDisposition(disposition) {
  if (typeof disposition !== 'string') return null;
  const star = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (star) {
    try {
      return decodeURIComponent(star[1]);
    } catch {
      return star[1];
    }
  }
  const plain = disposition.match(/filename="?([^";]+)"?/i);
  return plain ? plain[1] : null;
}

/**
 * Fetch a file from an addon endpoint and hand it to the browser.
 *
 * A blob round-trip rather than pointing a link at the URL, for two reasons:
 * it keeps the CSRF header and 401 interceptor that apiClient installs, and it
 * works for POST endpoints too (the batch download returns a zip built from a
 * posted selection). Same approach the built-in Demos modal already uses.
 *
 * An error response also arrives as a blob, so it is read back into JSON --
 * otherwise a failed download shows "[object Blob]" instead of the reason.
 */
export const addonDownload = async (addonId, method, path, { params, data, fallbackName } = {}) => {
  const clean = String(path || '').replace(/^\/+/, '');
  try {
    const response = await apiClient.request({
      url: `/addons/${addonId}/${clean}`,
      method: (method || 'GET').toLowerCase(),
      params,
      data,
      responseType: 'blob',
    });
    const name = filenameFromDisposition(response.headers?.['content-disposition'])
      || fallbackName || 'download';
    return { blob: response.data, filename: name };
  } catch (error) {
    const blob = error?.response?.data;
    if (blob && typeof blob.text === 'function') {
      try {
        const parsed = JSON.parse(await blob.text());
        const message = parsed?.error?.message;
        if (message) throw new Error(message);
      } catch (parseError) {
        if (parseError instanceof Error && parseError.message && !(parseError instanceof SyntaxError)) {
          throw parseError;
        }
      }
    }
    throw error;
  }
};

/** Save a blob under `filename` using a temporary object URL. */
export function saveBlob(blob, filename) {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}
