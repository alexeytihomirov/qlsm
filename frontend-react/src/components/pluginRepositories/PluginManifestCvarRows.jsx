import { Plus, Trash2 } from 'lucide-react';
import { KNOWN_CVAR_TYPES } from '../../utils/pluginManifestValidation';
import { defaultForCvarType } from '../../utils/pluginManifestDraft';

/**
 * The cvar list for the selected plugin.
 *
 * Every text field is bound with `|| ''`. A cvar reaches this editor exactly
 * as it sat in the repository's qlsm-plugins.json -- fetch_manifest() only
 * checks that `cvars` is a list and never fills in the dicts inside it -- so
 * an entry that declares no `label` or `description` would otherwise hand
 * React `undefined` and turn that input uncontrolled.
 */
function PluginManifestCvarRows({ cvars, onAdd, onUpdate, onRemove }) {
  const rows = cvars || [];

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="label-tech">Cvars ({rows.length})</span>
        <button type="button" onClick={onAdd} className="btn btn-secondary !px-2.5 !py-1 !text-xs">
          <Plus className="w-3.5 h-3.5" /> Add Cvar
        </button>
      </div>
      <div className="space-y-2">
        {rows.map((c, j) => {
          // A type the settings form doesn't know about is kept as a visible
          // option of its own rather than silently displayed as "string" --
          // the validator warns about it, and the select has to agree.
          const typeValue = c.type || '';
          const isKnownType = KNOWN_CVAR_TYPES.includes(typeValue);
          return (
            <div key={c._key} className="border border-[var(--surface-border)] rounded-lg p-3 space-y-2">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                <input
                  className="input-base font-mono text-xs" placeholder="cvar" value={c.cvar || ''}
                  onChange={(e) => onUpdate(j, { cvar: e.target.value })}
                />
                <input
                  className="input-base text-xs" placeholder="label" value={c.label || ''}
                  onChange={(e) => onUpdate(j, { label: e.target.value })}
                />
                <select
                  className="input-base text-xs" value={typeValue}
                  aria-label="Cvar type"
                  onChange={(e) => onUpdate(j, {
                    type: e.target.value || undefined,
                    default: defaultForCvarType(e.target.value),
                  })}
                >
                  <option value="">not set</option>
                  {KNOWN_CVAR_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                  {!isKnownType && typeValue && (
                    <option value={typeValue}>{typeValue} (unrecognized)</option>
                  )}
                </select>
                {c.type === 'bool' ? (
                  <label className="flex items-center gap-2 text-xs px-1">
                    <input
                      type="checkbox" checked={!!c.default}
                      onChange={(e) => onUpdate(j, { default: e.target.checked })}
                    />
                    default
                  </label>
                ) : (
                  <input
                    className="input-base font-mono text-xs"
                    type={c.type === 'number' ? 'number' : 'text'}
                    placeholder="default"
                    value={c.default ?? ''}
                    onChange={(e) => onUpdate(j, {
                      default: c.type === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value,
                    })}
                  />
                )}
              </div>
              <div className="flex gap-2 items-start">
                <textarea
                  className="input-base text-xs flex-1" rows={1} placeholder="description" value={c.description || ''}
                  onChange={(e) => onUpdate(j, { description: e.target.value })}
                />
                <button type="button" onClick={() => onRemove(j)} className="btn btn-secondary !px-2 !py-1 flex-shrink-0">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          );
        })}
        {rows.length === 0 && (
          <p className="text-xs text-[var(--text-muted)]">No cvars.</p>
        )}
      </div>
    </div>
  );
}

export default PluginManifestCvarRows;
