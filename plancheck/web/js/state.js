/** Tiny reactive store. No framework. */

const listeners = new Set();

let state = {
  tab: "upload",
  projectId: null,
  project: null,
  model: null,
  drawings: [],
  standards: [],
  job: null,
};

export function get() {
  return state;
}

export function set(patch) {
  state = { ...state, ...patch };
  for (const fn of listeners) fn(state);
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
