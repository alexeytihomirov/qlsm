import React, { useEffect, useMemo, useState } from 'react';
import { Crown, ShieldPlus, X, ExternalLink } from 'lucide-react';
import { getOperators } from '../../services/api';
import { setOperatorsCache } from '../../utils/operatorsCache';
import {
  readOwnerFromConfig,
  writeOwnerToConfig,
  parseAdminEntries,
  upsertAdminLine,
  removeAdminLine,
} from '../../utils/operatorConfigSync';
import OperatorCombobox from './OperatorCombobox';

// Structured Owner/Admins controls layered on top of the raw server.cfg
// (qlx_owner) and access.txt (steamid|level) text files, so operators added
// in Settings -> Operators can be assigned without hand-editing those files.
function OwnerAdminEditor({ serverCfgContent, accessTxtContent, onServerCfgChange, onAccessTxtChange }) {
  const [operators, setOperators] = useState([]);
  const [pendingAdmin, setPendingAdmin] = useState('');
  const [pendingLevel, setPendingLevel] = useState('5');

  useEffect(() => {
    let cancelled = false;
    getOperators()
      .then((data) => {
        if (cancelled) return;
        const list = data || [];
        setOperators(list);
        setOperatorsCache(list);
      })
      .catch(() => {
        if (!cancelled) setOperators([]);
      });
    return () => { cancelled = true; };
  }, []);

  const operatorsById = useMemo(() => {
    const map = new Map();
    operators.forEach((op) => map.set(op.steam_id64, op));
    return map;
  }, [operators]);

  const ownerSteamId = readOwnerFromConfig(serverCfgContent);
  const adminEntries = useMemo(() => parseAdminEntries(accessTxtContent), [accessTxtContent]);

  const handleOwnerChange = (steamId) => {
    onServerCfgChange(writeOwnerToConfig(serverCfgContent, steamId));
  };

  const handleAddAdmin = () => {
    if (!pendingAdmin) return;
    onAccessTxtChange(upsertAdminLine(accessTxtContent, pendingAdmin, pendingLevel));
    setPendingAdmin('');
    setPendingLevel('5');
  };

  const handleRemoveAdmin = (steamId) => {
    onAccessTxtChange(removeAdminLine(accessTxtContent, steamId));
  };

  return (
    <div className="rounded-xl border border-[var(--surface-border)] bg-[var(--surface-elevated)] p-4 mb-4">
      <div className="flex items-center justify-between mb-3">
        <span className="font-display text-xs font-semibold tracking-wider uppercase text-[var(--text-secondary)]">
          Owner &amp; Admins
        </span>
        <a
          href="/settings/operators"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-xs text-[var(--accent-primary)] hover:underline"
        >
          Manage operators <ExternalLink size={12} />
        </a>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {/* Owner */}
        <div>
          <label className="label-tech mb-1.5 flex items-center gap-1.5">
            <Crown size={14} />
            Owner
          </label>
          <OperatorCombobox
            value={ownerSteamId}
            onChange={handleOwnerChange}
            operators={operators}
            placeholder="Select owner…"
          />
          <p className="mt-1 text-xs text-[var(--text-muted)]">
            Writes <code className="text-[var(--text-secondary)]">qlx_owner</code> in server.cfg.
          </p>
        </div>

        {/* Admins */}
        <div>
          <label className="label-tech mb-1.5 flex items-center gap-1.5">
            <ShieldPlus size={14} />
            Admins
          </label>
          <div className="flex gap-2">
            <div className="flex-1 min-w-0">
              <OperatorCombobox
                value={pendingAdmin}
                onChange={setPendingAdmin}
                operators={operators.filter((op) => !adminEntries.some((e) => e.steamId === op.steam_id64))}
                placeholder="Add operator as admin…"
                allowClear={false}
              />
            </div>
            <div className="w-16 flex-shrink-0">
              <select
                value={pendingLevel}
                onChange={(e) => setPendingLevel(e.target.value)}
                className="input-base"
              >
                {[0, 1, 2, 3, 4, 5].map((lvl) => (
                  <option key={lvl} value={lvl}>{lvl}</option>
                ))}
              </select>
            </div>
            <button
              type="button"
              onClick={handleAddAdmin}
              disabled={!pendingAdmin}
              className="btn btn-secondary flex-shrink-0 px-3"
            >
              Add
            </button>
          </div>

          {adminEntries.length > 0 && (
            <ul className="mt-2 space-y-1">
              {adminEntries.map((entry) => {
                const operator = operatorsById.get(entry.steamId);
                return (
                  <li
                    key={entry.steamId}
                    className="flex items-center justify-between gap-2 rounded-md bg-[var(--surface-base)] px-2.5 py-1.5 text-sm"
                  >
                    <span className="truncate">
                      {operator ? operator.name : <span className="italic text-[var(--text-muted)]">Unknown operator</span>}
                      <span className="ml-2 font-mono text-xs text-[var(--text-muted)]">{entry.steamId}</span>
                      <span className="ml-2 text-xs text-[var(--text-muted)]">lvl {entry.level}</span>
                    </span>
                    <button
                      type="button"
                      onClick={() => handleRemoveAdmin(entry.steamId)}
                      className="text-[var(--text-muted)] hover:text-[var(--accent-danger)] flex-shrink-0"
                      title="Remove admin"
                    >
                      <X size={14} />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="mt-1 text-xs text-[var(--text-muted)]">
            Writes <code className="text-[var(--text-secondary)]">steamid|level</code> lines in access.txt.
          </p>
        </div>
      </div>
    </div>
  );
}

export default OwnerAdminEditor;
