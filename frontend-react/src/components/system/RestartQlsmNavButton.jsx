import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, RotateCw } from 'lucide-react';
import ConfirmationModal from '../ConfirmationModal';
import { useAddons } from '../../contexts/AddonsContext';
import { RESTART_CONFIRM_MESSAGE, useQlsmRestart } from '../../hooks/useQlsmRestart';

function PendingRestartControl() {
  const { supported, restarting, restart } = useQlsmRestart();
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Nothing here can restart a dev run (see useQlsmRestart), so the reminder
  // stays and leads to the page that says what is waiting.
  if (!supported) {
    return (
      <Link to="/addons" className="navbar-restart-btn" title="Some addon changes need a QLSM restart before they take effect.">
        <RotateCw size={16} strokeWidth={2} />
        <span>RESTART REQUIRED</span>
      </Link>
    );
  }

  return (
    <>
      <button type="button" onClick={() => setConfirmOpen(true)} disabled={restarting}
              className="navbar-restart-btn"
              title="Some addon changes need a QLSM restart before they take effect.">
        {restarting
          ? <><Loader2 size={16} strokeWidth={2} className="animate-spin" /><span>RESTARTING...</span></>
          : <><RotateCw size={16} strokeWidth={2} /><span>RESTART QLSM</span></>}
      </button>

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

/**
 * Navbar reminder that an addon change is still waiting for a restart.
 *
 * It lives in the navbar because the prompt raised right after an install can
 * be dismissed with "Later", and from then on the restart must stay one click
 * away on every page rather than only on the Addons page. Driven by the shared
 * addon catalog, so it survives a page reload and goes away by itself once the
 * restarted process reports nothing pending.
 */
function RestartQlsmNavButton() {
  const { addons } = useAddons();
  if (!addons.some(a => a.pending_restart)) return null;
  return <PendingRestartControl />;
}

export default RestartQlsmNavButton;
