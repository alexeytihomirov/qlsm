import React, { useEffect, useState } from 'react';
import { Loader2, RotateCw } from 'lucide-react';
import ConfirmationModal from '../ConfirmationModal';
import { useNotification } from '../NotificationProvider';
import { getSystemInfo, requestRestart, waitForRestart } from '../../services/system';

/**
 * "Something needs a restart" warning, with the button that actually does it.
 *
 * Restarting is what makes a freshly installed addon real: addons register
 * during create_app(), and Flask cannot hot-add a blueprint to a live app.
 *
 * The button only appears where a restart is survivable. A dev run started by
 * run-dev.sh has nothing to bring the process back, so /api/system/info
 * reports restart_supported: false and the banner stays informational rather
 * than offering an action that would end qlsm.
 *
 * On success the page is reloaded rather than refetched: every context in the
 * app was populated by the process that just went away, so a clean reload is
 * both simpler and more honest than patching pieces of state.
 */
function RestartQlsmBanner({ message }) {
  const { showError } = useNotification();
  const [supported, setSupported] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [restarting, setRestarting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getSystemInfo()
      .then(info => { if (!cancelled) setSupported(Boolean(info?.restart_supported)); })
      .catch(() => { if (!cancelled) setSupported(false); });
    return () => { cancelled = true; };
  }, []);

  const handleRestart = async () => {
    setConfirmOpen(false);
    setRestarting(true);
    try {
      await requestRestart();
    } catch (err) {
      setRestarting(false);
      showError(err?.response?.data?.error?.message || 'Failed to request a restart.');
      return;
    }

    const back = await waitForRestart();
    if (back) {
      window.location.reload();
      return;
    }
    setRestarting(false);
    showError('QLSM did not answer within two minutes. Check the stack before retrying.');
  };

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
        onConfirm={handleRestart}
        title="Restart QLSM?"
        message={'The web interface and the background workers come back on freshly loaded code. Running background tasks are allowed to finish first, but the interface is unavailable for a few seconds. Game servers QLSM manages are not touched.'}
        confirmButtonText="Restart"
        confirmButtonVariant="warning"
      />
    </>
  );
}

export default RestartQlsmBanner;
