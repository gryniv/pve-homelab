// Ordering of dashboard lists (web services, systems) per user.
// prefs.sort[kind]: 'manual' (prefs.order[kind] holds keys), 'name', or 'status' (running first).

import { locale } from './i18n.js';

export const KINDS = {
  services: { key: (s) => s.key, name: (s) => s.name, running: (s) => s.status === 'running' },
  systems: { key: (v) => String(v.vmid), name: (v) => v.name, running: (v) => v.status === 'running' },
};

export function arrange(kind, list, prefs) {
  const k = KINDS[kind];
  const mode = prefs.sort?.[kind] || 'manual';
  const byName = (a, b) => k.name(a).localeCompare(k.name(b), locale());
  if (mode === 'name') return [...list].sort(byName);
  if (mode === 'status') return [...list].sort((a, b) => (k.running(b) - k.running(a)) || byName(a, b));
  const pos = new Map((prefs.order?.[kind] || []).map((key, i) => [String(key), i]));
  return list.map((x, i) => [x, i])
    .sort(([a, ia], [b, ib]) => (pos.get(k.key(a)) ?? 1e6 + ia) - (pos.get(k.key(b)) ?? 1e6 + ib))
    .map(([x]) => x);
}

// New manual order after moving `key` by `delta` places, or right before `beforeKey`.
export function moved(kind, list, prefs, key, { delta = 0, beforeKey = null } = {}) {
  const k = KINDS[kind];
  const keys = arrange(kind, list, prefs).map(k.key);
  const from = keys.indexOf(String(key));
  if (from < 0) return null;
  keys.splice(from, 1);
  let to = beforeKey != null ? keys.indexOf(String(beforeKey)) : from + delta;
  if (to < 0) to = beforeKey != null ? keys.length : 0;
  to = Math.max(0, Math.min(keys.length, to));
  keys.splice(to, 0, String(key));
  return keys;
}
