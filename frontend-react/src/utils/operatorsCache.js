// Tiny module-level cache of the operator directory, refreshed whenever
// OwnerAdminEditor (or the Operators settings page) fetches the list.
// Lets the access.txt CodeMirror autocomplete (codemirror-lang-qlaccess.js)
// suggest known operators without threading the list through every editor
// prop chain (CodeMirrorEditor only takes language/linterSource today).
let operators = [];
const listeners = new Set();

export function setOperatorsCache(list) {
  operators = Array.isArray(list) ? list : [];
  listeners.forEach((listener) => listener(operators));
}

export function getOperatorsCache() {
  return operators;
}

export function subscribeOperatorsCache(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
