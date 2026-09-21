import { Plus, Trash2 } from 'lucide-react';

/**
 * The command list for the selected plugin. Same `|| ''` binding rule as
 * PluginManifestCvarRows: a command entry arrives exactly as the repository
 * wrote it, so `name` and `description` can both be missing.
 */
function PluginManifestCommandRows({ commands, onAdd, onUpdate, onRemove }) {
  const rows = commands || [];

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="label-tech">Commands ({rows.length})</span>
        <button type="button" onClick={onAdd} className="btn btn-secondary !px-2.5 !py-1 !text-xs">
          <Plus className="w-3.5 h-3.5" /> Add Command
        </button>
      </div>
      <div className="space-y-2">
        {rows.map((c, j) => (
          <div key={c._key} className="border border-[var(--surface-border)] rounded-lg p-3 space-y-2">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <input
                className="input-base font-mono text-xs" placeholder="name" value={c.name || ''}
                onChange={(e) => onUpdate(j, { name: e.target.value })}
              />
              <input
                className="input-base font-mono text-xs" placeholder="usage" value={c.usage || ''}
                onChange={(e) => onUpdate(j, { usage: e.target.value })}
              />
              <input
                className="input-base font-mono text-xs" type="number" min={0} max={5} placeholder="permission"
                aria-label="Command permission"
                value={c.permission ?? ''}
                onChange={(e) => onUpdate(j, {
                  permission: e.target.value === '' ? undefined : Number(e.target.value),
                })}
              />
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
        ))}
        {rows.length === 0 && (
          <p className="text-xs text-[var(--text-muted)]">No commands.</p>
        )}
      </div>
    </div>
  );
}

export default PluginManifestCommandRows;
