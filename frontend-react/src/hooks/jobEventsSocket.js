import { io } from 'socket.io-client';

// Separate connection from rconSocketTransport.js's on-demand RCON socket:
// job-completion toasts need to be live for as long as the app is open, not
// only while an RCON console happens to be mounted. Same shared-per-tab,
// not-HMR-safe caveat applies (see rconSocketTransport.js).
const SOCKET_URL = import.meta.env.VITE_API_BASE_URL || '';

let socket = null;
let users = 0;

export function acquireJobEventsSocket() {
  if (!socket) {
    socket = io(SOCKET_URL, {
      withCredentials: true,
      transports: import.meta.env.DEV ? ['polling'] : ['websocket', 'polling'],
      upgrade: !import.meta.env.DEV,
      reconnection: true,
      reconnectionDelay: 1000,
    });
  }
  users += 1;
  return socket;
}

export function releaseJobEventsSocket() {
  if (users === 0) return;
  users -= 1;
  if (users > 0 || !socket) return;
  socket.disconnect();
  socket = null;
}

export function resetJobEventsSocketForTests() {
  users = 0;
  if (socket) {
    socket.removeAllListeners?.();
    socket.disconnect();
    socket = null;
  }
}
