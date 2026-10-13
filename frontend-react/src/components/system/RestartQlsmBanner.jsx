import React, { useState } from 'react';
import { Loader2, RotateCw } from 'lucide-react';
import ConfirmationModal from '../ConfirmationModal';
import { RESTART_CONFIRM_MESSAGE, useQlsmRestart } from '../../hooks/useQlsmRestart';

/**
 * "Something needs a restart" warning, with the button that actually does it.
 * The button only appears where a restart is survivable; see useQlsmRestart.
 */
function RestartQlsmBanner({ message }) {
  const { supported, restarting, restart } = useQlsmRestart();
  const [confirmOpen, setConfirmOpen] = useState(false);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border p-3 text-sm"
           style={{ borderColor: 'var(--accent-warning, #d97706)' }}>
        <span>{message}</span>
        {supported && (
          <button type="button" onClick={() => setConfirmOpen(true)} disabled={restarting}
                  className="btn btn-secondary inline-flex flex-shrink-0 items-center gap-1.5 disabled:opacity-60">
            {restarting
              ? <><Loader2 size={14} className="animate-spin" /> Restarting...</>
              : <><RotateCw size={14} /> Restart QLSM</>}
          </button>
        )}
      </div>

      <ConfirmationModal
        isOpen={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={restart}
        title="Restart QLSM?"
        message={RESTART_CONFIRM_MESSAGE}
        confirmButtonText="Restart"
        confirmButtonVariant="warning"
      />
    </>
  );
}

export default RestartQlsmBanner;
