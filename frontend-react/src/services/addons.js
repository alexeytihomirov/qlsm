// Addon API client.
//
// Kept out of services/api.js on purpose: everything here talks to a single
// URL prefix (/api/addons/...) that core owns and no addon can escape, and
// api.js is already ~1200 lines of per-resource functions.
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
//
// Unwraps the response body's top-level `data` key by default -- every
// declarative panel route follows that `{"data": ...}` convention. Pass
// `raw: true` for a route whose body carries sibling fields alongside
// `data` (the `live_status_columns` contract's `{"data": ..., "configured":
// ...}` is the one case today -- unwrapping there would silently discard
// `configured` and hand the caller `undefined`, which read as "not false"
// and made every column look configured with empty data regardless of what
// the source actually reported).
export const addonRequest = async (addonId, method, path, { params, data, raw } = {}) => {
  const clean = String(path || '').replace(/^\/+/, '');
  const response = await apiClient.request({
    url: `/addons/${addonId}/${clean}`,
    method: (method || 'GET').toLowerCase(),
    params,
    data,
  });
  return raw ? response.data : response.data?.data;
};

/**
 * True when an asset path stays inside the addon's own `ui/` directory.
 *
 * Mirrors the backend's `_escapes_addon_dir` (ui/addons/manifest.py), and is
 * needed separately from it because not every path that reaches
 * `addonAssetUrl` comes from a manifest: a `live_status_columns` cell's
 * `icon_url` arrives in the addon's own JSON *response*, which the manifest
 * validator never sees. Stripping leading slashes was not enough -- the
 * browser collapses dot segments, so `../../../hosts/1/x` from a response
 * became a credentialed same-origin GET on a core endpoint, once per player
 * on every poll.
 *
 * `%` is rejected outright: `%2e%2e` and `..%2f` are a `..` segment to a URL
 * parser, and no legitimate asset filename here needs percent-encoding.
 *
 * Control and whitespace characters are rejected the same way: a URL parser
 * strips them before it looks at dot segments, so `".\t./.\t./hosts"` reaches
 * it as `"../../hosts"` even though the split-on-`/` segment check below
 * never sees a bare `.` or `..`.
 */
export function isSafeAddonAssetPath(filename) {
  if (typeof filename !== 'string' || !filename.trim()) return false;
  if (/[%?#\\\x00-\x20\x7f]/.test(filename)) return false;
  const path = filename.replace(/^\/+/, '');
  if (!path) return false;
  return !path.split('/').some((segment) => segment === '' || segment === '.' || segment === '..');
}

// URL for a tier-2 component bundle or a manifest/response-declared icon, or
// null when the path is not one the addon is allowed to ask for. Not fetched
// through axios: the browser's dynamic import() needs a real URL, and the JWT
// travels as an HttpOnly cookie on the same origin anyway.
export const addonAssetUrl = (addonId, filename) => {
  if (!isSafeAddonAssetPath(filename)) return null;
  return `/api/addons/${addonId}/ui/${String(filename).replace(/^\/+/, '')}`;
};

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
