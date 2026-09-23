// qlsm's own process-level API (/api/system/...), as opposed to the game
// servers it manages. Kept beside services/addons.js for the same reason:
// one small URL prefix, and api.js is already large.
import apiClient from './api';

export const getSystemInfo = async () => {
  const response = await apiClient.get('/system/info');
  return response.data.data;
};

export const requestRestart = async () => {
  const response = await apiClient.post('/system/restart');
  return response.data;
};

/**
 * Resolve once qlsm answers again after a restart.
 *
 * Polls the unauthenticated ping endpoint the container healthcheck already
 * uses. The first few calls are expected to fail while the worker is being
 * replaced, so errors are ignored until the deadline.
 */
export const waitForRestart = async ({
  timeoutMs = 120000,
  intervalMs = 2000,
  // Gives the process time to actually go down. Without it the very first
  // poll can hit the still-running old worker and report success immediately.
  initialDelayMs = 3000,
} = {}) => {
  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  await sleep(initialDelayMs);

  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await apiClient.get('/instances/ping');
      return true;
    } catch {
      await sleep(intervalMs);
    }
  }
  return false;
};
