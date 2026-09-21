# Rank Provider Integration — Design

Date: 2026-09-20
Status: Revised 2026-09-20 after a pre-implementation review loop, then again
the same day once Slipgate's own plugin was supplied and the two open decisions
were answered. **All open decisions are resolved — ready to implement.** See
the trailer at the bottom for the findings and assessment this revision folds
in.

## Problem

Different QLDS instances rank players through different external services —
qlstats (public API, used by the bundled minqlx `balance.py`), Slipgate
(`https://slipgate.gg/api/v1`, bearer-token auth), and a custom Thunderdome
`elo-service` (`X-API-Key` auth). QLSM's Live Status drawer currently shows
name/steamid/team/score/ping per connected player but no rating, and there is
no way to tell QLSM which rank service (if any) a given instance uses.

## Decisions locked during brainstorming

- **Display scope:** ELO appears only in the existing Live Status player
  table (`frontend-react/src/components/instances/LiveServerStatusModal.jsx`),
  as a new column. No separate leaderboard view.
- **Config scope:** Per QLDS instance. Each instance independently selects a
  provider (or none) and its own credentials, because different servers in
  the same QLSM install use different rank pools.
- **Fetch path:** Flask calls provider APIs directly over HTTP from the
  backend. No dependency on minqlx/RCON to obtain ratings — QLSM only needs
  each provider's own read API by steam ID(s).
- **Provider abstraction:** A shared `RankProvider` interface with one
  adapter class per provider (qlstats, Slipgate, Thunderdome elo-service),
  registered by a string `provider_type`. Adding a future provider is a new
  adapter module, not a schema or route change.
- **Config fields:** `provider_type`, `base_url`, optional `api_key`, plus
  `game_type` as its own column — but see "Game type is derived, not typed"
  below: `game_type` is an **optional override**, empty for most instances.
  Fields that don't fit go in a small provider-specific `extra` JSON blob
  rather than new columns, so a future provider's quirks never force a
  migration. `extra`'s first real tenant is qlstats' `elo` vs `elo_b`
  rating-system selector, and it ships with a write path through the `PUT` —
  a column that ships dead is the one genuinely wrong option.
- **Fetch cadence:** Cached/throttled independently of the Live Status poll
  rate. Ratings are fetched at most once per TTL window per instance and
  reused across all pollers/viewers, so an extra outbound HTTP call to a
  third-party service never rides on every Live Status refresh.

## Provider API shapes

All three providers are verified against a real client. qlstats and Thunderdome
elo-service against the in-repo plugins
(`configs/presets/_builtin/default-minqlxtended/scripts/balance.py` and
`.../ranked.py`); Slipgate against its own minqlxtended plugin, `slipgate.py`
v1.10.1, supplied by the operator and read at `slipgate (1).py` in the checkout
root (untracked — `.gitignore` is an allowlist). Line references in the Slipgate
row below are to that file. **Slipgate stays in the first slice** — the earlier
concern was that its shapes were unverifiable here, and they no longer are.

| Provider | Base URL | Auth | Single-player | Bulk/roster |
|---|---|---|---|---|
| qlstats | operator-set host plus a rating-system path segment: `http://<host>/<elo\|elo_b>/` (`balance.py:127-131`), plain `http://`, no TLS | none | `GET <base_url><steam_id>` | **supported** — `+`-joined into the path: `GET <base_url>a+b+c` (`balance.py:277`) |
| Slipgate | `https://slipgate.gg/api/v1`, trailing slash stripped (`:22`, `:244`) | `Authorization: Bearer <sgs_… token>` (`:456`) | `GET /players/{steam_id}/ratings/{code}` → `{display, tier_name, provisional, games}`; **`404` when the player is unranked** (`:2427`) | `POST /ratings/bulk` `{steam_ids, game_type}` → `{players: [{steam_id, display, tier_name, provisional, found}]}` (`:2496-2507`) |
| Thunderdome elo-service | operator-set, e.g. `http://host:5002` | `X-API-Key: <key>` — always sent when configured (the in-repo plugin sends it on writes only; sending it on reads is harmless if the read API ignores it) | `GET /player/{steam_id}?mode=ffa_auto` → `{name, mu, sort_score, wins, losses, rank, total_players}`; **`404` when the player is unranked** (`ranked.py:666`), not a null body | `GET /players?ids=a,b,c&mode=ffa_auto` → `{steam_id: {name, mu, sort_score, wins, losses} \| null}` |

**Rating source per provider — this is the value the adapter must read:**

- **qlstats:** the response is `{"players": [{"steamid": …, "<game_type>":
  {"elo": …, "games": …}}], "untracked": [...]}` (`balance.py:296-360`) — it is
  **keyed by game type**, so the adapter cannot pick a number without one.
  Read `players[i][<game_type>]["elo"]`; omit ids listed in `untracked` and ids
  absent from `players`. **Also omit a bucket where `elo == 0` and
  `games == 0`**: `balance.py:326-327` treats exactly that shape as "the API has
  nothing for this player" and substitutes `DEFAULT_RATING` (1500,
  `balance.py:46-47`). QLSM does **not** substitute 1500 — an in-game balancer
  needs a number to divide teams with, a read-only display does not, and an
  invented rating shown as if it came from qlstats is worse than a dash. Without
  the guard the cell renders a literal `0`, indistinguishable from a genuine
  rating and wrong under either reading.
- **Slipgate:** `display`, rendered whole and never parsed. The field is named
  `display`, not `rating`, and may well be a formatted label (`"1650 (Gold)"`)
  rather than a bare number — the adapter must not coerce it to a float or do
  arithmetic on it. Two distinct shapes both mean unranked and must be handled
  together (`:2542-2547`): a bulk entry with `found` false, **and** a bulk entry
  that is present with `display` null. Checking only one of the two renders a
  wrong cell for the other.

  QLSM only ever calls the **bulk** endpoint. The single-player path in the
  table above is recorded for reference and is not used by any adapter, and the
  plugin documents no `404` on the bulk `POST` — so an adapter's 404 branch on
  the bulk call is belt-and-braces, not a modelled case.
