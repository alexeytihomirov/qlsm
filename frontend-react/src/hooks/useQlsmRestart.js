import { useEffect, useState } from 'react';
import { useNotification } from '../components/NotificationProvider';
import { getSystemInfo, requestRestart, waitForRestart } from '../services/system';

// What a restart does, for the confirmation every restart control raises.
export const RESTART_CONFIRM_MESSAGE = 'The web interface and the background workers come back on freshly loaded code. Running background tasks are allowed to finish first, but the interface is unavailable for a few seconds. Game servers QLSM manages are not touched.';

/**
 * State and action behind every "restart QLSM" control.
 *
 * Restarting is what makes a freshly installed addon real: addons register
 * during create_app(), and Flask cannot hot-add a blueprint to a live app.
 *
 * `supported` is false where a restart would not be survivable. A dev run
 * started by run-dev.sh has nothing to bring the process back, so
 * /api/system/info reports restart_supported: false and callers must stay
 * informational rather than offer an action that would end qlsm.
 *
 * On success the page is reloaded rather than refetched: every context in the
 * app was populated by the process that just went away, so a clean reload is
 * both simpler and more honest than patching pieces of state.
 */
export function useQlsmRestart() {
  const { showError } = useNotification();
  const [supported, setSupported] = useState(false);
  const [restarting, setRestarting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getSystemInfo()
      .then(info => { if (!cancelled) setSupported(Boolean(info?.restart_supported)); })
      .catch(() => { if (!cancelled) setSupported(false); });
    return () => { cancelled = true; };
  }, []);

  const restart = async () => {
    setRestarting(true);
    let previousBootId;
    try {
      // Read now, not at mount: it is what tells the new process apart from
      // the one we are about to replace.
      previousBootId = (await getSystemInfo())?.boot_id;
      await requestRestart();
    } catch (err) {
      setRestarting(false);
      showError(err?.response?.data?.error?.message || 'Failed to request a restart.');
      return;
    }

    const back = await waitForRestart(previousBootId);
    if (back) {
      window.location.reload();
      return;
    }
    setRestarting(false);
    showError('QLSM did not answer within two minutes. Check the stack before retrying.');
  };

  return { supported, restarting, restart };
}
