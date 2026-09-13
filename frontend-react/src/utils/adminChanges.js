// What Save Configuration writes to Redis: only the admins the user changed in
// the Owner & Admins tab. Added or re-levelled -> the new level; removed -> 0.
// Anyone not touched is left out, so an in-game !setperm is never overwritten.
export function diffAdminLists(before, after) {
  const previous = new Map((before || []).map((e) => [e.steam_id64, Number(e.level)]));
  const next = new Map((after || []).map((e) => [e.steam_id64, Number(e.level)]));
  const changes = [];
  next.forEach((level, steamId) => {
    if (previous.get(steamId) !== level) changes.push({ steam_id64: steamId, level });
  });
  previous.forEach((_level, steamId) => {
    if (!next.has(steamId)) changes.push({ steam_id64: steamId, level: 0 });
  });
  return changes;
}
