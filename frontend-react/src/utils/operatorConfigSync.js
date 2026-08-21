// Read/write the owner (qlx_owner in server.cfg) and admins (access.txt lines,
// "steamid|level") for the structured Owner/Admins controls. Mirrors the
// existing sv_hostname <-> server.cfg sync pattern (see serverCfgCvars.js).
import { readCvarFromConfig, upsertCvarInConfig } from './serverCfgCvars';

export const STEAMID64_RE = /^7656119\d{10}$/;

export function readOwnerFromConfig(serverCfgText) {
  return readCvarFromConfig(serverCfgText, 'qlx_owner') || '';
}

export function writeOwnerToConfig(serverCfgText, steamId64) {
  return upsertCvarInConfig(serverCfgText, 'qlx_owner', steamId64 || '');
}

// Parses access.txt into admin entries, skipping blank lines and comments.
// Preserves the original line so unrelated formatting/comments are untouched.
export function parseAdminEntries(accessText) {
  const lines = (accessText || '').split('\n');
  const entries = [];
  lines.forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) return;
    const [idPart, ...rest] = trimmed.split('|');
    const steamId = (idPart || '').trim();
    if (!STEAMID64_RE.test(steamId)) return;
    const levelPart = (rest.join('|') || '').split('#')[0].trim();
    entries.push({ steamId, level: levelPart, lineIndex: index });
  });
  return entries;
}

// Adds or updates a "steamid|level" line. If the SteamID is already present,
// its level is updated in place; otherwise a new line is appended.
export function upsertAdminLine(accessText, steamId64, level) {
  const text = accessText || '';
  const lines = text.length ? text.split('\n') : [];
  const line = `${steamId64}|${level}`;
  const existingIndex = lines.findIndex((raw) => {
    const trimmed = raw.trim();
    if (!trimmed || trimmed.startsWith('#')) return false;
    const idPart = trimmed.split('|')[0].trim();
    return idPart === steamId64;
  });
  if (existingIndex >= 0) {
    lines[existingIndex] = line;
    return lines.join('\n');
  }
  if (lines.length === 0 || lines[lines.length - 1].trim() === '') {
    lines[lines.length - 1] = line;
    return lines.join('\n');
  }
  lines.push(line);
  return lines.join('\n');
}

// Removes every line whose SteamID matches, preserving all other lines
// (including comments and unrelated entries) as-is.
export function removeAdminLine(accessText, steamId64) {
  const text = accessText || '';
  const lines = text.split('\n');
  const filtered = lines.filter((raw) => {
    const trimmed = raw.trim();
    if (!trimmed || trimmed.startsWith('#')) return true;
    const idPart = trimmed.split('|')[0].trim();
    return idPart !== steamId64;
  });
  return filtered.join('\n');
}