- **Thunderdome elo-service:** `sort_score or mu` (`ranked.py:466` bulk,
  `ranked.py:672` single). Python's `or`, literally: both call sites read
  `int(d.get("sort_score") or d["mu"])`, so a `sort_score` of `0` is treated as
  absent and `mu` is used. An `is None` check instead of `or` diverges exactly
  there, and QLSM would show `0` for a player whose in-game `!rating` shows a
  real number. There is **no `rating` key** on these two endpoints — an adapter
  that reads `rating` returns `None` for every player against a perfectly
  healthy service.

All three take steam_id(s) plus a game-type/mode string. qlstats and elo-service
return a number; Slipgate returns a tier label. The shared interface below
carries both (`display` for rendering, `rating` when a number exists).

## Game type is derived, not typed

Every mode has its own rating pool — a player's CA rating and CTF rating are
different numbers — so each lookup must name a mode. **QLSM derives it from the
live server rather than asking the admin to type it.**

The gametype is already on hand: Live Status renders it today
(`LiveServerStatusModal.jsx:272`, `InstanceDetailsModal.jsx:440`), so no new
plumbing is needed to read it. It follows the mode automatically across a
rotation, which a typed-in value cannot.

**Each adapter owns its own translation**, because the vocabularies differ.
QLSM's codes are `['ca', 'ctf', 'tdm', 'ft', 'ad', 'har', 'dom', 'ob', 'rr']`
(`InstanceDetailsModal.jsx:446`) while Slipgate wants the long forms
(`slipgate (1).py:124-134`):

`GAMETYPE_CODES` there holds **eleven** entries, so the mapping does too — four
that differ and seven that pass through:

| QLSM | Slipgate |
|---|---|
| `har` | `harvester` |
| `dom` | `domination` |
| `rr` | `redrover` |
| `1f` | `1flag` |
| `ca`, `ctf`, `tdm`, `ft`, `ffa`, `duel`, `ad` | unchanged |

One-flag CTF is the easiest of these to drop, and dropping it is not cheap: a
one-flag instance pointed at Slipgate would make no request at all and show a
permanently empty column. `1f` is the short code both runtimes actually produce
(`minqlx/_core.py:54-55`, `minqlxtended/_enums.py:357`). The longer spellings
`1fctf` and `ictf` listed in `LiveServerStatusModal.jsx:26` are speculative
aliases in a set whose own comment says "and common aliases" — no plugin emits
them, so they are deliberately **not** mapped.

Sending `har` to Slipgate returns nothing — no error, just an empty column,
which is precisely the undiagnosable-dashes failure this spec exists to avoid.
So the interface grows one method:

```python
def map_game_type(self, qlsm_gametype: str) -> str | None:
    """Provider's own code for this mode, or None when it isn't rated there."""
```

Returning `None` is a correct, quiet outcome: the mode genuinely has no ratings
(race, for instance), so the column is empty and no request is made.

**The `game_type` column survives as an override**, because derivation cannot
cover every provider. Thunderdome's elo-service takes `mode=ffa_auto`, a
service-specific pool name that corresponds to no QL gametype and can only come
from the operator. Resolution order per lookup:

1. `config.game_type` when non-empty → used verbatim, no mapping.
2. Otherwise `adapter.map_game_type(<live gametype>)`.
3. `None` from either → no request, empty column, not an error.

This leaves the field blank for qlstats and Slipgate and set to `ffa_auto` for
elo-service, so the UI presents it as an optional advanced field rather than
something every admin must get right.

## Architecture

```
Flask route (GET /api/instances/<id>/ranks)
        │
        ▼
RankService (ui/rank_providers/service.py)
   - loads RankProviderConfig for the instance
   - checks Redis cache (key: rank:ratings:{instance_id}:{config_fp}:{roster_fp}, TTL 60s)
   - on miss: calls the adapter, stores result, returns it
        │
        ▼
RankProvider adapters (ui/rank_providers/)
   base.py        — RankProvider ABC: fetch_ratings(steam_ids, game_type) -> dict
   qlstats.py      — QlstatsProvider
   slipgate.py     — SlipgateProvider
   elo_service.py  — ThunderdomeEloProvider
   registry.py     — PROVIDER_TYPES: {"qlstats": QlstatsProvider, "slipgate": SlipgateProvider, "elo_service": ThunderdomeEloProvider}
```

### `RankProvider` interface

```python
class RankProvider(ABC):
    def __init__(self, base_url: str, api_key: str | None, extra: dict):
        ...

    def fetch_ratings(self, steam_ids: list[str], game_type: str | None) -> dict[str, RankResult]:
        """Returns {steam_id: RankResult}, keyed by the steam id as a **string**.
        Missing/unranked players are omitted, not raised. Network/HTTP errors are
        caught internally and result in an empty dict — callers never see provider
        exceptions."""
```

**Key type is load-bearing.** Every adapter returns `str` steam-id keys, and
every adapter that parses an id out of a provider payload must not carry the
provider's own type through — `balance.py:308` does `sid = int(p["steamid"])`,
and an adapter that mirrors that produces int keys, so every lookup on the
frontend misses and the whole feature silently renders a column of dashes.

**One reference copy, throughout.** Two `balance.py` files ship in this repo and
their line numbers do not agree: the 643-line minqlx copy at
`ql-assets/data/minqlx-plugins/balance.py`, and the 890-line minqlxtended preset
copy at `configs/presets/_builtin/default-minqlxtended/scripts/balance.py`.
Every `balance.py` citation in this document and in the implementation plan
refers to the **minqlxtended preset copy**, because that is the runtime all
three provider plugins target.

`RankResult` is a small typed dict: `{"rating": float | None, "display": str,
"provisional": bool}`. `display` is what's actually rendered (Slipgate has
tiers, elo-service has a raw number). `rating` and `provisional` are carried as
forward-compatible metadata; neither is rendered or sorted on in this slice (see
"Deferred follow-ups").

Each adapter is responsible for translating its own bulk/single-lookup shape
into this common return type and for its own timeout (fixed short timeout, 3s)
and auth header.

### Data flow for a Live Status view

