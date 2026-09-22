import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, XCircle } from 'lucide-react';
import AddonField from './AddonField';
import { addonRequest, getAddonState, updateAddonState } from '../../services/addons';
import {
  initialValues, normalizeFields, resolveRoute, serializeValues, validateValues,
} from './panelRoute';

/**
 * The `form` panel kind.
 *
 * Two modes, and the distinction matters:
 *
 *  - **Managed** (panel declares no `load`): values live in core's own
 *    AddonState table and are read/written through /addons/<id>/state. An
 *    addon with nothing but a manifest gets a working settings screen for
 *    free -- no backend code at all.
 *  - **Custom** (panel declares `load`): the addon serves its own payload.
 *    Needed whenever the values are not just stored settings, e.g. a live
 *    reachability probe an addon runs against its own backend.
 */
function StatusBadge({ state }) {
  if (!state) return null;
  if (state.loading) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-theme-muted">
        <Loader2 size={13} className="animate-spin" /> Checking...
      </span>
    );
  }
  if (state.error) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium" style={{ color: 'var(--accent-danger)' }}>
        <XCircle size={13} /> {state.error}
      </span>
    );
  }
  const payload = state.data || {};
  const ok = payload.ok ?? payload.reachable ?? payload.healthy;
  const text = payload.label || payload.message || (ok ? 'OK' : 'Unavailable');
  if (ok) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-400">
        <CheckCircle2 size={13} /> {text}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-theme-muted">
      <AlertTriangle size={13} /> {text}
    </span>
  );
}

function AddonFormPanel({ addon, panel, scope, scopeId }) {
  const managed = !panel?.load;
  const fields = normalizeFields(
    managed ? (addon.settings_schema?.[scope] || []) : panel.fields,
  );

  const [values, setValues] = useState(() => initialValues(fields, null));
  const [enabled, setEnabled] = useState(false);
  const [effective, setEffective] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [errors, setErrors] = useState({});
  const [status, setStatus] = useState(null);

  const context = { scope, scopeId, addonId: addon.id };

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      if (managed) {
        const state = await getAddonState(addon.id, scope, scopeId);
        setValues(initialValues(fields, state.settings));
        setEnabled(Boolean(state.enabled));
        setEffective(Boolean(state.effective));
      } else {
        const route = resolveRoute(panel.load, context);
        const data = await addonRequest(addon.id, route.method, route.path);
        setValues(initialValues(fields, data));
      }
    } catch (err) {
      setLoadError(err?.response?.data?.error?.message || 'Failed to load');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addon.id, scope, scopeId, managed, panel?.load]);

  const loadStatus = useCallback(async () => {
    if (!panel?.status?.load) return;
    setStatus({ loading: true });
    try {
      const route = resolveRoute(panel.status.load, context);
      setStatus({ data: await addonRequest(addon.id, route.method, route.path) });
    } catch (err) {
      setStatus({ error: err?.response?.data?.error?.message || 'Unreachable' });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addon.id, scope, scopeId, panel?.status?.load]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadStatus(); }, [loadStatus]);

  const handleChange = (key, value) => {
    setValues(prev => ({ ...prev, [key]: value }));
    setSaved(false);
    setErrors(prev => (prev[key] ? { ...prev, [key]: undefined } : prev));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const found = validateValues(fields, values);
    if (Object.keys(found).length) {
      setErrors(found);
      return;
    }
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      const payload = serializeValues(fields, values);
      if (managed) {
        const state = await updateAddonState(addon.id, scope, scopeId, {
          settings: payload, enabled,
        });
        setEffective(Boolean(state.effective));
      } else {
        const route = resolveRoute(panel.submit || panel.load, context);
        await addonRequest(addon.id, route.method === 'GET' ? 'PUT' : route.method, route.path, {
          data: payload,
        });
      }
      setSaved(true);
      loadStatus();
    } catch (err) {
      setSaveError(err?.response?.data?.error?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm text-theme-muted">
        <Loader2 size={15} className="animate-spin" /> Loading...
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="py-4">
        <p className="text-sm" style={{ color: 'var(--accent-danger)' }}>{loadError}</p>
        <button type="button" onClick={load}
                className="mt-2 inline-flex items-center gap-1.5 text-xs text-theme-secondary hover:text-theme-primary">
          <RefreshCw size={13} /> Retry
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-1">
      {(panel?.description || status) && (
        <div className="flex items-start justify-between gap-4 pb-2">
          <p className="text-sm text-theme-secondary">{panel?.description}</p>
          <StatusBadge state={status} />
        </div>
      )}

      {managed && (
        <div className="mb-2 rounded-md border p-3" style={{ borderColor: 'var(--surface-border)' }}>
          <label className="flex items-center gap-3 cursor-pointer">
            <input type="checkbox" checked={enabled} className="h-4 w-4"
                   onChange={(e) => { setEnabled(e.target.checked); setSaved(false); }} />
            <span className="text-sm text-theme-primary">Enabled for this {scope}</span>
          </label>
          {/* The layered rule made visible: without this the operator ticks a
              box, saves successfully, and nothing happens -- with no clue why. */}
          {enabled && !effective && (
            <p className="mt-1.5 pl-7 text-xs" style={{ color: 'var(--accent-warning, #d97706)' }}>
              Switched on here, but still inactive: enable this addon at the level above first.
            </p>
          )}
        </div>
      )}

      {fields.length === 0 && (
        <p className="py-2 text-sm text-theme-muted">This addon declares no settings for this scope.</p>
      )}

      {fields.map(field => (
        <AddonField key={field.key} field={field} value={values[field.key]}
                    error={errors[field.key]} disabled={saving} onChange={handleChange} />
      ))}

      {saveError && (
        <p className="pt-2 text-sm" style={{ color: 'var(--accent-danger)' }}>{saveError}</p>
      )}

      <div className="flex items-center gap-3 pt-3">
        <button type="submit" disabled={saving}
                className="btn-primary inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium disabled:opacity-50">
          {saving && <Loader2 size={14} className="animate-spin" />}
          Save
        </button>
        {saved && <span className="text-xs text-emerald-400">Saved</span>}
      </div>
    </form>
  );
}

export default AddonFormPanel;
