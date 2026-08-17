// Mirrors ui/task_logic/zmq_utils.py -- the generator's alphabet. Anything
// wider risks being mangled by the shell, Ansible extra-vars, or Quake arg
// parsing on the way to systemd's ExecStart.
export const ZMQ_PASSWORD_MIN_LENGTH = 8;
export const ZMQ_PASSWORD_MAX_LENGTH = 64;

const ZMQ_PASSWORD_PATTERN = /^[A-Za-z0-9\-_=]+$/;

export function validateZmqPassword(value, label) {
  const trimmed = (value ?? '').trim();
  if (!trimmed) {
    return `${label} is required when Auto Generate Passwords is off.`;
  }
  if (trimmed.length < ZMQ_PASSWORD_MIN_LENGTH || trimmed.length > ZMQ_PASSWORD_MAX_LENGTH) {
    return `${label} must be between ${ZMQ_PASSWORD_MIN_LENGTH} and ${ZMQ_PASSWORD_MAX_LENGTH} characters.`;
  }
  if (!ZMQ_PASSWORD_PATTERN.test(trimmed)) {
    return `${label} may only contain letters, digits, and - _ =.`;
  }
  return null;
}