1. Frontend already polls the existing live-status endpoint for
   map/players/score at its current interval (15s) — unchanged.
2. A new, independent hook (`useRankData`) polls
   `GET /api/instances/<id>/ranks` every **30s** while the Live Status drawer is
   open, sending the currently-connected steam IDs as a query param. It stops
   polling once a response reports `configured: false`.
3. Backend validates `steam_ids` **before anything else** (see below), then
   `RankService.get_ratings(instance_id, steam_ids)` — reads
   `RankProviderConfig` for the instance; if none configured or disabled,
   returns `{}` immediately (no provider call, no cache lookup). Otherwise
   checks Redis for a fresh cached blob; on a miss, calls the adapter
   synchronously (short timeout keeps the request cheap), stores the result
   in Redis with TTL, returns it.
4. Frontend merges `{steam_id: RankResult}` into `sortedPlayers` keyed on
   `String(p.steam)` and renders the rank column, showing `display` (or "—" if
   the player has no entry, is unranked, or the provider call failed).
   `serverchecker.py:229-231` writes exactly one identity field,
   `"steam": str(p.steam_id)` — the modal's existing
   `p.steam || p.steamid || p.steam_id` fallback is defensive, not evidence of
   three shapes. String on both sides, always.

### `steam_ids` validation (before any cache or provider call)

`steam_ids` is client-supplied and ends up interpolated into an outbound,
credential-carrying provider URL (a path segment for elo-service, a `+`-joined
path segment for qlstats). Applied in this order:

1. Split on `,`, `.strip()` each entry.
2. Drop every entry that does not match `STEAMID64_RE` — the existing
   `re.compile(r'^7656119\d{10}$')` in `ui/admin_permissions.py:10`. Reuse that
   constant; do **not** substitute a looser `^\d{17}$`. Non-matching ids are
   dropped silently, not rejected with a 400 — a stale roster should not fail
   the request.
3. De-duplicate, preserving nothing about order (the list is sorted for the
   cache key anyway).
4. Cap the result at **64 ids**. Anything beyond the cap is discarded. Without
   the cap, one authenticated request becomes an unbounded outbound fan-out at
   3s per call — a self-inflicted outage and a good way to get the QLSM host
   rate-limited by a third party.
5. Empty list after all of the above → return `{}` without touching cache or
   provider.

### Caching

Caching is per-instance (not per-viewer): several people watching the same
instance's Live Status share one cache entry, and the fetch cost is bounded
regardless of poller count. Redis is used instead of an in-process cache because
Gunicorn runs multiple worker processes — an in-memory cache would not be shared
across them and would refetch on every worker.

**Key composition** (colon-namespaced, matching `server:status:…` and
`steam:workshop:preview:…`):

```
rank:ratings:{instance_id}:{config_fp}:{roster_fp}
```

- `config_fp` — first 12 hex chars of `sha256` over
  `f"{provider_type}|{base_url}|{game_type}|{extra_json}|{enabled}"`. A config
  change is therefore simply a different key, never a stale hit.
- `roster_fp` — first 12 hex chars of `sha256` over the **sorted, de-duplicated,
  validated** steam ids joined by `,`. A player joining mid-window changes the
  roster fingerprint, so they get a fresh fetch instead of sitting at `—` for a
  whole TTL.
- `api_key` is deliberately **not** hashed into the key — no credential material
  in the Redis keyspace. A key rotation is covered by the write-invalidation
  below.

**TTLs:** 60s for a successful result; **15s** for an empty/negative result, so
a transient provider outage self-heals quickly without hammering a down
provider. The hook's 30s poll against a 60s TTL keeps `poll >= TTL/2`, so a
cache hit is the common case and an outbound call does not ride on every other
refresh.

**Write invalidation:** `PUT` and `DELETE /api/instances/<id>/rank-provider`
delete the instance's cache keys (`SCAN`/`DELETE` over
`rank:ratings:{instance_id}:*`) **before returning**. Without this, disabling a
provider visibly does nothing for a full TTL.

**No-Redis behavior:** `current_app.extensions['redis']` can be absent — the
shared client is created inside a `try/except` that only logs a warning
(`ui/__init__.py:113-119`), which is why `get_server_status`
(`server_status_routes.py:157-159`) and `_read_workshop_preview_cache` (`:48-50`)
both guard for `None`. `RankService` guards the same way and, when the client is
missing, **fetches uncached** rather than returning empty — degrading to "works,
just slower" beats "silently blank" during a Redis restart. It never raises.

## Data model

New table, one row per configured instance (an instance with no row has no
rank provider):

```python
class RankProviderConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    instance_id = db.Column(
        db.Integer,
        db.ForeignKey('ql_instance.id', ondelete='CASCADE'),
        nullable=False, unique=True,
    )
    provider_type = db.Column(db.String(32), nullable=False)   # "qlstats" | "slipgate" | "elo_service"
    base_url = db.Column(db.String(255), nullable=True)        # required for all three (qlstats' includes the elo|elo_b segment)
    api_key = db.Column(db.String(255), nullable=True)         # bearer token / X-API-Key; unused for qlstats
    game_type = db.Column(db.String(16), nullable=True)        # e.g. "duel", "ffa_auto"; provider-specific meaning
    extra = db.Column(db.Text, nullable=True)                  # JSON blob; first tenant is qlstats' elo|elo_b selector
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_updated = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
```

On `QLInstance`, the matching side is
`rank_provider_config = db.relationship('RankProviderConfig', uselist=False,
cascade='all, delete-orphan', passive_deletes=True)`.

`api_key` is stored the same way `zmq_stats_password` already is on
`QLInstance` — plaintext column, protected by the same route/auth boundary
as the rest of instance config. No new secret-handling pattern is
introduced. `ApiKey`'s own docstring states the project's position outright:
"Plaintext storage by design… No hash column to avoid misleading security
theater" (`ui/models.py:270-274`).

A one-to-one relationship (`instance_id` unique) matches "provider is
per-instance, at most one active provider at a time" — if an instance needs
no rank provider, it simply has no row.

### Migration (required — not optional)

