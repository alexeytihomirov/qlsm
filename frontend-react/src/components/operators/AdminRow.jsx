import React from 'react';
import { UserPlus, X } from 'lucide-react';

// One admin in the Owner & Admins list. `row` comes from useInstanceAdmins:
// {steamId, level}. The directory only supplies a display name -- a
// SteamID missing from it is shown as itself, never as "Unknown operator".
//
// The row carries a data-testid of `admin-row-<steamId>` so a sibling test can
// target it directly instead of matching text fragmented across the name and
// SteamID spans (e.g. `getByTestId('admin-row-76561198012345678')`).
function AdminRow({ row, operator, onRemove, onAddToDirectory, disabled = false }) {
  return (
    <li
      data-testid={`admin-row-${row.steamId}`}
      className="flex items-center justify-between gap-2 rounded-md bg-[var(--surface-base)] px-2.5 py-1.5 text-sm"
    >
      <span className="min-w-0 truncate text-[var(--text-primary)]">
        {/* The name gets its own span so getByText('Vex') can match it -- as a
            bare text node it normalizes to "Vex76561198012345678lvl 3". */}
        {operator ? <span>{operator.name}</span> : <span className="font-mono">{row.steamId}</span>}
        {operator && <span className="ml-2 font-mono text-xs text-[var(--text-muted)]">{row.steamId}</span>}
        <span className="ml-2 text-xs text-[var(--text-muted)]">lvl {row.level}</span>
      </span>
      <span className="flex flex-shrink-0 items-center gap-2">
        {!operator && onAddToDirectory && (
          <button type="button" onClick={() => onAddToDirectory(row.steamId)}
                  className="flex items-center gap-1 text-xs text-[var(--accent-primary)] hover:underline">
            <UserPlus size={12} /> Add to operators
          </button>
        )}
        {onRemove && (
          <button type="button" onClick={() => onRemove(row.steamId)} title="Remove admin"
                  aria-label="Remove admin" disabled={disabled}
                  className="text-[var(--text-muted)] hover:text-[var(--accent-danger)] disabled:opacity-40">
            <X size={14} />
          </button>
        )}
      </span>
    </li>
  );
}

export default AdminRow;
