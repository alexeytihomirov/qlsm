// Mirrors MAX_INSTANCES_PER_HOST in ui/constants.py. The backend is
// authoritative -- this only drives the disabled state and the copy, so keep
// the two in sync when the backend limit changes.
export const MAX_INSTANCES_PER_HOST = 8;

// Hosts provisioned before the limit was raised had a firewall allow-list only
// wide enough for this many instances. Past this count, hosts whose firewall
// QLSM owns outright need host setup re-run before the extra ports are open.
// The advisory is gated on Host.firewall_pool_v2 being false, so a host set up
// on this version never shows it -- this threshold only suppresses the notice
// on legacy hosts that have not yet reached the point where it matters.
export const FIREWALL_REFRESH_INSTANCE_THRESHOLD = 4;