Tests build their schema with `db.create_all()` (`tests/conftest.py:30-32`), so
every backend test passes whether or not a migration exists. Production runs
`flask db upgrade`, so without one the deployed app raises
`no such table: rank_provider_config` on the first call to any new endpoint.

Add `migrations/versions/<rev>_add_rank_provider_config.py` with
`down_revision = '20260915120000'` (the current single head,
`migrations/versions/20260915120000_add_display_url_to_plugin_repository.py`),
using `op.create_table` in batch mode per this repo's SQLite convention, with a
`downgrade` that drops the table. `flask db upgrade` is part of the deploy.

### Lifecycle wiring (delete and backup)

SQLite does not enforce foreign keys by default, and instance deletion is a
plain `db.session.delete(instance)` (`ui/task_logic/ansible_instance_mgmt.py:803`).
SQLite reuses a freed rowid when the deleted row held the max id, so an orphaned
config row can silently re-bind a stored third-party credential to a newly
created, unrelated instance.

- **Delete:** the `ondelete='CASCADE'` + `cascade='all, delete-orphan'` pair
  above, **plus** an explicit delete of the config row in `delete_instance_logic`
  before the instance is deleted. Do not rely on SQLite FK enforcement.
- **Backup export:** add `rank_provider_configs` to `serialize_database()`'s
  explicit table list (`ui/task_logic/backup_db_export.py:91-103`). That list is
  hand-maintained, so a new table is otherwise silently absent from every
  backup.
- **Backup restore:** add the table to `replace_database()`'s wipe list
  (`ui/task_logic/backup_db_import.py:62-71`), **children before parents** —
  before `QLInstance.query.delete()` — and to the restore loop as an *optional*
  key, following the `operators` precedent (`backup_db_import.py:119-126`), so
  older archives without the key still restore.
- **The `api_key` travels in the archive in the clear.** This follows the
  existing precedent — `ApiKey.key` is already exported in the clear
  (`backup_db_export.py:100`). The archive's existing "this file is sensitive"
  posture covers it; no new handling is invented here.

## API

- `GET /api/instances/<id>/rank-provider` — returns the current config
  `{"data": {provider_type, base_url, api_key, game_type, extra, enabled}}`,
  or `{"data": null}` if unconfigured.

  **`api_key` is returned in clear text, not masked.** This repo masks no
  secrets anywhere: `QLInstance.to_dict()` returns `zmq_rcon_password` and
  `zmq_stats_password` in the clear (`ui/models.py:186-189`) and
  `InstanceDetailsModal.jsx:419` already renders the stats password as
  selectable text with a copy button. Masking here would be the app's only
  masked secret, would need a sentinel protocol to survive the whole-object
  `PUT` below, and would still leave the operator unable to verify what is
  stored. Concretely: a masked `GET` feeding a full-field `PUT` writes `"****"`
  back over the real token the *first* time the operator toggles `enabled` or
  edits `game_type`, after which the provider 401s and the token is
  unrecoverable from the UI.

- `PUT /api/instances/<id>/rank-provider` — upsert
  `{provider_type, base_url, api_key, game_type, extra, enabled}` (whole
  object; `extra` is written here, which is its exercised path). Validation
  order follows the repo convention:
  1. **Type check** — `provider_type`, `base_url`, `api_key`, `game_type` are
     strings or absent; `enabled` is a bool; `extra` is an object **whose every
     value is a string**.
  2. **Normalize** — `.strip()` every string; strip **trailing slashes** off
     `base_url`. The adapters concatenate paths onto it (`balance.py:127-131`
     produces `http://host/api/` by construction), so without this a trailing
     slash silently yields a double-slash URL and the provider 404s with no
     useful error.
  3. **Empty check** — `provider_type` and `base_url` required. `game_type` is
     **optional** — blank means "derive it from the live gametype" (see "Game
     type is derived, not typed"), which is the normal case for qlstats and
     Slipgate.
  4. **Length check** — `base_url` ≤ 255, `api_key` ≤ 255, `game_type` ≤ 16,
     `provider_type` ≤ 32, matching the column widths. `extra` is bounded by its
     **serialized** length, ≤ 2048 characters: the column is an unbounded
     `Text`, and nothing else stops an operator posting arbitrary nested data
     into it.
  5. **Pattern check** — `provider_type` must be a key in the adapter registry
     (unknown value → `400`, nothing written); `base_url` must start with
     `http://` or `https://`. When `provider_type` is `qlstats` and `extra`
     carries a `rating_system`, it must be `elo` or `elo_b`.
  6. **Uniqueness** — no concern, `instance_id` is unique.

  **Why `extra` is validated at all.** It is not a privilege boundary — the
  principal is the same authenticated operator throughout. It is the one
  operator-controlled value that reaches an outbound URL without rules:
  `extra["rating_system"]` becomes a path segment in the qlstats request. The
  UI only ever offers `elo` and `elo_b`, so the check costs one line and turns a
  typo's silent 404 into a clear error at write time. These three rules are the
  whole of it; `extra` does not get a per-provider schema framework for a
  column with one key in it.

  On success, invalidates `rank:ratings:{instance_id}:*` before returning.

- `DELETE /api/instances/<id>/rank-provider` — removes the config (equivalent
  to "no provider"). Also invalidates `rank:ratings:{instance_id}:*` before
  returning.

- `GET /api/instances/<id>/ranks?steam_ids=a,b,c` — read-only, used by
  `useRankData`. Returns
  `{"data": {steam_id: RankResult}, "configured": true|false}`.

  `configured` is `false` when the instance has no `RankProviderConfig` row, or
  its row is `enabled=false`, or its row is incomplete. It is `true` whenever a
  usable provider exists — including when that provider just failed. The flag
  is about *configuration*; the "errors never propagate" contract below is
  about *failures*. They are different axes and the flag does not weaken the
  contract.

  Always `200` **once the instance exists**, with an empty `data` object when
  there's no provider configured, the provider call fails, or `steam_ids` is
  empty after validation — errors never propagate to the Live Status UI as a
  failure state, they just mean no rank shown that cycle. Matches this repo's
  "return boolean/empty, don't raise" convention for anything that talks to an
  external system.

  **An unknown instance id is a `404`**, like the three sibling routes above. It
  is a different kind of answer from "this instance has no ratings this cycle",
  and making `/ranks` the one route in the blueprint that invents a `200` for a
  missing row would be the larger inconsistency. The client side of that
  contract is pinned too: `useRankData` treats a `404` as `configured: false`
  and stops polling, so an instance deleted while its drawer is open does not
  keep firing a request every 30s for the life of the drawer.

  `steam_ids` is validated per the rules in "Data flow" above before any cache
  or provider call.

### Secret boundary: `api_key` must never enter `QLInstance.to_dict()`

`/api/v1/instances` strips a **denylist** —
`_EXCLUDED_FIELDS = {'zmq_rcon_port', 'zmq_rcon_password', 'logs', 'config'}`
(`ui/routes/external_api_routes.py:8`) — so the default for anything newly added
to `to_dict()` is "exposed to every holder of the external API key". That key is
a different principal from the logged-in operator, so the "plaintext is fine
here" argument above does **not** extend across this boundary.

`api_key` therefore never appears in `QLInstance.to_dict()`. If a rank-provider
summary is ever added there for frontend convenience, it carries only
`provider_type` and `enabled`, and it is added to `_EXCLUDED_FIELDS` as well.

## Frontend changes

- `LiveServerStatusModal.jsx`: add an "ELO" column to the players table,
  positioned after "Team" and before "Score" (rank data is a property of the
  player, closer to identity than to live match state). Cell shows
  `rankData[String(p.steam)]?.display ?? '—'`, rendered by a small dedicated
  cell component rather than inline (the modal is already 344 lines against a
  300-line soft limit).

  Adding a column **is** a layout change for every existing user — the earlier
  "no layout change" claim was wrong and is struck. The table shape already
  varies per instance today: the team `Score` field is conditional on
  `isTeamMode` (`LiveServerStatusModal.jsx:274-280`), so a conditional rank
  column is consistent with the existing table, not a departure from it.

  **On an instance with no provider configured the column is hidden entirely**,
  not shown full of dashes — operators who never use this feature see the table
  exactly as it is today. The `configured` flag in the `/ranks` response drives
  this. Within a configured instance an individual player's empty cell still
  renders as `—`, because there the absence is about that player, not about the
  feature being off.

- New hook `frontend-react/src/hooks/useRankData.js`, with the signature
  `useRankData(instanceId, steamIds, { enabled })`:
  - `enabled = isOpen && !!instanceId`. This is **required**, not an
    optimization: `LiveServerStatusModal` is mounted *unconditionally in two
    places* — `ServersPage.jsx:401` and `InstanceDetailsModal.jsx:528` — with
    visibility controlled only by the `isOpen` prop. A hook in the component
    body otherwise runs while the drawer is closed, and runs twice when the
    details modal sits behind the drawer. The precedent is
    `useWorkshopPreview(workshopItemId, enabled)`
    (`frontend-react/src/hooks/useWorkshopPreview.js:10-20`), which this exact
    component already calls with `isOpen`.
  - The effect depends on a **stable sorted joined string** of the steam ids,
    not the array. `sortedPlayers` is a `useMemo` over `serverStatus.players`,
    which `useServerStatus` replaces on a 15s interval
    (`useServerStatus.js:4`), so an array in the dependency list re-fires the
    effect on every parent render and the 30s throttle — the thing the entire
    caching design rests on — quietly evaporates.
  - Polls every 30s while enabled; stops polling as soon as a response reports
    `configured: false`, or returns `404`, so an instance that will never have a
    provider costs one request instead of one every 30s for the life of the
    drawer. **That latch is keyed on the instance alone, never on the roster.**
    `configured: false` is a property of the instance, not of who happens to be
    connected, so clearing the latch when a player joins or leaves turns the
    stated "one request" into one request per roster change — frequent on a
    populated server. The cost is that a provider configured while the drawer is
    open is not picked up until the drawer is reopened, which is the right
    behaviour for a config change.
  - **`configured` starts `false`.** The modal renders before the first
    `/ranks` response resolves, so an initial `true` shows the header and a
    column of dashes on every instance that has no provider — which is every
    instance on day one — and then removes them a moment later. That is exactly
    the flash the "hidden entirely" decision above exists to prevent. `true` is
    set only by a successful response that says so, and a failed poll leaves
    `configured` **untouched** rather than forcing it `true`. The cost is one
    render without a column before a configured instance's first response, which
    is the correct direction to be wrong in.
  - **Both `ranks` and `configured` reset when `instanceId` changes.** One
    `LiveServerStatusModal` is mounted per page and the `instance` prop is
    swapped as the operator picks servers (`ServersPage.jsx:401`), so without a
    reset instance A's column and numbers survive into instance B's first
    render. A player on both servers then carries A's rating into B's table:
    a wrong number rather than a missing one, and the one failure in this
    feature an operator cannot detect by looking.
  - Returns `{ ranks, configured }`. Follows the repo's state rule: the hook
    holds IDs/raw data, the modal re-derives per-row rank objects on each
    render.

- **Config surface:** a new `rank` tab in `EditInstanceConfigModal.jsx`
  (existing tabs: `config | scripts | factories | hooks | admins`, see `:145`
  and `:1195-1199`). There is no existing post-creation per-instance settings
  editor to slot into — `zmq_stats_password` is set at creation and read-only
  afterwards (`InstanceDetailsModal.jsx:419-421`), and the instance `PUT`
  handler accepts only `name`/`hostname` ("Currently only supporting name
  updates", `ui/routes/instance_routes.py:569-596`). Placement is therefore a
  design decision, made here, not an implementation-plan detail.

  The tab body lives in its own component file,
  `frontend-react/src/components/instances/RankProviderTab.jsx`, and
  `EditInstanceConfigModal` gains only a tab button and a panel — exactly how
  the `admins` tab was added, and what keeps a 1413-line modal from growing
  further.

  The tab holds: a provider dropdown (None / qlstats / Slipgate / Thunderdome
  elo-service), `base_url`, `enabled`, `api_key` (hidden for qlstats, which has
  no auth), and for qlstats an `elo` / `elo_b` rating-system selector persisted
  into `extra`. `base_url` is required for every provider.

  `game_type` sits under a collapsed "Advanced" disclosure, labelled as an
  override with helper text along the lines of *"Leave blank to follow the
  server's current game type. Set this only for providers with their own pool
  names, such as elo-service's `ffa_auto`."* It is deliberately not a prominent
  required field: for qlstats and Slipgate the derived value is always right,
  and a typed one can only be wrong.

## Error handling

- Provider unreachable, timeout, non-200, or malformed response: the
  adapter logs once (dedup'd, adapted to this repo's logging) and returns `{}`
  for that call. The Redis cache is not poisoned with an empty result
  permanently — the short 15s negative TTL (against the normal 60s) lets a
  transient outage self-heal quickly without hammering a down provider every
  request.
- A `404` from a single-player path means "unranked", not "error". For
  elo-service that is the rating lookup at `ranked.py:666`; `:597` is a
  different endpoint's 404 (the `GET /player/{steam_id}` name lookup, no
  `?mode=`) and is not cited here. Slipgate says the same thing at
  `slipgate (1).py:2427`, on a single-player path QLSM never calls. In every
  case the player is omitted from the result, the cell is empty, and it is not
  logged as a failure.
- Slipgate's bulk path expresses the same thing two ways and both must be
  treated as unranked: an entry with `found` false, and an entry present with
  `display` null (`slipgate (1).py:2542-2547`). Neither is an error.
- A game type that maps to `None` for the configured provider is not an error
  either: no request is made and the column is empty for everyone, because that
  mode genuinely has no ratings at that provider.
- **Log hygiene.** Adapters log the **provider type, the instance id and the
  HTTP status code only** — never request or response headers, never request
  or response bodies, never the config object. This repo ships logs to Loki, so
  a token dumped into a "let's log the failed request" line does not stay
  local. Rank failures **never** reach `append_log(instance, ...)`: that field
  is surfaced verbatim in the UI, which makes it the worst possible
  destination for third-party error text.
- Invalid/incomplete `RankProviderConfig` (e.g. a row missing `base_url`):
  treated as "no provider" for fetch purposes — `ranks` returns `{}` with
  `configured: false`. The `PUT` validation above rejects incomplete configs at
  write time, so this is a defence for rows that predate a validation change or
  arrive via a restore, not the normal path.
- Redis client absent: fetch uncached, never raise (see "Caching").
- No steam IDs requested, or none survive validation: short-circuits to `{}`
  without touching cache or provider.

## Testing

- `tests/test_rank_providers.py`: one test module per adapter
  (`fetch_ratings` against mocked HTTP responses) covering success, 404/no
  rating, and network-error paths, plus a registry test. Per adapter:
  - elo-service: bulk `/players` parsed via `sort_score or mu`; a `null` entry
    yields no result; single-player `404` yields no result; `mode` is passed
    through; `X-API-Key` present when configured. A `{"sort_score": 0,
    "mu": 22.5}` entry yields `22.5` — the `or`-semantics guard, which an
    `is None` check fails.
  - qlstats: ids `+`-joined into the path; value read from
    `players[i][<game_type>]["elo"]`; ids in `untracked` omitted; a player
    absent from `players` omitted; a player whose bucket is `{"elo": 0,
    "games": 0}` omitted rather than rendered as `0`.
  - Slipgate: bulk `POST /ratings/bulk` parsed from `players[]`; **both**
    unranked shapes yield no result — `found` false, and present-with-`display`-
    null; single-player `404` yields no result; `display` is returned verbatim
    and a non-numeric value such as `"1650 (Gold)"` survives untouched (the
    don't-parse-it guard); `Authorization: Bearer` present when configured.
  - every adapter returns **string** steam-id keys (the int-key regression
    guard).
- **Game-type resolution tests** — one per adapter over `map_game_type`:
  Slipgate maps `har`→`harvester`, `dom`→`domination`, `rr`→`redrover`,
  `1f`→`1flag` and passes `ca`/`ctf`/`tdm`/`ft`/`ffa`/`duel`/`ad` through
  unchanged; an unrated mode returns `None` and the service makes **no HTTP call
  at all**; a non-empty `config.game_type` wins over derivation and is sent
  verbatim (the elo-service `ffa_auto` path). The `har`→`harvester` and
  `1f`→`1flag` cases are the specific regression guards for the
  silent-empty-column failure.
- `tests/test_rank_provider_routes.py`: CRUD on
  `/api/instances/<id>/rank-provider` (validation order; `api_key` returned in
  clear on `GET`; unknown `provider_type` → `400` with nothing written;
  `base_url` trailing slash normalized; non-`http(s)` scheme rejected; a
  non-string `extra` value, an oversized `extra` blob, and a qlstats
  `rating_system` outside `{elo, elo_b}` each rejected) and
  `/api/instances/<id>/ranks` (cache hit/miss, `configured` flag for
  unconfigured / disabled / working instances, empty-provider short circuit,
  provider failure returns empty data with `200` and the short negative TTL,
  `enabled=false` makes no adapter call at all).

  **These route tests must stub Redis.** `create_app` always installs a client
  (`ui/__init__.py:113-119`) and `from_url` does not connect, so the key is
  present but unusable and `tests/conftest.py` overrides nothing. A `/ranks`
  test that leaves it alone gets `None` back from `_live_gametype`, returns
  before any adapter call, and passes without exercising the thing it names —
  the provider-failure test in particular. Install a `MagicMock` into
  `app.extensions['redis']` returning a real status blob, following
  `tests/test_server_status_routes.py:41-46`, and assert the mocked transport
  was actually reached.
- **Migration test** — upgrading from `20260915120000` creates
  `rank_provider_config` and `downgrade` drops it. Without this, `db.create_all()`
  hides a missing migration from every other test in the suite. Scope it to the
  **one new revision**: stamp the schema at `20260915120000`, then upgrade and
  downgrade a single step. Replaying the whole chain from the root drags in
  three data migrations that touch `configs/` on disk, which couples a unit test
  to the working directory for no extra signal. `flask db heads` already covers
  the "is the chain branched" question.
- **Lifecycle tests** — deleting an instance removes its `RankProviderConfig`
  row; a backup round trip (export → `replace_database` → restore) returns
  configs attached to the right instances, and a pre-existing config row for
  instance id N does *not* survive a restore that re-creates a *different*
  instance with id N.
- **Input validation** — `?steam_ids=../../admin,12345,7656119…` drops the
  non-matching ids before they reach the adapter (assert on the mocked call's
  URL); a list longer than the cap never exceeds 64 ids in outbound calls.
- **Redis absent** — `current_app.extensions['redis']` missing → `/ranks` still
  returns `200` with data and no exception.
- **Secret boundary** — `api_key` appears in no response body of
  `/api/instances/`, `/api/v1/instances`, or `/api/instances/<id>/ranks`.
- Frontend:
  - `useRankData` does not fetch when `enabled` is false (the double-mount
    guard for `ServersPage.jsx:401` + `InstanceDetailsModal.jsx:528`).
  - `useRankData` does not re-fetch when the steam-id array is a new array with
    identical contents (the stable-dependency guard).
  - `useRankData` stops polling after `configured: false`, and a roster change
    afterwards makes **no** second request (the latch is keyed on the instance,
    not the roster).
  - `useRankData` reports `configured` false on the first render, before any
    response resolves, so the column never flashes.
  - `useRankData` clears `ranks` and `configured` when `instanceId` changes.
  - `useRankData` stops polling on a `404` from `/ranks` instead of retrying
    every 30s.
  - `LiveServerStatusModal` renders `display` for a matching `steam` value and
    `—` otherwise, merging on the string `p.steam`.
  - `RankProviderTab` (following `HooksTab.test.jsx`, the repo's precedent for
    testing a tab body in isolation): choosing "None" issues a delete rather
    than a save, the API key field is hidden for qlstats and shown for the other
    two, and selecting `elo_b` persists into `extra`. That fork is the tab's
    only real branching, and the delete path is the one an operator reaches by
    picking "None" — easy to break silently later.

## Documentation impact

- `docs/api_reference.md`: document the four new endpoints.
- `docs/architecture.md`: add `RankProviderConfig` to the SQLite schema
  note in the architecture diagram's data-flow box, and a short paragraph
  on the rank-provider adapter pattern.
- `docs/development_guidelines.md`: note the `RankProvider` adapter pattern
  as the template for any future external-service integration of this
  shape.
- `docs/user/`: brief instance-settings doc addition explaining how to
  point an instance at qlstats/Slipgate/elo-service and what each field
  means, since this is user-facing per-instance configuration.
- `docs/user/operations/live-status.md`: this page documents the player table
  field-by-field under "What You See" and "Player Sorting Logic", and embeds
  `../images/instance-live-status.png` at `:10`. Both go stale the moment a
  column is added — the prose needs the new column and the screenshot needs
  re-recording against an instance with a provider configured.
- **A new user page needs two registrations, both hand-maintained:** a `nav:`
  entry in `mkdocs.yml`, *and* an entry in `docs/user/index.json`, which backs
  the in-app help. Missing either leaves the page unreachable from one of the
  two surfaces.
- **Version bump — all four references move together**, and per this project's
  convention the bump lands **after the PR is opened** so the changelog entry
  can cite the real PR number: `VERSION`, `docs/user/version.json`,
  `docs/user/releases.md`, and the `README.md` badge. Drift between them causes
  a wrong footer version, a spurious "update available" notice, or a stale
  badge.

## Out of scope

- Any leaderboard/browse view beyond the connected-player Live Status table.
- Writing match results back to a provider (QLSM only reads ratings; writing
  is each provider's own plugin's job, as already established with
  `ranked.py`/`balance.py`/`slipgate.py`).
- A generic "credentials vault" — `api_key` follows the existing plaintext
  pattern already used for `zmq_stats_password`.

## Implementation notes for the plan

No implementation plan exists yet. These are instructions for whoever writes
it — they came out of the review loop as plan-level concerns rather than design
changes, and each one is already reflected in the sections above where it also
affects the design.

**File layout — decide up front, three target files are already over the repo's
size limits** (`ui/routes/instance_routes.py` 1418 lines,
`EditInstanceConfigModal.jsx` 1413, `LiveServerStatusModal.jsx` 344, against a
300-line soft and 500-line hard limit):

- Routes go in a **new** blueprint, `ui/routes/rank_provider_routes.py`,
  registered at `url_prefix='/instances'` next to `instance_admin_api_bp`. This
  is the established pattern, not a new one —
  `ui/routes/instance_admin_routes.py` is a 21-line file registered exactly that
  way at `ui/__init__.py:256-257`, alongside `instance_hooks_routes` and
  `instance_hooks_files_routes`.
- The config form is `components/instances/RankProviderTab.jsx`; the rank cell
  is its own small component. Neither is an inline addition to the modals.
- Adapters live one-per-file under `ui/rank_providers/` as laid out in
  "Architecture".

**Build order.** Migration → model + lifecycle wiring (delete, backup export,
backup import) → adapters + registry → `RankService` (validation, cache,
no-Redis guard) → routes blueprint → `useRankData` → `RankProviderTab` → rank
column. The lifecycle wiring is easy to forget once the feature visibly works,
so it lands before the UI, not after.

**Game type is derived from live status, with an operator override.** This
reverses an earlier note in this spec that had it operator-configured with
derivation as a fallback. The reversal is deliberate: for qlstats and Slipgate
the derived value is always right and a typed one can only go stale across a
rotation, and each adapter owns the translation to its own vocabulary. See
"Game type is derived, not typed" for the resolution order and the mapping
table. The override column remains, because elo-service's `ffa_auto` has no QL
gametype to derive from.

The cache-key objection to derivation is answered by the fingerprint scheme
already specified: the resolved game type is one component of `config_fp`, so a
mode change rotates the key exactly as a config edit does. That is correct
behaviour — CA ratings must not be served for a CTF round — not coupling.

The `elo` vs `elo_b` selector goes in `extra`, which gives that column its first
exercised write path.

**Slipgate's shapes are verified** against its own minqlxtended plugin v1.10.1
(`slipgate (1).py` in the checkout root, untracked). Adapter tests use fixtures
transcribed from that file's real request and response handling rather than
guessed shapes. That file is an operator-supplied artifact, not a repo file:
copy the fixture payloads into the test module so the suite does not depend on
it remaining on disk.

**Deploy step.** `flask db upgrade` is part of the production deploy for this
change. Say so in the PR body.

**Version bump is a post-PR step, not an implementation step.** Open the PR
first, then bump all four references in one commit so the changelog entry can
cite the real PR number. See "Documentation impact".

**Documentation and the screenshot.** The `live-status.md` screenshot refresh
needs the feature running against a real instance with a provider configured —
it is the slowest item on the documentation list. Schedule it, rather than
discovering it at PR time.

## Open decisions — resolved 2026-09-20

Both decisions the review left to the author are now settled; nothing here
blocks the plan.

- **Does Slipgate stay in the first slice?** *Yes.* The operator supplied
  Slipgate's own minqlxtended plugin (v1.10.1), so its shapes are verified and
  fixture-sourced rather than guessed. See "Provider API shapes".
- **Is the ELO column hidden or dashed on unconfigured instances?** *Hidden.*
  Instances with no provider configured render the table exactly as today. See
  the Live Status section.

A third question surfaced and was settled during the same pass: **who supplies
the game type.** Derived from live status per-adapter, with an optional
operator override — see "Game type is derived, not typed".

## Deferred follow-ups

Reviewed and consciously not done in this slice:

- **Explicit rate limit on `/ranks`** (finding 20). The comparable
  third-party-proxying endpoint carries one
  (`@limiter.limit(WORKSHOP_PREVIEW_RATE_LIMIT)`,
  `server_status_routes.py:176`) and the global default is 200/min. Deferred
  because the caller is a single authenticated operator on a 30s poll, and the
  64-id cap plus the cache already bound the outbound volume that actually
  matters. One constant, takeable any time for the symmetry.
- **Column header wording** (finding 25). "ELO" mislabels Slipgate's tiers and
  elo-service's `mu`/`sort_score` scale; "Rank" or "Rating" would be accurate
  for all three. Deferred because it is purely cosmetic, "ELO" is the term
  Quake Live players actually use, and it is one string in one file either
  way — decidable at implementation time without amending this spec.
- **Sorting by `rating`, and rendering `provisional`** (finding 15). Both
  fields are carried in `RankResult` as forward-compatible metadata but neither
  is used by this slice. Deferred because the locked display decision was
  deliberately minimal ("a new column, no separate leaderboard view"), and
  adding an ELO sort is unrequested scope. Fine follow-ups if anyone asks.

---
**Review loop closed:** 2026-09-20
- Findings: `docs/findings/2026-09-20-rank-provider-integration-findings.md`
- Assessment: `docs/assess-review-findings/2026-09-20-rank-provider-integration-assessment.md`
- Accepted findings folded in: 1 (missing Alembic migration), 2 (elo-service
  returns `sort_score`/`mu`, not `rating`), 3 (delete/backup lifecycle wiring),
  4 (masking + whole-object upsert destroys the API key — masking dropped),
  5 (cache key ignores roster/provider/game type), 6 (`steam_ids` validation and
  cap), 7 (config UI surface named), 8 (qlstats adapter details), 9 (Slipgate
  unverifiable in-repo), 10 (`configured` flag and polling gate), 11 (hook
  mounting and dependency identity), 12 (string merge key), 13 (Redis client can
  be absent), 14 (`extra` gets a write path), 15 (wording fix — `rating` no
  longer documented as driving sort), 16 (`api_key` must never enter
  `to_dict()`), 17 (version bump and affected user pages), 18 (new blueprint and
  separate components), 19 (Redis key naming), 21 (cadence 30s poll / 60s TTL),
  23 (log hygiene), 24 (`base_url` validation)
- Deferred: 20 (explicit rate limit on `/ranks`), 25 (column header wording),
  15 (ELO sort and `provisional` rendering — the forward-looking half)

---
**Review loop closed (round 2):** 2026-09-20
- Findings: `docs/findings/2026-09-20-rank-provider-integration-findings-r2.md`
- Assessment: `docs/assess-review-findings/2026-09-20-rank-provider-integration-assessment-r2.md`
- Accepted findings folded in: 2 (one-flag CTF added to the Slipgate mapping,
  `1fctf`/`ictf` explicitly not mapped), 4 (route tests must stub Redis),
  5 (`configured` starts `false`), 6 (hook state resets on instance change),
  7 (the polling latch is keyed on the instance, never the roster),
  8 (`sort_score or mu` is Python's `or`, not an `is None` check), 9 (qlstats
  omits an `elo == 0, games == 0` bucket rather than rendering `0`),
  10 (migration test scoped to the one new revision), 13 (one `balance.py`
  reference copy — the minqlxtended preset copy — throughout), 14 (`extra`
  validation: string values, serialized size bound, qlstats `rating_system`
  restricted to `elo`/`elo_b`), 15 (`/ranks` is "always 200 once the instance
  exists"; a `404` is `configured: false` plus stop polling), 18 (`ranked.py:597`
  dropped as a different endpoint's 404), 22 (Slipgate's single-player path is
  documented for reference and unused), 23 (`RankProviderTab` gets scoped tests)
- Deferred: none from this round on the spec side — 19 (elo-service display
  rounding) and 21 (citing the source of qlstats' `_SUPPORTED` set) are recorded
  in the implementation plan's deferred follow-ups
- Rejected, documents already correct: 3 (the Redis `gametype` is a bare `'ca'`
  under both runtimes, so no normalization), 16 (`useWorkshopPreview` is already
  cited positionally), 17 (the plan's `:301-302` and `:315-320` citations are
  the correct ones), 20 (Task 3 Step 5 already says the registry test stays red)
