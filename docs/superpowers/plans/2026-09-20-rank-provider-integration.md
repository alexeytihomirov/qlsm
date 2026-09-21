# Rank Provider Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each connected player's external rating in the Live Status player table, fetched by QLSM's backend from whichever rank service (qlstats, Slipgate, or a Thunderdome elo-service) that instance is configured to use.

**Architecture:** A per-instance `RankProviderConfig` row names a provider type, base URL and optional credential. A `RankService` resolves the game type from live status, validates the client-supplied steam IDs, checks a Redis cache keyed by a config+roster fingerprint, and on a miss calls one of three `RankProvider` adapters over HTTP. A new blueprint exposes CRUD plus a read-only `/ranks` endpoint; a new `useRankData` hook polls it on its own 30s cadence, independent of the 15s live-status poll, and the modal renders one extra column.

**Tech Stack:** Flask + SQLAlchemy + Alembic, Redis (`current_app.extensions['redis']`), `requests`, React + Vite, Vitest, pytest.

**Source spec:** `docs/superpowers/specs/2026-09-20-rank-provider-integration-design.md` — read it before starting. Every open decision in it is resolved.

---

## Before you start

- [ ] **Create the worktree.** Use the `/new-worktree` skill (never plain `git worktree add`). Branch name: `feature/rank-provider-integration`. The skill runs `./setup-worktree.sh`, which is what gives the worktree its own `.env`, `.venv`, `configs/` and DB. Without it `rcon_service` dies on Redis auth and the RCON console shows "RCON service unavailable".
- [ ] **Read the spec.** `docs/superpowers/specs/2026-09-20-rank-provider-integration-design.md`.
- [ ] **Do not run the full `pytest tests/` suite.** Scope every local run to the file or test you just touched. CI runs the full suite on the PR.

### Two spec ambiguities this plan resolves

You will not find these spelled out identically in the spec; resolve them the way this plan does and stay consistent.

1. **qlstats `base_url` vs `extra.rating_system`.** The spec says both that `base_url` "includes the elo|elo_b segment" and that `extra`'s first tenant is the `elo`/`elo_b` selector. Those overlap. This plan splits them the way `balance.py` actually composes the URL (`balance.py:127-131`: `f"http://{host}/{api}/"`): **`base_url` is the host root** (`http://qlstats.net`), and **`extra["rating_system"]`** is `"elo"` or `"elo_b"`. The adapter joins them. This keeps `extra` genuinely load-bearing, which the spec insists on.

2. **Where the live game type comes from.** Server-side, from the same Redis blob the live-status endpoint reads: `server:status:{host_id}:{instance_id}` (`ui/task_logic/server_status_poll.py:17,29`). Not from a client query param — it feeds the cache fingerprint and must not be client-controlled. When that blob is missing there is no game type, so no lookup happens and the column is empty. That degenerate case is moot in practice: the status blob comes from Redis too, so if it is gone the Live Status drawer has no players to rank in the first place.

   **The wire format is settled, not open.** The `gametype` value is a bare lowercase short code such as `'ca'` under both runtimes — verified against live blobs on this machine, and explained in the `_live_gametype` docstring in Task 7. No normalization step is needed and none should be added.

---

## File Structure

**New backend files**

| File | Responsibility |
|---|---|
| `ui/rank_providers/__init__.py` | Package marker; re-exports `RankResult`, `RankProvider`. |
| `ui/rank_providers/base.py` | `RankResult` TypedDict + `RankProvider` ABC (`fetch_ratings`, `map_game_type`). |
| `ui/rank_providers/qlstats.py` | `QlstatsProvider`. |
| `ui/rank_providers/slipgate.py` | `SlipgateProvider`. |
| `ui/rank_providers/elo_service.py` | `ThunderdomeEloProvider`. |
| `ui/rank_providers/registry.py` | `PROVIDER_TYPES` dict + `build_provider(config)`. |
| `ui/rank_providers/service.py` | `RankService`: id validation, game-type resolution, cache keys, Redis guard, invalidation. |
| `ui/routes/rank_provider_routes.py` | Blueprint: `GET/PUT/DELETE …/rank-provider`, `GET …/ranks`. |
| `migrations/versions/20260920120000_add_rank_provider_config.py` | Creates `rank_provider_config`. |

**New frontend files**

| File | Responsibility |
|---|---|
| `frontend-react/src/hooks/useRankData.js` | 30s poll of `/ranks`, stable deps, stops on `configured: false`. |
| `frontend-react/src/components/instances/RankProviderTab.jsx` | The `rank` tab body in `EditInstanceConfigModal`. |
| `frontend-react/src/components/instances/PlayerRankCell.jsx` | One table cell; keeps the modal from growing. |

**Modified files**

| File | Change |
|---|---|
| `ui/models.py` | `RankProviderConfig` model + relationship on `QLInstance`. |
| `ui/__init__.py:256` | Register the new blueprint at `url_prefix='/instances'`. |
| `ui/task_logic/ansible_instance_mgmt.py:803` | Explicit config delete before instance delete. |
| `ui/task_logic/backup_db_export.py:91-103` | Add `rank_provider_configs`. |
| `ui/task_logic/backup_db_import.py:62-71,119-126` | Wipe list (children first) + optional restore loop. |
| `frontend-react/src/services/api.js` | Four API functions. |
| `frontend-react/src/components/instances/LiveServerStatusModal.jsx` | Conditional ELO column. |
| `frontend-react/src/components/instances/EditInstanceConfigModal.jsx` | Tab button + panel only. |

**New test files:** `tests/test_rank_providers.py`, `tests/test_rank_service.py`, `tests/test_rank_provider_routes.py`, `tests/test_rank_provider_lifecycle.py`, `tests/test_rank_provider_migration.py`, `frontend-react/src/hooks/__tests__/useRankData.test.js`, `frontend-react/src/components/instances/__tests__/RankProviderTab.test.jsx`, and additions to `frontend-react/src/components/instances/__tests__/LiveServerStatusModal.test.jsx`.

**Build order** (the spec is explicit that lifecycle wiring lands *before* the UI, because it is easy to forget once the feature visibly works): migration → model → lifecycle → adapters → service → routes → API client → hook → tab → column → docs.

---

## Task 1: Model and migration

**Files:**
- Modify: `ui/models.py` (add model; add relationship on `QLInstance`)
- Create: `migrations/versions/20260920120000_add_rank_provider_config.py`
- Test: `tests/test_rank_provider_migration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_rank_provider_migration.py`:

```python
"""The migration must exist and must match the model.

tests/conftest.py builds its schema with db.create_all(), so every other test in
this repo passes whether or not a migration exists. Production runs
`flask db upgrade`. Without this test a missing migration ships green and the
deployed app raises `no such table: rank_provider_config` on first use.
"""
import sqlalchemy as sa

from ui import db
from ui.models import RankProviderConfig


def test_model_table_name_and_columns():
    table = RankProviderConfig.__table__
    assert table.name == 'rank_provider_config'
    assert set(table.columns.keys()) == {
        'id', 'instance_id', 'provider_type', 'base_url', 'api_key',
        'game_type', 'extra', 'enabled', 'created_at', 'last_updated',
    }


def test_instance_id_is_unique_and_cascades():
    column = RankProviderConfig.__table__.columns['instance_id']
    assert column.nullable is False
    fk = list(column.foreign_keys)[0]
    assert fk.ondelete == 'CASCADE'
    assert any(c.unique for c in RankProviderConfig.__table__.constraints
               if isinstance(c, sa.UniqueConstraint)) or column.unique


def test_migration_creates_and_drops_the_table(app):
    """Exactly one revision, up and back down.

    Scoped on purpose. `command.upgrade(cfg, 'head')` against a dropped schema
    replays the whole chain from the root, and three of those revisions do real
    work outside the database — 20260120120110_migrate_presets_to_filesystem,
    20260424103000_add_builtin_presets and
    7cf046f62e03_convert_ssh_key_paths_to_relative all touch `configs/` on disk.
    That makes a unit test slow and couples it to the working directory's
    configs/ tree for no extra signal. `flask db heads` in Step 7 already covers
    the "is the chain branched" question.

    Stamping first means this test no longer proves the chain is unbroken. That
    is deliberate: the full chain belongs in a deploy, not here.
    """
    import os

    from alembic import command
    from alembic.config import Config

    # Resolve from __file__, not the cwd: Config('migrations/alembic.ini')
    # only works when pytest happens to run from the repo root.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    migrations_dir = os.path.join(repo_root, 'migrations')

    with app.app_context():
        # conftest.py already built the whole schema with db.create_all(), which
        # includes rank_provider_config. Drop just that one table so the new
        # revision has something to do.
        RankProviderConfig.__table__.drop(db.engine, checkfirst=True)

        cfg = Config(os.path.join(migrations_dir, 'alembic.ini'))
        cfg.set_main_option('script_location', migrations_dir)
        # No sqlalchemy.url here on purpose: migrations/env.py:39 overwrites it
        # with get_engine_url() from the Flask app's engine, so setting it is a
        # no-op that implies a control this test does not have.

        # The schema now matches 20260915120000. Stamp it so `upgrade` runs the
        # one new revision instead of replaying the chain from the root.
        command.stamp(cfg, '20260915120000')

        command.upgrade(cfg, '20260920120000')
        inspector = sa.inspect(db.engine)
        assert 'rank_provider_config' in inspector.get_table_names()

        command.downgrade(cfg, '20260915120000')
        inspector = sa.inspect(db.engine)
        assert 'rank_provider_config' not in inspector.get_table_names()
```

The stamp is what keeps this a unit test. Do not "simplify" it back to
`upgrade(cfg, 'head')` against a dropped schema — that is the version this
review rejected.

- [ ] **Step 2: Run it to make sure it fails**

Run: `pytest tests/test_rank_provider_migration.py -v`
Expected: FAIL — `ImportError: cannot import name 'RankProviderConfig' from 'ui.models'`

- [ ] **Step 3: Add the model**

In `ui/models.py`, after the `QLInstance` class, add:

```python
class RankProviderConfig(db.Model):
    """Which external rank service one QLDS instance reads ratings from.

    One row per configured instance; an instance with no row has no rank
    provider. api_key is a plaintext column, exactly as zmq_stats_password
    already is on QLInstance — see ApiKey's docstring for the project's
    position on masking.
    """
    __tablename__ = 'rank_provider_config'

    id = db.Column(db.Integer, primary_key=True)
    instance_id = db.Column(
        db.Integer,
        db.ForeignKey('ql_instance.id', ondelete='CASCADE'),
        nullable=False, unique=True,
    )
    provider_type = db.Column(db.String(32), nullable=False)
    base_url = db.Column(db.String(255), nullable=True)
    api_key = db.Column(db.String(255), nullable=True)
    # Optional override. Blank means "derive from the live gametype" — the
    # normal case for qlstats and Slipgate. Set for providers with their own
    # pool names, e.g. elo-service's "ffa_auto".
    game_type = db.Column(db.String(16), nullable=True)
    extra = db.Column(db.Text, nullable=True)  # JSON; qlstats' elo|elo_b selector
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_updated = db.Column(
        db.DateTime, default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    def extra_dict(self):
        """The extra blob as a dict; {} when unset or malformed."""
        if not self.extra:
            return {}
        try:
            parsed = json.loads(self.extra)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def to_dict(self):
        return {
            'provider_type': self.provider_type,
            'base_url': self.base_url,
            'api_key': self.api_key,
            'game_type': self.game_type,
            'extra': self.extra_dict(),
            'enabled': self.enabled,
        }
```

`json` and `datetime` are already imported at the top of `ui/models.py:1-3`.

- [ ] **Step 4: Add the relationship on `QLInstance`**

Inside `class QLInstance`, alongside the other relationship declarations, add:

```python
    rank_provider_config = db.relationship(
        'RankProviderConfig', uselist=False,
        cascade='all, delete-orphan', passive_deletes=True,
        backref='instance',
    )
```

Do **not** add anything rank-related to `QLInstance.to_dict()`. `/api/v1/instances` strips a denylist (`ui/routes/external_api_routes.py:8`), so anything added to `to_dict()` is exposed to every external API key holder by default — a different principal from the logged-in operator.

- [ ] **Step 5: Write the migration**

Create `migrations/versions/20260920120000_add_rank_provider_config.py`:

```python
"""add rank_provider_config

Revision ID: 20260920120000
Revises: 20260915120000
Create Date: 2026-09-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260920120000'
down_revision = '20260915120000'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'rank_provider_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('instance_id', sa.Integer(), nullable=False),
        sa.Column('provider_type', sa.String(length=32), nullable=False),
        sa.Column('base_url', sa.String(length=255), nullable=True),
        sa.Column('api_key', sa.String(length=255), nullable=True),
        sa.Column('game_type', sa.String(length=16), nullable=True),
        sa.Column('extra', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['instance_id'], ['ql_instance.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('instance_id'),
    )


def downgrade():
    op.drop_table('rank_provider_config')
```

- [ ] **Step 6: Run the tests**

Run: `pytest tests/test_rank_provider_migration.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Verify the head is single**

Run: `.venv/bin/flask db heads`
Expected: exactly one line, `20260920120000 (head)`. Two lines means a branch — fix `down_revision` before continuing.

- [ ] **Step 8: Commit**

```bash
git add ui/models.py migrations/versions/20260920120000_add_rank_provider_config.py tests/test_rank_provider_migration.py
git commit -m "feat(rank): add RankProviderConfig model and migration"
```

---

## Task 2: Lifecycle wiring — delete and backup

The spec is emphatic that this lands before the UI. SQLite does not enforce foreign keys by default, and it reuses a freed rowid when the deleted row held the max id — so an orphaned config row can re-bind a stored third-party credential to a newly created, unrelated instance.

**Files:**
- Modify: `ui/task_logic/ansible_instance_mgmt.py:800-805`
- Modify: `ui/task_logic/backup_db_export.py:91-103`
- Modify: `ui/task_logic/backup_db_import.py:62-71` and `:119-126`
- Test: `tests/test_rank_provider_lifecycle.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rank_provider_lifecycle.py`:

```python
"""A config row must not outlive its instance, and must survive a backup trip."""
import json

from ui import db
from ui.models import Host, QLInstance, RankProviderConfig
from ui.task_logic.backup_db_export import serialize_database
from ui.task_logic.backup_db_import import replace_database


def _seed_instance(name='inst-a', port=27960):
    host = Host.query.filter_by(name='host-a').first()
    if host is None:
        host = Host(name='host-a', ip_address='10.0.0.1', ssh_user='root',
                    ssh_key_path='/keys/id', ssh_port=22, provider='vultr')
        db.session.add(host)
        db.session.flush()
    instance = QLInstance(name=name, port=port, hostname='hn', host_id=host.id)
    db.session.add(instance)
    db.session.flush()
    db.session.add(RankProviderConfig(
        instance_id=instance.id, provider_type='elo_service',
        base_url='http://elo:5002', api_key='secret-key',
        game_type='ffa_auto', extra=json.dumps({}), enabled=True,
    ))
    db.session.commit()
    return instance.id


def test_deleting_an_instance_removes_its_config(app):
    with app.app_context():
        instance_id = _seed_instance()
        instance = db.session.get(QLInstance, instance_id)
        db.session.delete(instance)
        db.session.commit()
        assert RankProviderConfig.query.filter_by(instance_id=instance_id).count() == 0


def test_config_is_exported(app):
    with app.app_context():
        instance_id = _seed_instance()
        snapshot = serialize_database()
        assert 'rank_provider_configs' in snapshot
        row = snapshot['rank_provider_configs'][0]
        assert row['instance_id'] == instance_id
        assert row['provider_type'] == 'elo_service'
        assert row['api_key'] == 'secret-key'


def test_backup_round_trip_reattaches_the_config(app):
    with app.app_context():
        instance_id = _seed_instance()
        snapshot = serialize_database()
        replace_database(snapshot)
        db.session.commit()
        configs = RankProviderConfig.query.all()
        assert len(configs) == 1
        assert configs[0].instance_id == instance_id
        assert configs[0].api_key == 'secret-key'


def test_restore_does_not_strand_a_config_on_a_reused_id(app):
    """A pre-existing config for id N must not survive a restore that creates a
    DIFFERENT instance with id N — otherwise one operator's token silently
    points at another operator's server."""
    with app.app_context():
        _seed_instance(name='old', port=27960)
        snapshot = serialize_database()
        # An archive that has the same instance id but no config row for it.
        snapshot['rank_provider_configs'] = []
        replace_database(snapshot)
        db.session.commit()
        assert RankProviderConfig.query.count() == 0


def test_an_older_archive_without_the_key_still_restores(app):
    """'rank_provider_configs' is optional, following the 'operators' precedent."""
    with app.app_context():
        _seed_instance()
        snapshot = serialize_database()
        del snapshot['rank_provider_configs']
        replace_database(snapshot)
        db.session.commit()
        assert RankProviderConfig.query.count() == 0
        assert QLInstance.query.count() == 1
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `pytest tests/test_rank_provider_lifecycle.py -v`
Expected: FAIL — `KeyError: 'rank_provider_configs'` on the export tests.

- [ ] **Step 3: Add the export row serializer**

In `ui/task_logic/backup_db_export.py`, add `RankProviderConfig` to the model imports at the top, then add this function next to the other `_*_row` helpers:

```python
def _rank_provider_config_row(row):
    return {
        'id': row.id, 'instance_id': row.instance_id,
        'provider_type': row.provider_type, 'base_url': row.base_url,
        'api_key': row.api_key, 'game_type': row.game_type,
        'extra': row.extra, 'enabled': row.enabled,
        'created_at': _iso(row.created_at), 'last_updated': _iso(row.last_updated),
    }
```

`api_key` travels in the clear, following `ApiKey.key`, which is already exported that way (`backup_db_export.py:100`). The archive's existing "this file is sensitive" posture covers it.

- [ ] **Step 4: Add it to `serialize_database()`**

In the returned dict, after the `'operators'` line:

```python
        'rank_provider_configs': [
            _rank_provider_config_row(r)
            for r in RankProviderConfig.query.order_by(RankProviderConfig.id).all()
        ],
```

- [ ] **Step 5: Add the wipe, children first**

In `ui/task_logic/backup_db_import.py`, import `RankProviderConfig`, then in the wipe block add the delete **above** `QLInstance.query.delete()` — it is a child of `ql_instance`:

```python
    # Children before parents so no foreign key is ever left dangling
    # mid-wipe (QLInstance.host_id -> Host.id).
    RankProviderConfig.query.delete()
    BinaryMetadata.query.delete()
    QLInstance.query.delete()
```

Placing it after `QLInstance.query.delete()` is the bug this test guards: the rows would be orphaned, not removed.

- [ ] **Step 6: Add the optional restore loop**

After the `operators` loop, following the same optional-key precedent:

```python
    # 'rank_provider_configs' is intentionally not in _REQUIRED_KEYS: older
    # backups predate this table and simply have none to restore.
    for row in data.get('rank_provider_configs') or []:
        db.session.add(RankProviderConfig(
            id=row['id'], instance_id=row['instance_id'],
            provider_type=row['provider_type'], base_url=row.get('base_url'),
            api_key=row.get('api_key'), game_type=row.get('game_type'),
            extra=row.get('extra'), enabled=row.get('enabled', True),
            created_at=_parse_dt(row.get('created_at')),
            last_updated=_parse_dt(row.get('last_updated')),
        ))
```

- [ ] **Step 7: Add the explicit delete in `delete_instance_logic`**

In `ui/task_logic/ansible_instance_mgmt.py`, import the model at the top with the other model imports, then change the delete block at `:801-803` from:

```python
            instance_name_for_log = instance.name # Store name before deleting
            db.session.delete(instance)
```

to:

```python
            instance_name_for_log = instance.name # Store name before deleting
            # Explicit, not relying on SQLite FK enforcement (off by default).
            # SQLite reuses a freed rowid, so an orphaned config row can re-bind
            # a stored third-party credential to a later, unrelated instance.
            RankProviderConfig.query.filter_by(instance_id=instance.id).delete()
            db.session.delete(instance)
```

- [ ] **Step 8: Run the tests**

Run: `pytest tests/test_rank_provider_lifecycle.py -v`
Expected: PASS (5 tests)

- [ ] **Step 9: Run the existing backup tests for regressions**

Run: `pytest tests/test_backup_routes.py -v`
Expected: PASS, no new failures.

- [ ] **Step 10: Commit**

```bash
git add ui/task_logic/backup_db_export.py ui/task_logic/backup_db_import.py ui/task_logic/ansible_instance_mgmt.py tests/test_rank_provider_lifecycle.py
git commit -m "feat(rank): wire RankProviderConfig into delete and backup lifecycle"
```

---

## Task 3: Provider base and registry

**Files:**
- Create: `ui/rank_providers/__init__.py`, `ui/rank_providers/base.py`, `ui/rank_providers/registry.py`
- Test: `tests/test_rank_providers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_rank_providers.py`:

```python
"""Adapter contract tests. Fixtures are transcribed from each provider's real
client, not guessed — see the spec's 'Provider API shapes'."""
import pytest

from ui.rank_providers.base import RankProvider
from ui.rank_providers.registry import PROVIDER_TYPES, build_provider


def test_registry_holds_the_three_providers():
    assert set(PROVIDER_TYPES) == {'qlstats', 'slipgate', 'elo_service'}
    for cls in PROVIDER_TYPES.values():
        assert issubclass(cls, RankProvider)


def test_build_provider_returns_none_for_an_unknown_type():
    assert build_provider('nope', 'http://x', None, {}) is None


def test_build_provider_constructs_a_known_type():
    provider = build_provider('slipgate', 'https://slipgate.gg/api/v1', 'tok', {})
    assert provider.base_url == 'https://slipgate.gg/api/v1'
    assert provider.api_key == 'tok'
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `pytest tests/test_rank_providers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.rank_providers'`

- [ ] **Step 3: Write `base.py`**

Create `ui/rank_providers/base.py`:

```python
"""The shared rank-provider interface.

Every adapter converts its own provider's shape into RankResult and swallows
its own failures. Callers never see a provider exception and never see a
provider's own key type — see the string-key note on fetch_ratings.
"""
import logging
from abc import ABC, abstractmethod
from typing import TypedDict

logger = logging.getLogger(__name__)

# Connect and read timeouts for every outbound provider call. Short on purpose:
# this rides a synchronous request the UI polls.
PROVIDER_TIMEOUT = (3, 3)


class RankResult(TypedDict):
    rating: float | None   # numeric when the provider gives one; carried, not rendered
    display: str           # what the table actually shows
    provisional: bool      # carried, not rendered in this slice


class RankProvider(ABC):
    def __init__(self, base_url: str, api_key: str | None, extra: dict):
        self.base_url = (base_url or '').rstrip('/')
        self.api_key = api_key or None
        self.extra = extra or {}

    @abstractmethod
    def fetch_ratings(self, steam_ids: list[str], game_type: str | None) -> dict[str, RankResult]:
        """Returns {steam_id: RankResult}, keyed by the steam id as a **string**.

        Missing or unranked players are omitted, not raised. Network and HTTP
        errors are caught internally and yield an empty dict.

        The string key is load-bearing. balance.py:308 does
        `sid = int(p["steamid"])`; an adapter that mirrors that produces int
        keys, every frontend lookup misses, and the whole feature renders a
        silent column of dashes.
        """

    @abstractmethod
    def map_game_type(self, qlsm_gametype: str) -> str | None:
        """This provider's own code for a QLSM gametype, or None when the mode
        is not rated here. None is a correct, quiet outcome: no request is made
        and the column is empty."""

    def _log_failure(self, instance_id, status_code=None, exc=None):
        """Provider type, instance id and status code ONLY.

        Never headers, never bodies, never the config object: these logs ship to
        Loki, so a token in a 'let's log the failed request' line does not stay
        local. Rank failures never reach append_log() either — that field is
        rendered verbatim in the UI.
        """
        logger.warning(
            'rank provider %s failed for instance %s (status=%s, error=%s)',
            type(self).__name__, instance_id, status_code,
            type(exc).__name__ if exc else None,
        )
```

- [ ] **Step 4: Write `__init__.py`**

Create `ui/rank_providers/__init__.py`:

```python
from ui.rank_providers.base import PROVIDER_TIMEOUT, RankProvider, RankResult

__all__ = ['PROVIDER_TIMEOUT', 'RankProvider', 'RankResult']
```

- [ ] **Step 5: Write `registry.py`**

Create `ui/rank_providers/registry.py`:

```python
"""Provider type string -> adapter class.

Adding a provider is a new module plus one line here. It is never a schema
change or a route change.
"""
from ui.rank_providers.elo_service import ThunderdomeEloProvider
from ui.rank_providers.qlstats import QlstatsProvider
from ui.rank_providers.slipgate import SlipgateProvider

PROVIDER_TYPES = {
    'qlstats': QlstatsProvider,
    'slipgate': SlipgateProvider,
    'elo_service': ThunderdomeEloProvider,
}


def build_provider(provider_type, base_url, api_key, extra):
    """An adapter instance, or None when provider_type is not registered."""
    cls = PROVIDER_TYPES.get(provider_type)
    if cls is None:
        return None
    return cls(base_url, api_key, extra)
```

This imports the three adapter modules, which do not exist yet — Tasks 4, 5 and 6 create them. The registry test stays red until Task 6 lands. That is expected; do not stub the adapters to make it pass early.

- [ ] **Step 6: Commit**

```bash
git add ui/rank_providers/__init__.py ui/rank_providers/base.py ui/rank_providers/registry.py tests/test_rank_providers.py
git commit -m "feat(rank): add RankProvider interface and registry"
```

---

## Task 4: qlstats adapter

Verified against `configs/presets/_builtin/default-minqlxtended/scripts/balance.py`.

- `_api_url` is `f"http://{host}/{api}/"` (`:127-131`) where `api` is `elo` or `elo_b` — hence this plan's `base_url` + `extra["rating_system"]` split.
- Bulk lookup `+`-joins ids into the path: `url = self._api_url + "+".join(...)` (`:277`).
- The response is keyed by short game type; the value is read as `self.ratings[steam_id][gametype]["elo"]` (`:411`).
- Supported modes are `ad, ca, ctf, dom, ft, tdm` plus `duel, ffa` externally (`:48-56`). Everything else is unrated here.
- **A bucket with `elo == 0` and `games == 0` means "the API has nothing for this player"** — `balance.py:326-327` matches exactly that shape and substitutes `DEFAULT_RATING` (1500, `:46-47`). QLSM does **not** substitute 1500: an in-game balancer needs a number to divide teams with, a read-only display does not, and an invented rating shown as if it came from qlstats is worse than a dash. The adapter **omits** the player instead, so the cell renders `—`. Without the guard the cell shows a literal `0`, indistinguishable from a genuine rating and wrong under either reading.
- No auth.

**Files:**
- Create: `ui/rank_providers/qlstats.py`
- Test: `tests/test_rank_providers.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rank_providers.py`:

```python
from unittest.mock import MagicMock, patch

from ui.rank_providers.qlstats import QlstatsProvider

QLSTATS_BODY = {
    'players': [
        {'steamid': '76561198000000001', 'ca': {'elo': 1650, 'games': 120}},
        {'steamid': '76561198000000002', 'ca': {'elo': 1200, 'games': 4}},
        {'steamid': '76561198000000003', 'ctf': {'elo': 1400, 'games': 9}},
        # balance.py:326-327's "the API has nothing" shape.
        {'steamid': '76561198000000004', 'ca': {'elo': 0, 'games': 0}},
    ],
    'untracked': ['76561198000000002'],
}


def _response(status=200, body=None):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body if body is not None else {}
    return response


def test_qlstats_reads_elo_for_the_requested_game_type():
    provider = QlstatsProvider('http://qlstats.net', None, {'rating_system': 'elo'})
    with patch('ui.rank_providers.qlstats.requests.get',
               return_value=_response(body=QLSTATS_BODY)) as get:
        result = provider.fetch_ratings(
            ['76561198000000001', '76561198000000002', '76561198000000003',
             '76561198000000004'], 'ca')
    url = get.call_args[0][0]
    assert url == ('http://qlstats.net/elo/'
                   '76561198000000001+76561198000000002+76561198000000003'
                   '+76561198000000004')
    # Only the first: the second is untracked, the third has no 'ca' key, the
    # fourth is the zero/zero "nothing known" bucket.
    assert list(result) == ['76561198000000001']
    assert result['76561198000000001']['display'] == '1650'
    assert result['76561198000000001']['rating'] == 1650.0


def test_qlstats_omits_a_zero_elo_zero_games_bucket():
    """balance.py:326-327 reads elo==0 and games==0 as 'the API has nothing'
    and substitutes DEFAULT_RATING. QLSM does not invent 1500 for a read-only
    display — it omits the player so the cell shows a dash. Without this guard
    the cell renders a literal 0, which looks like a real rating."""
    provider = QlstatsProvider('http://qlstats.net', None, {})
    with patch('ui.rank_providers.qlstats.requests.get',
               return_value=_response(body=QLSTATS_BODY)):
        result = provider.fetch_ratings(['76561198000000004'], 'ca')
    assert '76561198000000004' not in result


def test_qlstats_honours_the_elo_b_rating_system():
    provider = QlstatsProvider('http://qlstats.net', None, {'rating_system': 'elo_b'})
    with patch('ui.rank_providers.qlstats.requests.get',
               return_value=_response(body={'players': []})) as get:
        provider.fetch_ratings(['76561198000000001'], 'ca')
    assert get.call_args[0][0].startswith('http://qlstats.net/elo_b/')


def test_qlstats_keys_are_strings():
    provider = QlstatsProvider('http://qlstats.net', None, {})
    with patch('ui.rank_providers.qlstats.requests.get',
               return_value=_response(body=QLSTATS_BODY)):
        result = provider.fetch_ratings(['76561198000000001'], 'ca')
    assert all(isinstance(k, str) for k in result)


def test_qlstats_network_error_is_an_empty_dict():
    import requests as requests_lib
    provider = QlstatsProvider('http://qlstats.net', None, {})
    with patch('ui.rank_providers.qlstats.requests.get',
               side_effect=requests_lib.RequestException('boom')):
        assert provider.fetch_ratings(['76561198000000001'], 'ca') == {}


def test_qlstats_non_200_is_an_empty_dict():
    provider = QlstatsProvider('http://qlstats.net', None, {})
    with patch('ui.rank_providers.qlstats.requests.get', return_value=_response(status=503)):
        assert provider.fetch_ratings(['76561198000000001'], 'ca') == {}


@pytest.mark.parametrize('qlsm,expected', [
    ('ca', 'ca'), ('ctf', 'ctf'), ('tdm', 'tdm'), ('ft', 'ft'),
    ('ad', 'ad'), ('dom', 'dom'), ('duel', 'duel'), ('ffa', 'ffa'),
    ('har', None), ('rr', None), ('ob', None), ('race', None), ('', None),
])
def test_qlstats_game_type_mapping(qlsm, expected):
    provider = QlstatsProvider('http://qlstats.net', None, {})
    assert provider.map_game_type(qlsm) == expected
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `pytest tests/test_rank_providers.py -k qlstats -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.rank_providers.qlstats'`

- [ ] **Step 3: Write the adapter**

Create `ui/rank_providers/qlstats.py`:

```python
"""qlstats adapter.

Verified against the bundled balance.py plugin:
  - URL shape:  f"http://{host}/{api}/" + "+".join(ids)   (:127-131, :277)
  - value:      players[i][<game_type>]["elo"]            (:411)
  - modes:      SUPPORTED_GAMETYPES + duel/ffa            (:48-56)
No auth.
"""
import requests

from ui.rank_providers.base import PROVIDER_TIMEOUT, RankProvider, RankResult

# balance.py's SUPPORTED_GAMETYPES plus the two it supports externally only.
# qlstats uses the same short codes QLSM does, so this is an identity map
# restricted to what qlstats actually rates.
_SUPPORTED = {'ad', 'ca', 'ctf', 'dom', 'ft', 'tdm', 'duel', 'ffa'}

DEFAULT_RATING_SYSTEM = 'elo'


class QlstatsProvider(RankProvider):
    def map_game_type(self, qlsm_gametype):
        code = (qlsm_gametype or '').strip().lower()
        return code if code in _SUPPORTED else None

    def fetch_ratings(self, steam_ids, game_type, instance_id=None):
        if not steam_ids or not game_type:
            return {}
        system = self.extra.get('rating_system') or DEFAULT_RATING_SYSTEM
        url = f"{self.base_url}/{system}/" + '+'.join(str(s) for s in steam_ids)
        try:
            response = requests.get(url, timeout=PROVIDER_TIMEOUT)
        except requests.RequestException as exc:
            self._log_failure(instance_id, exc=exc)
            return {}
        if response.status_code != 200:
            self._log_failure(instance_id, status_code=response.status_code)
            return {}
        try:
            body = response.json()
        except ValueError:
            self._log_failure(instance_id, status_code=response.status_code)
            return {}
        if not isinstance(body, dict):
            return {}

        untracked = {str(sid) for sid in (body.get('untracked') or [])}
        out = {}
        for entry in body.get('players') or []:
            if not isinstance(entry, dict):
                continue
            # str(), never int() — balance.py:308 does int() and that key type
            # would miss every lookup on the frontend.
            steam_id = str(entry.get('steamid') or '').strip()
            if not steam_id or steam_id in untracked:
                continue
            bucket = entry.get(game_type)
            if not isinstance(bucket, dict):
                continue
            elo = bucket.get('elo')
            if elo is None:
                continue
            # balance.py:326-327 treats elo==0 AND games==0 as "the API has
            # nothing for this player" and substitutes DEFAULT_RATING (1500).
            # A read-only display does not invent a number: omit the player so
            # the cell shows a dash. Without this the cell renders a literal 0.
            if elo == 0 and bucket.get('games') == 0:
                continue
            out[steam_id] = RankResult(
                rating=float(elo), display=str(elo), provisional=False,
            )
        return out
```

Note the `instance_id=None` keyword on `fetch_ratings`: it exists only so failures can be logged against an instance. Add it to the ABC signature in `base.py` as well:

```python
    @abstractmethod
    def fetch_ratings(self, steam_ids: list[str], game_type: str | None,
                      instance_id: int | None = None) -> dict[str, RankResult]:
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_rank_providers.py -k qlstats -v`
Expected: PASS (19 tests, counting the parametrized mapping cases)

- [ ] **Step 5: Commit**

```bash
git add ui/rank_providers/qlstats.py ui/rank_providers/base.py tests/test_rank_providers.py
git commit -m "feat(rank): add qlstats adapter"
```

---

## Task 5: Slipgate adapter

Verified against Slipgate's own minqlxtended plugin v1.10.1. **The fixtures below are transcribed into the test module on purpose** — the source file is an operator-supplied artifact at the checkout root, not a repo file, and the suite must not depend on it staying on disk.

Facts, with line references into that plugin:
- Auth: `Authorization: Bearer <sgs_… token>` (`:456`).
- Bulk: `POST /ratings/bulk` with `{"steam_ids": [...], "game_type": code}` → `{"players": [{steam_id, display, tier_name, provisional, found}]}` (`:2496-2507`).
- Single: `GET /players/{steam_id}/ratings/{code}`, **404 means unranked** (`:2427`). **QLSM never calls this path** — the adapter only ever POSTs to the bulk endpoint. It is documented here for reference, and the adapter's 404 branch on the bulk POST is belt-and-braces rather than a modelled case, because the plugin documents no 404 there.
- **Two unranked shapes, both must be handled**: `found` false, and present-with-`display`-null (`:2542-2547`).
- `display` is rendered whole and never parsed. It is named `display`, not `rating`.
- `GAMETYPE_CODES` (`:124-134`) holds **eleven** codes, so `_GAME_TYPE_MAP` below has eleven entries: four that differ (`har`→`harvester`, `dom`→`domination`, `rr`→`redrover`, `1f`→`1flag`) and seven that pass through. **One-flag is the easy one to drop and the expensive one to miss**: a one-flag instance pointed at Slipgate would get `None` from `map_game_type`, make no request at all, and show a permanently empty column with no error anywhere — the exact failure this mapping exists to prevent. `1f` is the short code both runtimes produce (`minqlx/_core.py:54-55`, `minqlxtended/_enums.py:357`). The longer spellings `1fctf` and `ictf` in `LiveServerStatusModal.jsx:26` are speculative aliases in a set whose own comment says "and common aliases"; no plugin emits them, so they are deliberately **not** mapped.

**Files:**
- Create: `ui/rank_providers/slipgate.py`
- Test: `tests/test_rank_providers.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rank_providers.py`:

```python
from ui.rank_providers.slipgate import SlipgateProvider

# Transcribed from slipgate.py v1.10.1 fetch_ratings/:2496-2507 and
# rating_entry/:2542-2547. Both unranked shapes are represented.
SLIPGATE_BODY = {
    'players': [
        {'steam_id': '76561198000000001', 'display': '1650',
         'tier_name': 'Gold', 'provisional': False, 'found': True},
        {'steam_id': '76561198000000002', 'display': '1200 (Silver)',
         'tier_name': 'Silver', 'provisional': True, 'found': True},
        {'steam_id': '76561198000000003', 'display': None,
         'tier_name': None, 'provisional': False, 'found': True},
        {'steam_id': '76561198000000004', 'display': None,
         'tier_name': None, 'provisional': False, 'found': False},
    ],
}


def test_slipgate_parses_the_bulk_response():
    provider = SlipgateProvider('https://slipgate.gg/api/v1', 'sgs_tok', {})
    with patch('ui.rank_providers.slipgate.requests.post',
               return_value=_response(body=SLIPGATE_BODY)) as post:
        result = provider.fetch_ratings(
            ['76561198000000001', '76561198000000002',
             '76561198000000003', '76561198000000004'], 'ca')
    assert post.call_args[0][0] == 'https://slipgate.gg/api/v1/ratings/bulk'
    assert post.call_args[1]['json'] == {
        'steam_ids': ['76561198000000001', '76561198000000002',
                      '76561198000000003', '76561198000000004'],
        'game_type': 'ca',
    }
    # Both unranked shapes drop out: found=False AND found=True/display=None.
    assert set(result) == {'76561198000000001', '76561198000000002'}


def test_slipgate_returns_display_verbatim_and_never_parses_it():
    """display may be a label, not a number. Printing it whole is the contract."""
    provider = SlipgateProvider('https://slipgate.gg/api/v1', 'sgs_tok', {})
    with patch('ui.rank_providers.slipgate.requests.post',
               return_value=_response(body=SLIPGATE_BODY)):
        result = provider.fetch_ratings(['76561198000000002'], 'ca')
    assert result['76561198000000002']['display'] == '1200 (Silver)'
    assert result['76561198000000002']['rating'] is None
    assert result['76561198000000002']['provisional'] is True


def test_slipgate_sends_the_bearer_token():
    provider = SlipgateProvider('https://slipgate.gg/api/v1', 'sgs_tok', {})
    with patch('ui.rank_providers.slipgate.requests.post',
               return_value=_response(body={'players': []})) as post:
        provider.fetch_ratings(['76561198000000001'], 'ca')
    assert post.call_args[1]['headers']['Authorization'] == 'Bearer sgs_tok'


def test_slipgate_omits_the_header_when_there_is_no_token():
    provider = SlipgateProvider('https://slipgate.gg/api/v1', None, {})
    with patch('ui.rank_providers.slipgate.requests.post',
               return_value=_response(body={'players': []})) as post:
        provider.fetch_ratings(['76561198000000001'], 'ca')
    assert 'Authorization' not in post.call_args[1]['headers']


def test_slipgate_404_is_not_an_error():
    provider = SlipgateProvider('https://slipgate.gg/api/v1', 'sgs_tok', {})
    with patch('ui.rank_providers.slipgate.requests.post', return_value=_response(status=404)):
        assert provider.fetch_ratings(['76561198000000001'], 'ca') == {}


def test_slipgate_keys_are_strings():
    provider = SlipgateProvider('https://slipgate.gg/api/v1', 'sgs_tok', {})
    body = {'players': [{'steam_id': 76561198000000001, 'display': '1650',
                         'provisional': False, 'found': True}]}
    with patch('ui.rank_providers.slipgate.requests.post', return_value=_response(body=body)):
        result = provider.fetch_ratings(['76561198000000001'], 'ca')
    assert list(result) == ['76561198000000001']


@pytest.mark.parametrize('qlsm,expected', [
    # The four that differ. har->harvester and 1f->1flag are THE regression
    # guards for the silent-empty-column failure this feature exists to avoid.
    ('har', 'harvester'), ('dom', 'domination'), ('rr', 'redrover'),
    ('1f', '1flag'),
    # The seven that pass through unchanged.
    ('ca', 'ca'), ('ctf', 'ctf'), ('tdm', 'tdm'), ('ft', 'ft'),
    ('ffa', 'ffa'), ('duel', 'duel'), ('ad', 'ad'),
    # Unrated here. '1fctf' and 'ictf' are frontend guesses that no plugin
    # emits, so they are deliberately unmapped rather than aliased to 1flag.
    ('race', None), ('ob', None), ('1fctf', None), ('ictf', None), ('', None),
])
def test_slipgate_game_type_mapping(qlsm, expected):
    provider = SlipgateProvider('https://slipgate.gg/api/v1', 'sgs_tok', {})
    assert provider.map_game_type(qlsm) == expected
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `pytest tests/test_rank_providers.py -k slipgate -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.rank_providers.slipgate'`

- [ ] **Step 3: Write the adapter**

Create `ui/rank_providers/slipgate.py`:

```python
"""Slipgate adapter.

Verified against Slipgate's own minqlxtended plugin v1.10.1:
  - auth:   Authorization: Bearer <sgs_...>                (:456)
  - bulk:   POST /ratings/bulk {steam_ids, game_type}      (:2496-2507)
  - 404 on the single-player path means unranked           (:2427)
  - TWO unranked shapes: found=False, and display=None     (:2542-2547)
  - codes:  the 11 long forms in GAMETYPE_CODES            (:124-134)

Only the bulk POST is ever called. The single-player path above is documented
for reference and unused.

'display' is rendered whole and never parsed: the field is named display, not
rating, and may well be a label like "1650 (Gold)".
"""
import requests

from ui.rank_providers.base import PROVIDER_TIMEOUT, RankProvider, RankResult

# QLSM's short codes -> Slipgate's own vocabulary. All 11 of GAMETYPE_CODES:
# four differ, seven pass through. Sending 'har' or '1f' unmapped returns
# nothing at all, with no error — exactly the undiagnosable empty column this
# mapping exists to prevent.
#
# '1fctf' and 'ictf' from LiveServerStatusModal.jsx:26 are NOT mapped: they are
# speculative aliases in a set whose own comment says "and common aliases", and
# neither runtime emits them. '1f' is the real short code
# (minqlx/_core.py:54-55, minqlxtended/_enums.py:357).
_GAME_TYPE_MAP = {
    'ca': 'ca', 'ctf': 'ctf', 'tdm': 'tdm', 'ft': 'ft',
    'ffa': 'ffa', 'duel': 'duel', 'ad': 'ad',
    'har': 'harvester', 'dom': 'domination', 'rr': 'redrover',
    '1f': '1flag',
}


class SlipgateProvider(RankProvider):
    def map_game_type(self, qlsm_gametype):
        return _GAME_TYPE_MAP.get((qlsm_gametype or '').strip().lower())

    def _headers(self):
        headers = {}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        return headers

    def fetch_ratings(self, steam_ids, game_type, instance_id=None):
        if not steam_ids or not game_type:
            return {}
        payload = {'steam_ids': [str(s) for s in steam_ids], 'game_type': game_type}
        try:
            response = requests.post(
                f'{self.base_url}/ratings/bulk',
                json=payload, headers=self._headers(), timeout=PROVIDER_TIMEOUT,
            )
        except requests.RequestException as exc:
            self._log_failure(instance_id, exc=exc)
            return {}
        if response.status_code == 404:
            # Belt-and-braces. The plugin documents a 404 only on the
            # single-player path (:2427), which QLSM never calls; nothing
            # documents one on the bulk POST. Kept because if it ever happens it
            # means unranked, not an error, and must not be logged as a failure.
            return {}
        if response.status_code != 200:
            self._log_failure(instance_id, status_code=response.status_code)
            return {}
        try:
            body = response.json()
        except ValueError:
            self._log_failure(instance_id, status_code=response.status_code)
            return {}
        if not isinstance(body, dict):
            return {}

        out = {}
        for entry in body.get('players') or []:
            if not isinstance(entry, dict):
                continue
            steam_id = str(entry.get('steam_id') or '').strip()
            if not steam_id:
                continue
            # Shape one: explicitly not found.
            if not entry.get('found'):
                continue
            display = entry.get('display')
            # Shape two: found, but no rating to show. Same meaning, and an
            # adapter that checks only the first renders a wrong cell here.
            if display is None:
                continue
            out[steam_id] = RankResult(
                rating=None,                    # display is not necessarily numeric
                display=str(display),           # verbatim, never parsed
                provisional=bool(entry.get('provisional')),
            )
        return out
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_rank_providers.py -k slipgate -v`
Expected: PASS (22 tests, counting the parametrized mapping cases)

- [ ] **Step 5: Commit**

```bash
git add ui/rank_providers/slipgate.py tests/test_rank_providers.py
git commit -m "feat(rank): add Slipgate adapter"
```

---

## Task 6: Thunderdome elo-service adapter

Verified against `configs/presets/_builtin/default-minqlxtended/scripts/ranked.py`.

- Bulk: `GET /players?ids=a,b,c&mode=<mode>` → `{steam_id: {name, mu, sort_score, wins, losses} | null}`.
- Single: `GET /player/{steam_id}?mode=<mode>`, **404 = unranked** (`:666`). Cite `:666` alone: `:597` is the 404 of a different endpoint, the `GET /player/{steam_id}` name lookup with no `?mode=`, and is not the path this adapter models.
- **The rating is `sort_score or mu`** (`:466` bulk, `:672` single). There is **no `rating` key** on these two endpoints — an adapter that reads `rating` returns nothing against a perfectly healthy service. This was the single worst bug the pre-implementation review caught.
- **Python's `or`, literally.** Both call sites read `int(d.get("sort_score") or d["mu"])`, so a `sort_score` of `0` is treated as absent and `mu` is used. An `is None` check diverges exactly there and QLSM would show `0` for a player whose in-game `!rating` shows a real number. `or` also swallows a genuine `sort_score` of `0.0` — that is what the plugin does on purpose, and matching the documented source beats inventing a third behaviour.
- Auth: `X-API-Key`, always sent when configured.
- `mode` is a service-specific pool name (`ffa_auto`) with no QL gametype behind it, so `map_game_type` returns `None` and this provider relies on the `game_type` override column.

**Files:**
- Create: `ui/rank_providers/elo_service.py`
- Test: `tests/test_rank_providers.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rank_providers.py`:

```python
from ui.rank_providers.elo_service import ThunderdomeEloProvider

ELO_SERVICE_BODY = {
    '76561198000000001': {'name': 'a', 'mu': 25.1, 'sort_score': 1802.5,
                          'wins': 10, 'losses': 3},
    '76561198000000002': {'name': 'b', 'mu': 18.0, 'sort_score': None,
                          'wins': 0, 'losses': 0},
    '76561198000000003': None,
    # The `or` guard: 0 is falsy, so the plugin falls through to mu here.
    '76561198000000004': {'name': 'd', 'mu': 22.5, 'sort_score': 0,
                          'wins': 0, 'losses': 0},
}


def test_elo_service_prefers_sort_score_and_falls_back_to_mu():
    """There is NO 'rating' key on this endpoint. Reading one returns nothing
    for every player against a healthy service."""
    provider = ThunderdomeEloProvider('http://elo:5002', 'k', {})
    with patch('ui.rank_providers.elo_service.requests.get',
               return_value=_response(body=ELO_SERVICE_BODY)) as get:
        result = provider.fetch_ratings(
            ['76561198000000001', '76561198000000002', '76561198000000003'],
            'ffa_auto')
    assert get.call_args[1]['params'] == {
        'ids': '76561198000000001,76561198000000002,76561198000000003',
        'mode': 'ffa_auto',
    }
    assert result['76561198000000001']['rating'] == 1802.5
    assert result['76561198000000001']['display'] == '1802.5'
    # sort_score None -> falls back to mu
    assert result['76561198000000002']['rating'] == 18.0
    # a null entry yields no result at all
    assert '76561198000000003' not in result


def test_elo_service_treats_a_zero_sort_score_as_absent():
    """ranked.py:466 and :672 both read `int(d.get("sort_score") or d["mu"])`.
    Python's `or`, literally: 0 is falsy and mu wins. An `is None` check
    diverges exactly here and shows 0 for a player whose !rating shows 22."""
    provider = ThunderdomeEloProvider('http://elo:5002', 'k', {})
    with patch('ui.rank_providers.elo_service.requests.get',
               return_value=_response(body=ELO_SERVICE_BODY)):
        result = provider.fetch_ratings(['76561198000000004'], 'ffa_auto')
    assert result['76561198000000004']['rating'] == 22.5


def test_elo_service_sends_the_api_key():
    provider = ThunderdomeEloProvider('http://elo:5002', 'k', {})
    with patch('ui.rank_providers.elo_service.requests.get',
               return_value=_response(body={})) as get:
        provider.fetch_ratings(['76561198000000001'], 'ffa_auto')
    assert get.call_args[1]['headers']['X-API-Key'] == 'k'


def test_elo_service_404_is_not_an_error():
    provider = ThunderdomeEloProvider('http://elo:5002', 'k', {})
    with patch('ui.rank_providers.elo_service.requests.get', return_value=_response(status=404)):
        assert provider.fetch_ratings(['76561198000000001'], 'ffa_auto') == {}


def test_elo_service_network_error_is_an_empty_dict():
    import requests as requests_lib
    provider = ThunderdomeEloProvider('http://elo:5002', 'k', {})
    with patch('ui.rank_providers.elo_service.requests.get',
               side_effect=requests_lib.RequestException('boom')):
        assert provider.fetch_ratings(['76561198000000001'], 'ffa_auto') == {}


def test_elo_service_keys_are_strings():
    provider = ThunderdomeEloProvider('http://elo:5002', 'k', {})
    body = {76561198000000001: {'mu': 25.0, 'sort_score': 1800}}
    with patch('ui.rank_providers.elo_service.requests.get', return_value=_response(body=body)):
        result = provider.fetch_ratings(['76561198000000001'], 'ffa_auto')
    assert list(result) == ['76561198000000001']


def test_elo_service_has_no_derivable_game_type():
    """mode is a service-specific pool name; it can only come from the override."""
    provider = ThunderdomeEloProvider('http://elo:5002', 'k', {})
    for code in ('ca', 'ffa', 'duel', 'har', ''):
        assert provider.map_game_type(code) is None
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `pytest tests/test_rank_providers.py -k elo_service -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.rank_providers.elo_service'`

- [ ] **Step 3: Write the adapter**

Create `ui/rank_providers/elo_service.py`:

```python
"""Thunderdome elo-service adapter.

Verified against the bundled ranked.py plugin:
  - bulk:   GET /players?ids=a,b,c&mode=<mode>
  - single: GET /player/{steam_id}?mode=<mode>, 404 = unranked  (:666)
  - RATING: sort_score or mu                                    (:466, :672)
  - auth:   X-API-Key

:597 is a different endpoint's 404 (the GET /player/{steam_id} name lookup,
no ?mode=) and is not what this adapter models.

There is no 'rating' key on either endpoint. An adapter that reads one returns
None for every player against a perfectly healthy service.
"""
import requests

from ui.rank_providers.base import PROVIDER_TIMEOUT, RankProvider, RankResult


class ThunderdomeEloProvider(RankProvider):
    def map_game_type(self, qlsm_gametype):
        """Always None: 'mode' here is a service-specific pool name such as
        'ffa_auto', which corresponds to no QL gametype. This provider is
        configured through the game_type override column instead."""
        return None

    def _headers(self):
        return {'X-API-Key': self.api_key} if self.api_key else {}

    def fetch_ratings(self, steam_ids, game_type, instance_id=None):
        if not steam_ids or not game_type:
            return {}
        params = {'ids': ','.join(str(s) for s in steam_ids), 'mode': game_type}
        try:
            response = requests.get(
                f'{self.base_url}/players',
                params=params, headers=self._headers(), timeout=PROVIDER_TIMEOUT,
            )
        except requests.RequestException as exc:
            self._log_failure(instance_id, exc=exc)
            return {}
        if response.status_code == 404:
            return {}
        if response.status_code != 200:
            self._log_failure(instance_id, status_code=response.status_code)
            return {}
        try:
            body = response.json()
        except ValueError:
            self._log_failure(instance_id, status_code=response.status_code)
            return {}
        if not isinstance(body, dict):
            return {}

        out = {}
        for steam_id, entry in body.items():
            # A null entry means the service knows nothing about that player.
            if not isinstance(entry, dict):
                continue
            # `or`, not `is None`. ranked.py:466 and :672 both read
            # int(d.get("sort_score") or d["mu"]), so a sort_score of 0 is
            # treated as absent and mu wins. An `is None` check would show 0
            # in QLSM for a player whose in-game !rating shows a real number.
            value = entry.get('sort_score') or entry.get('mu')
            if value is None:
                continue
            try:
                rating = float(value)
            except (TypeError, ValueError):
                continue
            out[str(steam_id)] = RankResult(
                rating=rating,
                display=f'{rating:g}',
                provisional=False,
            )
        return out
```

- [ ] **Step 4: Run the whole adapter suite**

Run: `pytest tests/test_rank_providers.py -v`
Expected: PASS, including the three registry tests from Task 3 that were red until now.

- [ ] **Step 5: Commit**

```bash
git add ui/rank_providers/elo_service.py tests/test_rank_providers.py
git commit -m "feat(rank): add Thunderdome elo-service adapter"
```

---

## Task 7: RankService — validation, game-type resolution, caching

This is where the review's most consequential findings live. Read the steps carefully.

**Files:**
- Create: `ui/rank_providers/service.py`
- Test: `tests/test_rank_service.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rank_service.py`:

```python
"""RankService: id validation, game-type resolution, caching, Redis guard."""
import json
from unittest.mock import MagicMock, patch

import pytest

from ui import db
from ui.models import Host, QLInstance, RankProviderConfig
from ui.rank_providers.service import RankService

VALID_A = '76561198000000001'
VALID_B = '76561198000000002'


def _seed(provider_type='slipgate', game_type=None, enabled=True,
          base_url='https://slipgate.gg/api/v1', extra=None):
    host = Host(name='host-a', ip_address='10.0.0.1', ssh_user='root',
                ssh_key_path='/keys/id', ssh_port=22, provider='vultr')
    db.session.add(host)
    db.session.flush()
    instance = QLInstance(name='inst-a', port=27960, hostname='hn', host_id=host.id)
    db.session.add(instance)
    db.session.flush()
    db.session.add(RankProviderConfig(
        instance_id=instance.id, provider_type=provider_type,
        base_url=base_url, api_key='tok', game_type=game_type,
        extra=json.dumps(extra or {}), enabled=enabled,
    ))
    db.session.commit()
    return instance.id


def _redis(status_gametype='ca', cached=None):
    client = MagicMock()
    client.get.side_effect = lambda key: (
        json.dumps({'gametype': status_gametype}) if key.startswith('server:status:')
        else cached
    )
    client.scan_iter.return_value = []
    return client


# --- steam_ids validation -------------------------------------------------

def test_invalid_ids_are_dropped_silently(app):
    with app.app_context():
        instance_id = _seed()
        service = RankService(_redis())
        with patch.object(service, '_fetch_from_provider', return_value={}) as fetch:
            service.get_ratings(instance_id, ['../../admin', '12345', VALID_A, 'abc'])
        assert fetch.call_args[0][1] == [VALID_A]


def test_ids_are_deduplicated_and_capped(app):
    with app.app_context():
        instance_id = _seed()
        service = RankService(_redis())
        many = [f'7656119{i:010d}' for i in range(100)] + [VALID_A, VALID_A]
        with patch.object(service, '_fetch_from_provider', return_value={}) as fetch:
            service.get_ratings(instance_id, many)
        sent = fetch.call_args[0][1]
        assert len(sent) == 64
        assert len(set(sent)) == 64


def test_no_valid_ids_short_circuits(app):
    with app.app_context():
        instance_id = _seed()
        service = RankService(_redis())
        with patch.object(service, '_fetch_from_provider') as fetch:
            data, configured = service.get_ratings(instance_id, ['nope', '123'])
        assert data == {}
        assert configured is True
        fetch.assert_not_called()


# --- configured flag ------------------------------------------------------

def test_unconfigured_instance_reports_not_configured(app):
    with app.app_context():
        host = Host(name='h', ip_address='1.1.1.1', ssh_user='root',
                    ssh_key_path='/k', ssh_port=22, provider='vultr')
        db.session.add(host)
        db.session.flush()
        instance = QLInstance(name='i', port=27961, hostname='hn', host_id=host.id)
        db.session.add(instance)
        db.session.commit()
        data, configured = RankService(_redis()).get_ratings(instance.id, [VALID_A])
    assert data == {}
    assert configured is False


def test_disabled_config_reports_not_configured_and_never_calls_the_adapter(app):
    with app.app_context():
        instance_id = _seed(enabled=False)
        service = RankService(_redis())
        with patch.object(service, '_fetch_from_provider') as fetch:
            data, configured = service.get_ratings(instance_id, [VALID_A])
        assert (data, configured) == ({}, False)
        fetch.assert_not_called()


def test_config_missing_base_url_reports_not_configured(app):
    with app.app_context():
        instance_id = _seed(base_url=None)
        data, configured = RankService(_redis()).get_ratings(instance_id, [VALID_A])
    assert (data, configured) == ({}, False)


def test_a_failing_provider_is_still_configured(app):
    """configured is about configuration; failure is a different axis."""
    with app.app_context():
        instance_id = _seed()
        service = RankService(_redis())
        with patch.object(service, '_fetch_from_provider', return_value={}):
            data, configured = service.get_ratings(instance_id, [VALID_A])
        assert (data, configured) == ({}, True)


# --- game type resolution -------------------------------------------------

def test_game_type_is_derived_from_live_status(app):
    with app.app_context():
        instance_id = _seed(provider_type='slipgate')
        service = RankService(_redis(status_gametype='har'))
        with patch('ui.rank_providers.slipgate.requests.post') as post:
            post.return_value = MagicMock(status_code=200,
                                          json=MagicMock(return_value={'players': []}))
            service.get_ratings(instance_id, [VALID_A])
        # 'har' must be translated to Slipgate's 'harvester'.
        assert post.call_args[1]['json']['game_type'] == 'harvester'


def test_an_explicit_game_type_overrides_derivation(app):
    with app.app_context():
        instance_id = _seed(provider_type='elo_service', game_type='ffa_auto',
                            base_url='http://elo:5002')
        service = RankService(_redis(status_gametype='ca'))
        with patch('ui.rank_providers.elo_service.requests.get') as get:
            get.return_value = MagicMock(status_code=200, json=MagicMock(return_value={}))
            service.get_ratings(instance_id, [VALID_A])
        assert get.call_args[1]['params']['mode'] == 'ffa_auto'


def test_an_unrated_mode_makes_no_http_call_at_all(app):
    with app.app_context():
        instance_id = _seed(provider_type='slipgate')
        service = RankService(_redis(status_gametype='race'))
        with patch('ui.rank_providers.slipgate.requests.post') as post:
            data, configured = service.get_ratings(instance_id, [VALID_A])
        post.assert_not_called()
        assert (data, configured) == ({}, True)


# --- caching --------------------------------------------------------------

def test_a_cache_hit_skips_the_provider(app):
    with app.app_context():
        instance_id = _seed()
        cached = json.dumps({VALID_A: {'rating': None, 'display': '1650',
                                       'provisional': False}})
        service = RankService(_redis(cached=cached))
        with patch.object(service, '_fetch_from_provider') as fetch:
            data, _ = service.get_ratings(instance_id, [VALID_A])
        fetch.assert_not_called()
        assert data[VALID_A]['display'] == '1650'


def test_a_roster_change_changes_the_cache_key(app):
    with app.app_context():
        instance_id = _seed()
        service = RankService(_redis())
        key_one = service._cache_key(instance_id, service._load_config(instance_id),
                                     'ca', [VALID_A])
        key_two = service._cache_key(instance_id, service._load_config(instance_id),
                                     'ca', [VALID_A, VALID_B])
        assert key_one != key_two


def test_the_api_key_is_not_in_the_cache_key(app):
    with app.app_context():
        instance_id = _seed()
        service = RankService(_redis())
        config = service._load_config(instance_id)
        key = service._cache_key(instance_id, config, 'ca', [VALID_A])
        assert 'tok' not in key


def test_a_successful_result_uses_the_long_ttl(app):
    with app.app_context():
        instance_id = _seed()
        client = _redis()
        service = RankService(client)
        with patch.object(service, '_fetch_from_provider',
                          return_value={VALID_A: {'rating': None, 'display': '1',
                                                  'provisional': False}}):
            service.get_ratings(instance_id, [VALID_A])
        assert client.setex.call_args[0][1] == 60


def test_an_empty_result_uses_the_short_negative_ttl(app):
    with app.app_context():
        instance_id = _seed()
        client = _redis()
        service = RankService(client)
        with patch.object(service, '_fetch_from_provider', return_value={}):
            service.get_ratings(instance_id, [VALID_A])
        assert client.setex.call_args[0][1] == 15


def test_no_redis_fetches_uncached_and_never_raises(app):
    """Degrading to 'works, just slower' beats 'silently blank'."""
    with app.app_context():
        instance_id = _seed(game_type='ffa_auto', provider_type='elo_service',
                            base_url='http://elo:5002')
        service = RankService(None)
        with patch.object(service, '_fetch_from_provider',
                          return_value={VALID_A: {'rating': 1.0, 'display': '1',
                                                  'provisional': False}}) as fetch:
            data, configured = service.get_ratings(instance_id, [VALID_A])
        fetch.assert_called_once()
        assert data[VALID_A]['display'] == '1'
        assert configured is True


def test_invalidate_deletes_every_key_for_the_instance(app):
    with app.app_context():
        client = MagicMock()
        client.scan_iter.return_value = ['rank:ratings:7:aaa:bbb',
                                         'rank:ratings:7:ccc:ddd']
        RankService(client).invalidate(7)
        client.scan_iter.assert_called_once_with(match='rank:ratings:7:*')
        assert client.delete.call_count == 2


def test_invalidate_is_a_noop_without_redis():
    RankService(None).invalidate(7)  # must not raise
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `pytest tests/test_rank_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.rank_providers.service'`

- [ ] **Step 3: Write the service**

Create `ui/rank_providers/service.py`:

```python
"""Loads a rank config, resolves the game type, caches, and calls an adapter.

Caching is per-instance, not per-viewer: several people watching the same
instance's Live Status share one entry and the fetch cost is bounded regardless
of poller count. Redis rather than an in-process cache because Gunicorn runs
multiple worker processes.
"""
import hashlib
import json
import logging

from ui import db
from ui.admin_permissions import STEAMID64_RE
from ui.models import RankProviderConfig
from ui.rank_providers.registry import build_provider

logger = logging.getLogger(__name__)

CACHE_PREFIX = 'rank:ratings'
SUCCESS_TTL = 60   # the hook polls at 30s, so poll >= TTL/2 keeps hits common
NEGATIVE_TTL = 15  # a transient outage self-heals fast without hammering
MAX_STEAM_IDS = 64

STATUS_KEY_PREFIX = 'server:status'  # ui/task_logic/server_status_poll.py:17


def validate_steam_ids(raw):
    """Applied before any cache or provider call.

    These ids end up interpolated into an outbound, credential-carrying
    provider URL (a path segment for qlstats, a query value for elo-service).

    1. split, strip
    2. drop anything that is not a steam64 — reusing the repo's existing
       STEAMID64_RE (r'^7656119\\d{10}$'). Do NOT substitute a looser
       r'^\\d{17}$'. Non-matching ids are dropped silently rather than 400'd:
       a stale roster should not fail the request.
    3. de-duplicate
    4. cap at MAX_STEAM_IDS — without it one authenticated request becomes an
       unbounded outbound fan-out at 3s per call
    """
    if isinstance(raw, str):
        parts = raw.split(',')
    else:
        parts = list(raw or [])
    seen = []
    for part in parts:
        candidate = str(part).strip()
        if not STEAMID64_RE.match(candidate):
            continue
        if candidate not in seen:
            seen.append(candidate)
        if len(seen) >= MAX_STEAM_IDS:
            break
    return seen


def _fingerprint(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]


class RankService:
    def __init__(self, redis_client):
        # May be None: ui/__init__.py:113-119 creates the shared client inside a
        # try/except that only logs a warning.
        self.redis = redis_client

    # -- config ------------------------------------------------------------

    def _load_config(self, instance_id):
        return RankProviderConfig.query.filter_by(instance_id=instance_id).first()

    @staticmethod
    def _is_usable(config):
        """A row that predates a validation change, or arrived via a restore,
        is treated as 'no provider' rather than trusted."""
        return bool(
            config
            and config.enabled
            and config.provider_type
            and config.base_url
        )

    # -- game type ---------------------------------------------------------

    def _live_gametype(self, instance):
        """The gametype from the same Redis blob live status reads.

        Server-side on purpose: it feeds the cache fingerprint and must not be
        client-controlled. Missing blob -> None -> no lookup, empty column. That
        case is moot in practice: the blob is how Live Status gets its players
        at all, so if it is gone there is nobody to rank.

        WIRE FORMAT — verified, do not re-derive. The value is a bare lowercase
        short code such as 'ca' under BOTH runtimes. Live blobs read off this
        machine's Redis:

            server:status:8:20   gametype='ca'  map='campgrounds'
            server:status:13:28  gametype='ca'  map='almostlost'

        The two serverchecker copies write it differently — minqlx writes
        `game.type_short` directly (serverchecker.py:253) and minqlxtended
        wraps it in `str()` (serverchecker.py:311) — but they agree on the
        result, because minqlxtended.Gametype is declared
        `class Gametype(enum.StrEnum)` (minqlxtended/_enums.py:344), and
        StrEnum.__str__ is str.__str__. `str(Gametype.CA)` is 'ca', never
        'Gametype.CA'. So NO normalization step is needed here, and none should
        be added: a branch that strips a 'Gametype.' prefix would be dead code
        and a fixture built on 'Gametype.CA' would assert a value the system
        never produces. The .strip().lower() below is ordinary hygiene, not
        enum handling.
        """
        if self.redis is None or instance is None:
            return None
        try:
            raw = self.redis.get(f'{STATUS_KEY_PREFIX}:{instance.host_id}:{instance.id}')
        except Exception:
            return None
        if not raw:
            return None
        try:
            status = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(status, dict):
            return None
        gametype = status.get('gametype')
        return str(gametype).strip().lower() if gametype else None

    def _resolve_game_type(self, config, provider, instance):
        """1. an explicit override wins, verbatim
        2. otherwise the adapter maps the live gametype
        3. None from either means no request at all
        """
        if config.game_type and config.game_type.strip():
            return config.game_type.strip()
        live = self._live_gametype(instance)
        if not live:
            return None
        return provider.map_game_type(live)

    # -- cache -------------------------------------------------------------

    def _cache_key(self, instance_id, config, game_type, steam_ids):
        """rank:ratings:{instance_id}:{config_fp}:{roster_fp}

        api_key is deliberately NOT hashed in — no credential material in the
        Redis keyspace. Key rotation is covered by write invalidation.
        """
        config_fp = _fingerprint(
            f'{config.provider_type}|{config.base_url}|{game_type}|'
            f'{json.dumps(config.extra_dict(), sort_keys=True)}|{config.enabled}'
        )
        roster_fp = _fingerprint(','.join(sorted(steam_ids)))
        return f'{CACHE_PREFIX}:{instance_id}:{config_fp}:{roster_fp}'

    def _read_cache(self, key):
        if self.redis is None:
            return None
        try:
            raw = self.redis.get(key)
        except Exception:
            return None
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def _write_cache(self, key, data):
        if self.redis is None:
            return
        ttl = SUCCESS_TTL if data else NEGATIVE_TTL
        try:
            self.redis.setex(key, ttl, json.dumps(data))
        except Exception:
            logger.warning('rank cache write failed for %s', key)

    def invalidate(self, instance_id):
        """Called by PUT and DELETE before returning. Without it, disabling a
        provider visibly does nothing for a full TTL."""
        if self.redis is None:
            return
        try:
            for key in self.redis.scan_iter(match=f'{CACHE_PREFIX}:{instance_id}:*'):
                self.redis.delete(key)
        except Exception:
            logger.warning('rank cache invalidation failed for instance %s', instance_id)

    # -- fetch -------------------------------------------------------------

    def _fetch_from_provider(self, provider, steam_ids, game_type, instance_id):
        return provider.fetch_ratings(steam_ids, game_type, instance_id=instance_id)

    def get_ratings(self, instance_id, raw_steam_ids):
        """Returns (data, configured).

        Never raises. Any failure is an empty data dict — errors do not reach
        the Live Status UI as a failure state, they just mean no rank that cycle.
        """
        from ui.models import QLInstance

        config = self._load_config(instance_id)
        if not self._is_usable(config):
            return {}, False

        steam_ids = validate_steam_ids(raw_steam_ids)
        if not steam_ids:
            return {}, True

        provider = build_provider(
            config.provider_type, config.base_url, config.api_key, config.extra_dict(),
        )
        if provider is None:
            return {}, False

        instance = db.session.get(QLInstance, instance_id)
        game_type = self._resolve_game_type(config, provider, instance)
        if not game_type:
            # The mode genuinely has no ratings here. Not an error.
            return {}, True

        key = self._cache_key(instance_id, config, game_type, steam_ids)
        cached = self._read_cache(key)
        if cached is not None:
            return cached, True

        try:
            data = self._fetch_from_provider(provider, steam_ids, game_type, instance_id)
        except Exception:
            # Adapters catch their own errors; this is the last line of defence.
            logger.warning('rank fetch failed for instance %s', instance_id)
            data = {}

        self._write_cache(key, data)
        return data, True
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_rank_service.py -v`
Expected: PASS (18 tests)

- [ ] **Step 5: Commit**

```bash
git add ui/rank_providers/service.py tests/test_rank_service.py
git commit -m "feat(rank): add RankService with validation, game-type resolution and caching"
```

---

## Task 8: Routes blueprint

A **new** blueprint, not an addition to `ui/routes/instance_routes.py` (1418 lines, over the 500-line hard limit). This follows `ui/routes/instance_admin_routes.py`, a 21-line file registered at `url_prefix='/instances'` (`ui/__init__.py:256-257`).

**Files:**
- Create: `ui/routes/rank_provider_routes.py`
- Modify: `ui/__init__.py` (register)
- Test: `tests/test_rank_provider_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rank_provider_routes.py`:

```python
import json
from unittest.mock import MagicMock, patch

import pytest

from ui import db
from ui.models import Host, QLInstance, RankProviderConfig
from tests.helpers import auth_headers, make_user

VALID_A = '76561198000000001'


@pytest.fixture(autouse=True)
def stub_redis(app):
    """Every /ranks test in this module needs a working Redis stub.

    create_app always installs a client (ui/__init__.py:113-119) and
    redis_lib.from_url does not connect, so the key is present but unusable and
    tests/conftest.py overrides nothing. Left alone, RankService._live_gametype
    gets None back, _resolve_game_type returns None, and get_ratings returns
    ({}, True) BEFORE any adapter call — so a test that patches the adapter's
    transport passes without ever reaching it. That is exactly how
    test_a_provider_failure_is_a_200_with_empty_data would vouch for a contract
    it never exercises. It also removes a real source of nondeterminism: on a
    developer box running run-dev.sh the unstubbed client talks to live Redis.

    Follows tests/test_server_status_routes.py:41-46, the repo's precedent.
    """
    client = MagicMock()
    # A real status blob, so the derived game type is a real short code.
    client.get.side_effect = lambda key: (
        json.dumps({'gametype': 'ca', 'map': 'campgrounds', 'players': []})
        if key.startswith('server:status:') else None
    )
    client.scan_iter.return_value = []
    app.extensions['redis'] = client
    return client


def _seed():
    host = Host(name='host-a', ip_address='10.0.0.1', ssh_user='root',
                ssh_key_path='/keys/id', ssh_port=22, provider='vultr')
    db.session.add(host)
    db.session.flush()
    instance = QLInstance(name='inst-a', port=27960, hostname='hn', host_id=host.id)
    db.session.add(instance)
    db.session.commit()
    return instance.id


def _put(client, app, instance_id, payload):
    return client.put(f'/api/instances/{instance_id}/rank-provider',
                      json=payload, headers=auth_headers(app, 'adminuser'))


# --- auth -----------------------------------------------------------------

def test_every_route_requires_authentication(client, app):
    with app.app_context():
        instance_id = _seed()
    assert client.get(f'/api/instances/{instance_id}/rank-provider').status_code == 401
    assert client.put(f'/api/instances/{instance_id}/rank-provider', json={}).status_code == 401
    assert client.delete(f'/api/instances/{instance_id}/rank-provider').status_code == 401
    assert client.get(f'/api/instances/{instance_id}/ranks').status_code == 401


# --- GET / PUT / DELETE ---------------------------------------------------

def test_get_returns_null_when_unconfigured(client, app):
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    response = client.get(f'/api/instances/{instance_id}/rank-provider',
                          headers=auth_headers(app, 'adminuser'))
    assert response.status_code == 200
    assert response.get_json()['data'] is None


def test_put_creates_then_get_returns_the_api_key_in_clear(client, app):
    """Masking would be this app's only masked secret, and a masked GET feeding
    a whole-object PUT overwrites the real token on the first unrelated edit."""
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    assert _put(client, app, instance_id, {
        'provider_type': 'slipgate', 'base_url': 'https://slipgate.gg/api/v1',
        'api_key': 'sgs_secret', 'enabled': True,
    }).status_code == 200
    body = client.get(f'/api/instances/{instance_id}/rank-provider',
                      headers=auth_headers(app, 'adminuser')).get_json()['data']
    assert body['api_key'] == 'sgs_secret'
    assert body['provider_type'] == 'slipgate'


def test_put_is_an_upsert(client, app):
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    _put(client, app, instance_id, {'provider_type': 'slipgate',
                                    'base_url': 'https://a.example'})
    _put(client, app, instance_id, {'provider_type': 'qlstats',
                                    'base_url': 'http://b.example'})
    with app.app_context():
        rows = RankProviderConfig.query.filter_by(instance_id=instance_id).all()
        assert len(rows) == 1
        assert rows[0].provider_type == 'qlstats'


def test_put_strips_trailing_slashes_from_base_url(client, app):
    """Adapters concatenate paths onto it; a trailing slash yields // and a 404
    with no useful error."""
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    _put(client, app, instance_id, {'provider_type': 'slipgate',
                                    'base_url': 'https://slipgate.gg/api/v1///'})
    with app.app_context():
        row = RankProviderConfig.query.filter_by(instance_id=instance_id).first()
        assert row.base_url == 'https://slipgate.gg/api/v1'


def test_put_rejects_an_unknown_provider_type_and_writes_nothing(client, app):
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    response = _put(client, app, instance_id, {'provider_type': 'bogus',
                                               'base_url': 'http://x.example'})
    assert response.status_code == 400
    with app.app_context():
        assert RankProviderConfig.query.count() == 0


def test_put_rejects_a_non_http_scheme(client, app):
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    response = _put(client, app, instance_id, {'provider_type': 'slipgate',
                                               'base_url': 'file:///etc/passwd'})
    assert response.status_code == 400


def test_put_requires_provider_type_and_base_url(client, app):
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    assert _put(client, app, instance_id, {'base_url': 'http://x.example'}).status_code == 400
    assert _put(client, app, instance_id, {'provider_type': 'slipgate'}).status_code == 400


def test_put_accepts_a_blank_game_type(client, app):
    """Blank means 'derive it', which is the normal case."""
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    assert _put(client, app, instance_id, {
        'provider_type': 'slipgate', 'base_url': 'https://slipgate.gg/api/v1',
        'game_type': '',
    }).status_code == 200


def test_put_rejects_an_over_long_base_url(client, app):
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    assert _put(client, app, instance_id, {
        'provider_type': 'slipgate', 'base_url': 'http://' + 'a' * 300,
    }).status_code == 400


def test_put_persists_extra(client, app):
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    _put(client, app, instance_id, {
        'provider_type': 'qlstats', 'base_url': 'http://qlstats.net',
        'extra': {'rating_system': 'elo_b'},
    })
    with app.app_context():
        row = RankProviderConfig.query.filter_by(instance_id=instance_id).first()
        assert row.extra_dict() == {'rating_system': 'elo_b'}


def test_put_rejects_a_non_string_extra_value(client, app):
    """extra is the one operator-controlled value that reaches an outbound URL.
    Rejecting non-strings also closes json.dumps of arbitrary nested data into
    an unbounded Text column."""
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    assert _put(client, app, instance_id, {
        'provider_type': 'qlstats', 'base_url': 'http://qlstats.net',
        'extra': {'rating_system': {'nested': 'object'}},
    }).status_code == 400


def test_put_rejects_an_oversized_extra_blob(client, app):
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    assert _put(client, app, instance_id, {
        'provider_type': 'qlstats', 'base_url': 'http://qlstats.net',
        'extra': {'padding': 'x' * 4096},
    }).status_code == 400


def test_put_rejects_an_unknown_qlstats_rating_system(client, app):
    """base_url gets five rules and steam_ids gets a regex plus a cap for the
    same reason: the value becomes part of an outbound request. The UI only
    offers elo and elo_b, so this turns a typo's silent 404 into a clear error
    at write time."""
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    assert _put(client, app, instance_id, {
        'provider_type': 'qlstats', 'base_url': 'http://qlstats.net',
        'extra': {'rating_system': 'elo_c'},
    }).status_code == 400
    with app.app_context():
        assert RankProviderConfig.query.count() == 0


def test_put_allows_a_rating_system_key_for_a_non_qlstats_provider(client, app):
    """The rating_system rule is scoped to qlstats. extra does not get a
    per-provider schema framework for a column with one key in it."""
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    assert _put(client, app, instance_id, {
        'provider_type': 'slipgate', 'base_url': 'https://slipgate.gg/api/v1',
        'extra': {'rating_system': 'anything'},
    }).status_code == 200


def test_delete_removes_the_config(client, app):
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    _put(client, app, instance_id, {'provider_type': 'slipgate',
                                    'base_url': 'https://slipgate.gg/api/v1'})
    assert client.delete(f'/api/instances/{instance_id}/rank-provider',
                         headers=auth_headers(app, 'adminuser')).status_code == 200
    with app.app_context():
        assert RankProviderConfig.query.count() == 0


def test_put_and_delete_invalidate_the_cache(client, app):
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    with patch('ui.routes.rank_provider_routes.RankService.invalidate') as invalidate:
        _put(client, app, instance_id, {'provider_type': 'slipgate',
                                        'base_url': 'https://slipgate.gg/api/v1'})
        client.delete(f'/api/instances/{instance_id}/rank-provider',
                      headers=auth_headers(app, 'adminuser'))
    assert invalidate.call_count == 2


def test_unknown_instance_is_404(client, app):
    make_user(app, 'adminuser', 'password123')
    headers = auth_headers(app, 'adminuser')
    assert client.get('/api/instances/424242/rank-provider', headers=headers).status_code == 404


# --- /ranks ---------------------------------------------------------------

def test_ranks_reports_unconfigured(client, app):
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    response = client.get(f'/api/instances/{instance_id}/ranks?steam_ids={VALID_A}',
                          headers=auth_headers(app, 'adminuser'))
    assert response.status_code == 200
    body = response.get_json()
    assert body['data'] == {}
    assert body['configured'] is False


def test_ranks_returns_data_and_configured(client, app):
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    _put(client, app, instance_id, {'provider_type': 'slipgate',
                                    'base_url': 'https://slipgate.gg/api/v1'})
    payload = {VALID_A: {'rating': None, 'display': '1650', 'provisional': False}}
    with patch('ui.routes.rank_provider_routes.RankService.get_ratings',
               return_value=(payload, True)):
        response = client.get(f'/api/instances/{instance_id}/ranks?steam_ids={VALID_A}',
                              headers=auth_headers(app, 'adminuser'))
    body = response.get_json()
    assert body['configured'] is True
    assert body['data'][VALID_A]['display'] == '1650'


def test_a_provider_failure_is_a_200_with_empty_data(client, app):
    """Errors never propagate to the Live Status UI as a failure state.

    The stub_redis fixture is what makes this test mean anything: without a
    status blob the game type resolves to None and the request returns before
    the adapter is ever built. Assert the transport was actually reached, so
    this cannot silently go back to passing for the wrong reason.
    """
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    _put(client, app, instance_id, {'provider_type': 'slipgate',
                                    'base_url': 'https://slipgate.gg/api/v1'})
    with patch('ui.rank_providers.slipgate.requests.post',
               side_effect=Exception('down')) as post:
        response = client.get(f'/api/instances/{instance_id}/ranks?steam_ids={VALID_A}',
                              headers=auth_headers(app, 'adminuser'))
    post.assert_called_once()
    assert response.status_code == 200
    assert response.get_json()['data'] == {}


def test_ranks_works_without_redis(client, app):
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    _put(client, app, instance_id, {
        'provider_type': 'elo_service', 'base_url': 'http://elo:5002',
        'game_type': 'ffa_auto',
    })
    app.extensions.pop('redis', None)
    with patch('ui.rank_providers.elo_service.requests.get') as get:
        get.return_value.status_code = 200
        get.return_value.json.return_value = {VALID_A: {'sort_score': 1800, 'mu': 25}}
        response = client.get(f'/api/instances/{instance_id}/ranks?steam_ids={VALID_A}',
                              headers=auth_headers(app, 'adminuser'))
    assert response.status_code == 200
    assert response.get_json()['data'][VALID_A]['display'] == '1800'


def test_ranks_drops_invalid_ids_before_the_adapter_sees_them(client, app):
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    _put(client, app, instance_id, {
        'provider_type': 'elo_service', 'base_url': 'http://elo:5002',
        'game_type': 'ffa_auto',
    })
    with patch('ui.rank_providers.elo_service.requests.get') as get:
        get.return_value.status_code = 200
        get.return_value.json.return_value = {}
        client.get(
            f'/api/instances/{instance_id}/ranks?steam_ids=../../admin,12345,{VALID_A}',
            headers=auth_headers(app, 'adminuser'))
    assert get.call_args[1]['params']['ids'] == VALID_A


# --- secret boundary ------------------------------------------------------

def test_the_api_key_never_appears_in_the_instance_endpoints(client, app):
    """/api/v1/instances strips a DENYLIST, so anything added to
    QLInstance.to_dict() is exposed to every external API key holder."""
    make_user(app, 'adminuser', 'password123')
    with app.app_context():
        instance_id = _seed()
    _put(client, app, instance_id, {
        'provider_type': 'slipgate', 'base_url': 'https://slipgate.gg/api/v1',
        'api_key': 'sgs_secret',
    })
    headers = auth_headers(app, 'adminuser')
    listing = client.get('/api/instances/', headers=headers)
    assert 'sgs_secret' not in listing.get_data(as_text=True)
    ranks = client.get(f'/api/instances/{instance_id}/ranks?steam_ids={VALID_A}',
                       headers=headers)
    assert 'sgs_secret' not in ranks.get_data(as_text=True)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `pytest tests/test_rank_provider_routes.py -v`
Expected: FAIL — 404 on every route (the blueprint does not exist).

- [ ] **Step 3: Write the blueprint**

Create `ui/routes/rank_provider_routes.py`:

```python
"""Per-instance rank provider configuration, and the read-only ratings feed.

A separate blueprint rather than an addition to instance_routes.py (1418 lines,
over the 500-line hard limit), following instance_admin_routes.py.
"""
import json

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

from ui import db
from ui.models import QLInstance, RankProviderConfig
from ui.rank_providers.registry import PROVIDER_TYPES
from ui.rank_providers.service import RankService

rank_provider_api_bp = Blueprint('rank_provider_api_routes', __name__)

MAX_LENGTHS = {'base_url': 255, 'api_key': 255, 'game_type': 16, 'provider_type': 32}

# `extra` lands in an unbounded Text column, so bound the SERIALIZED blob.
MAX_EXTRA_SERIALIZED = 2048

# qlstats interpolates extra['rating_system'] straight into a request path.
# The UI only ever offers these two.
QLSTATS_RATING_SYSTEMS = {'elo', 'elo_b'}


def _error(message, status=400):
    return jsonify({"error": {"message": message}}), status


def _service():
    return RankService(current_app.extensions.get('redis'))


def _require_instance(instance_id):
    return db.session.get(QLInstance, instance_id)


def _validate(payload):
    """Repo validation order: type -> normalize -> empty -> length -> pattern.

    Returns (cleaned, error_message).
    """
    if not isinstance(payload, dict):
        return None, "Request body must be a JSON object."

    # 1. Type check
    for field in ('provider_type', 'base_url', 'api_key', 'game_type'):
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            return None, f"'{field}' must be a string."
    if 'enabled' in payload and not isinstance(payload['enabled'], bool):
        return None, "'enabled' must be a boolean."
    extra = payload.get('extra', {})
    if extra is None:
        extra = {}
    if not isinstance(extra, dict):
        return None, "'extra' must be an object."
    # Every value a string. Without this, json.dumps writes arbitrary nested
    # data into an unbounded Text column, and a non-string rating_system
    # reaches an outbound URL path segment as whatever repr it happens to have.
    for key, value in extra.items():
        if not isinstance(value, str):
            return None, f"'extra.{key}' must be a string."

    # 2. Normalize
    cleaned = {
        'provider_type': (payload.get('provider_type') or '').strip(),
        # Trailing slashes off: adapters concatenate paths onto this, so a
        # trailing slash yields a double slash and a 404 with no useful error.
        'base_url': (payload.get('base_url') or '').strip().rstrip('/'),
        'api_key': (payload.get('api_key') or '').strip() or None,
        'game_type': (payload.get('game_type') or '').strip() or None,
        'extra': extra,
        'enabled': payload.get('enabled', True),
    }

    # 3. Empty check — game_type is deliberately optional: blank means
    #    "derive it from the live gametype", the normal case.
    if not cleaned['provider_type']:
        return None, "'provider_type' is required."
    if not cleaned['base_url']:
        return None, "'base_url' is required."

    # 4. Length check
    for field, limit in MAX_LENGTHS.items():
        value = cleaned.get(field)
        if value and len(value) > limit:
            return None, f"'{field}' must be {limit} characters or fewer."
    # extra is bounded by its serialized length — the column is Text, and
    # nothing else stops an operator posting arbitrary data into it.
    if len(json.dumps(cleaned['extra'])) > MAX_EXTRA_SERIALIZED:
        return None, (f"'extra' must serialize to {MAX_EXTRA_SERIALIZED} "
                      "characters or fewer.")

    # 5. Pattern check
    if cleaned['provider_type'] not in PROVIDER_TYPES:
        return None, (f"Unknown provider type '{cleaned['provider_type']}'. "
                      f"Expected one of: {', '.join(sorted(PROVIDER_TYPES))}.")
    if not cleaned['base_url'].startswith(('http://', 'https://')):
        return None, "'base_url' must start with http:// or https://."
    # The one operator-controlled value that reaches an outbound URL path
    # segment. Scoped to qlstats on purpose: this is three rules, not a
    # per-provider schema framework for a column with one key in it.
    if cleaned['provider_type'] == 'qlstats':
        system = cleaned['extra'].get('rating_system')
        if system is not None and system not in QLSTATS_RATING_SYSTEMS:
            return None, ("'extra.rating_system' must be one of: "
                          f"{', '.join(sorted(QLSTATS_RATING_SYSTEMS))}.")

    # 6. Uniqueness — none needed, instance_id is unique.
    return cleaned, None


@rank_provider_api_bp.route('/<int:instance_id>/rank-provider', methods=['GET'])
@jwt_required()
def get_rank_provider(instance_id):
    if _require_instance(instance_id) is None:
        return _error(f"Instance {instance_id} not found.", 404)
    config = RankProviderConfig.query.filter_by(instance_id=instance_id).first()
    # api_key is returned in clear text, not masked. This repo masks no secrets
    # anywhere (QLInstance.to_dict() returns both ZMQ passwords in the clear),
    # and a masked GET feeding the whole-object PUT below would overwrite the
    # real token the first time the operator toggles `enabled`.
    return jsonify({"data": config.to_dict() if config else None}), 200


@rank_provider_api_bp.route('/<int:instance_id>/rank-provider', methods=['PUT'])
@jwt_required()
def put_rank_provider(instance_id):
    if _require_instance(instance_id) is None:
        return _error(f"Instance {instance_id} not found.", 404)

    cleaned, error = _validate(request.get_json(silent=True))
    if error:
        return _error(error)

    config = RankProviderConfig.query.filter_by(instance_id=instance_id).first()
    if config is None:
        config = RankProviderConfig(instance_id=instance_id)
        db.session.add(config)

    config.provider_type = cleaned['provider_type']
    config.base_url = cleaned['base_url']
    config.api_key = cleaned['api_key']
    config.game_type = cleaned['game_type']
    config.extra = json.dumps(cleaned['extra'])
    config.enabled = cleaned['enabled']
    db.session.commit()

    # Before returning: without this, disabling a provider visibly does
    # nothing for a full TTL.
    _service().invalidate(instance_id)
    return jsonify({"data": config.to_dict(), "message": "Rank provider saved."}), 200


@rank_provider_api_bp.route('/<int:instance_id>/rank-provider', methods=['DELETE'])
@jwt_required()
def delete_rank_provider(instance_id):
    if _require_instance(instance_id) is None:
        return _error(f"Instance {instance_id} not found.", 404)
    RankProviderConfig.query.filter_by(instance_id=instance_id).delete()
    db.session.commit()
    _service().invalidate(instance_id)
    return jsonify({"data": None, "message": "Rank provider removed."}), 200


@rank_provider_api_bp.route('/<int:instance_id>/ranks', methods=['GET'])
@jwt_required()
def get_ranks(instance_id):
    """Always 200 ONCE THE INSTANCE EXISTS. Errors never propagate to Live
    Status as a failure state — they just mean no rank shown that cycle.

    An unknown instance is a 404, like the three sibling routes above. It is a
    different kind of answer from "no ratings this cycle", and making /ranks
    the one route in this blueprint that invents a 200 for a missing row would
    be the larger inconsistency. The client side of that contract is pinned
    too: useRankData treats a 404 as configured:false and stops polling, so an
    instance deleted while its drawer is open does not keep firing a request
    every 30s.
    """
    if _require_instance(instance_id) is None:
        return _error(f"Instance {instance_id} not found.", 404)
    data, configured = _service().get_ratings(
        instance_id, request.args.get('steam_ids', ''))
    return jsonify({"data": data, "configured": configured}), 200
```

- [ ] **Step 4: Register the blueprint**

In `ui/__init__.py`, directly after the `instance_admin_api_bp` registration at `:256-257`:

```python
    from ui.routes.rank_provider_routes import rank_provider_api_bp
    api_bp.register_blueprint(rank_provider_api_bp, url_prefix='/instances')
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_rank_provider_routes.py -v`
Expected: PASS (24 tests)

- [ ] **Step 6: Commit**

```bash
git add ui/routes/rank_provider_routes.py ui/__init__.py tests/test_rank_provider_routes.py
git commit -m "feat(rank): add rank provider routes blueprint"
```

---

## Task 9: Frontend API client

**Files:**
- Modify: `frontend-react/src/services/api.js`

- [ ] **Step 1: Add the four functions**

Append near `getInstanceAdmins` (`api.js:789`), matching its exact shape:

```javascript
// Rank Provider APIs
export const getRankProvider = async (instanceId) => {
  try {
    const response = await apiClient.get(`/instances/${instanceId}/rank-provider`);
    return response.data.data;
  } catch (error) {
    console.error('Failed to fetch rank provider:', error.response ? error.response.data : error.message);
    throw error.response ? error.response.data : new Error('Failed to fetch rank provider');
  }
};

export const saveRankProvider = async (instanceId, config) => {
  try {
    const response = await apiClient.put(`/instances/${instanceId}/rank-provider`, config);
    return response.data.data;
  } catch (error) {
    console.error('Failed to save rank provider:', error.response ? error.response.data : error.message);
    throw error.response ? error.response.data : new Error('Failed to save rank provider');
  }
};

export const deleteRankProvider = async (instanceId) => {
  try {
    const response = await apiClient.delete(`/instances/${instanceId}/rank-provider`);
    return response.data;
  } catch (error) {
    console.error('Failed to delete rank provider:', error.response ? error.response.data : error.message);
    throw error.response ? error.response.data : new Error('Failed to delete rank provider');
  }
};

export const getInstanceRanks = async (instanceId, steamIds) => {
  const response = await apiClient.get(`/instances/${instanceId}/ranks`, {
    params: { steam_ids: steamIds },
  });
  return { ranks: response.data.data || {}, configured: !!response.data.configured };
};
```

`getInstanceRanks` deliberately does **not** catch. The hook owns failure handling for the polling path, and a `console.error` on every failed 30s poll would flood the console during a provider outage.

- [ ] **Step 2: Lint**

Run: `cd frontend-react && pnpm lint`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend-react/src/services/api.js
git commit -m "feat(rank): add rank provider API client functions"
```

---

## Task 10: `useRankData` hook

Six things here are required, not optimizations. Each has a named failure mode: the `enabled` gate (double mount), the stable string dependency (throttle evaporates), `configured` starting `false` (column flashes on every unconfigured instance), the reset on `instanceId` (instance A's ratings render under instance B), the stop latch keyed on the instance alone (one request per roster change), and the `404` branch (polling a deleted instance forever).

**Files:**
- Create: `frontend-react/src/hooks/useRankData.js`
- Test: `frontend-react/src/hooks/__tests__/useRankData.test.js`

- [ ] **Step 1: Write the failing tests**

Create `frontend-react/src/hooks/__tests__/useRankData.test.js`:

```javascript
import { renderHook, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useRankData } from '../useRankData';
import * as api from '../../services/api';

vi.mock('../../services/api');

describe('useRankData', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    api.getInstanceRanks = vi.fn().mockResolvedValue({ ranks: {}, configured: true });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it('does not fetch when disabled', () => {
    // LiveServerStatusModal is mounted UNCONDITIONALLY in two places
    // (ServersPage.jsx:401, InstanceDetailsModal.jsx:528) with visibility
    // controlled only by isOpen. Without this guard the hook runs while the
    // drawer is closed, and twice when the details modal sits behind it.
    renderHook(() => useRankData(1, ['76561198000000001'], { enabled: false }));
    expect(api.getInstanceRanks).not.toHaveBeenCalled();
  });

  it('fetches once when enabled', async () => {
    renderHook(() => useRankData(1, ['76561198000000001'], { enabled: true }));
    await waitFor(() => expect(api.getInstanceRanks).toHaveBeenCalledTimes(1));
    expect(api.getInstanceRanks).toHaveBeenCalledWith(1, '76561198000000001');
  });

  it('does not refetch when the array identity changes but contents do not', async () => {
    // sortedPlayers is a useMemo over serverStatus.players, which
    // useServerStatus replaces every 15s. An array in the dependency list
    // re-fires the effect on every parent render and the 30s throttle — which
    // the entire caching design rests on — quietly evaporates.
    const { rerender } = renderHook(
      ({ ids }) => useRankData(1, ids, { enabled: true }),
      { initialProps: { ids: ['76561198000000001', '76561198000000002'] } },
    );
    await waitFor(() => expect(api.getInstanceRanks).toHaveBeenCalledTimes(1));
    rerender({ ids: ['76561198000000002', '76561198000000001'] });
    await act(async () => {});
    expect(api.getInstanceRanks).toHaveBeenCalledTimes(1);
  });

  it('refetches when a player actually joins', async () => {
    const { rerender } = renderHook(
      ({ ids }) => useRankData(1, ids, { enabled: true }),
      { initialProps: { ids: ['76561198000000001'] } },
    );
    await waitFor(() => expect(api.getInstanceRanks).toHaveBeenCalledTimes(1));
    rerender({ ids: ['76561198000000001', '76561198000000003'] });
    await waitFor(() => expect(api.getInstanceRanks).toHaveBeenCalledTimes(2));
  });

  it('polls every 30 seconds', async () => {
    renderHook(() => useRankData(1, ['76561198000000001'], { enabled: true }));
    await waitFor(() => expect(api.getInstanceRanks).toHaveBeenCalledTimes(1));
    await act(async () => { vi.advanceTimersByTime(30000); });
    await waitFor(() => expect(api.getInstanceRanks).toHaveBeenCalledTimes(2));
  });

  it('stops polling once the server reports configured false', async () => {
    api.getInstanceRanks = vi.fn().mockResolvedValue({ ranks: {}, configured: false });
    const { result } = renderHook(
      () => useRankData(1, ['76561198000000001'], { enabled: true }));
    await waitFor(() => expect(result.current.configured).toBe(false));
    await act(async () => { vi.advanceTimersByTime(90000); });
    // One request for the life of the drawer, not one every 30s.
    expect(api.getInstanceRanks).toHaveBeenCalledTimes(1);
  });

  it('does not re-arm the stop latch when the roster changes', async () => {
    // configured:false is a property of the INSTANCE, not of who happens to be
    // connected. Keying the latch reset on steamIdsKey turns the stated "one
    // request" into one request per join or leave, which on a populated server
    // is frequent. Effects run in declaration order, so the reset would land
    // before the fetch effect re-subscribes and the new request would go out.
    api.getInstanceRanks = vi.fn().mockResolvedValue({ ranks: {}, configured: false });
    const { result, rerender } = renderHook(
      ({ ids }) => useRankData(1, ids, { enabled: true }),
      { initialProps: { ids: ['76561198000000001'] } },
    );
    await waitFor(() => expect(result.current.configured).toBe(false));
    rerender({ ids: ['76561198000000001', '76561198000000003'] });
    await act(async () => { vi.advanceTimersByTime(30000); });
    expect(api.getInstanceRanks).toHaveBeenCalledTimes(1);
  });

  it('reports configured false on the first render, before any response', () => {
    // The spec's rule is "hidden entirely, not shown full of dashes". The modal
    // renders before the first /ranks response resolves, so an initial `true`
    // shows a header and a column of dashes on every instance that has no
    // provider — which is every instance on day one — then removes them.
    const { result } = renderHook(
      () => useRankData(1, ['76561198000000001'], { enabled: true }));
    expect(result.current.configured).toBe(false);
  });

  it('clears ranks and configured when the instance changes', async () => {
    // One LiveServerStatusModal is mounted per page (ServersPage.jsx:401) and
    // the instance prop is swapped. Without a reset, instance A's column and
    // numbers survive into instance B's first render, and a player on both
    // servers carries A's rating into B's table — a WRONG number rather than a
    // missing one, and the one failure here an operator cannot spot by looking.
    api.getInstanceRanks = vi.fn().mockResolvedValue({
      ranks: { 76561198000000001: { display: '1650' } }, configured: true,
    });
    const { result, rerender } = renderHook(
      ({ id }) => useRankData(id, ['76561198000000001'], { enabled: true }),
      { initialProps: { id: 1 } },
    );
    await waitFor(() => expect(result.current.configured).toBe(true));
    api.getInstanceRanks = vi.fn(() => new Promise(() => {}));  // never resolves
    rerender({ id: 2 });
    expect(result.current.ranks).toEqual({});
    expect(result.current.configured).toBe(false);
  });

  it('treats a 404 as unconfigured and stops polling', async () => {
    // get_ranks 404s on an instance deleted while its drawer is open. Without
    // this the catch would keep polling a dead instance every 30s for the life
    // of the drawer.
    const notFound = Object.assign(new Error('not found'), {
      response: { status: 404 },
    });
    api.getInstanceRanks = vi.fn().mockRejectedValue(notFound);
    const { result } = renderHook(
      () => useRankData(1, ['76561198000000001'], { enabled: true }));
    await waitFor(() => expect(api.getInstanceRanks).toHaveBeenCalledTimes(1));
    await act(async () => { vi.advanceTimersByTime(90000); });
    expect(api.getInstanceRanks).toHaveBeenCalledTimes(1);
    expect(result.current.configured).toBe(false);
  });

  it('keeps the last good ranks and configured when a poll fails', async () => {
    api.getInstanceRanks = vi.fn()
      .mockResolvedValueOnce({ ranks: { a: { display: '1650' } }, configured: true })
      .mockRejectedValueOnce(new Error('down'));
    const { result } = renderHook(
      () => useRankData(1, ['76561198000000001'], { enabled: true }));
    await waitFor(() => expect(result.current.ranks.a.display).toBe('1650'));
    await act(async () => { vi.advanceTimersByTime(30000); });
    expect(result.current.ranks.a.display).toBe('1650');
    // The catch leaves configured ALONE. Forcing it true here would render a
    // provider column on an instance that may have none.
    expect(result.current.configured).toBe(true);
  });

  it('does not fetch with an empty roster', () => {
    renderHook(() => useRankData(1, [], { enabled: true }));
    expect(api.getInstanceRanks).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `cd frontend-react && pnpm vitest run src/hooks/__tests__/useRankData.test.js`
Expected: FAIL — cannot resolve `../useRankData`

- [ ] **Step 3: Write the hook**

Create `frontend-react/src/hooks/useRankData.js`:

```javascript
import { useEffect, useMemo, useRef, useState } from 'react';
import { getInstanceRanks } from '../services/api';

const POLL_INTERVAL_MS = 30000;

/**
 * Ratings for the currently connected players, on its own cadence.
 *
 * Independent of the 15s live-status poll on purpose: an outbound call to a
 * third-party service must never ride on every Live Status refresh. 30s against
 * the backend's 60s cache TTL keeps poll >= TTL/2, so a cache hit is the common
 * case.
 *
 * @param {number|null} instanceId
 * @param {string[]} steamIds - connected players' steam ids
 * @param {{enabled: boolean}} options - enabled is REQUIRED, not an
 *   optimization: LiveServerStatusModal is mounted unconditionally in two
 *   places and visibility is controlled only by its isOpen prop.
 */
export function useRankData(instanceId, steamIds, { enabled = true } = {}) {
  const [ranks, setRanks] = useState({});
  // Starts FALSE. The modal renders before the first /ranks response resolves,
  // so an initial `true` shows the header and a column of dashes on every
  // instance that has no provider — which is every instance on day one — and
  // then removes them a moment later. That is exactly the flash the spec's
  // "hidden entirely, not shown full of dashes" rule exists to prevent. The
  // cost is one render without a column before a configured instance's first
  // response, which is the correct direction to be wrong in.
  const [configured, setConfigured] = useState(false);
  const stopPollingRef = useRef(false);

  // A stable primitive, not the array. sortedPlayers is a useMemo over
  // serverStatus.players, which useServerStatus replaces on a 15s interval — an
  // array here re-fires the effect on every parent render and the throttle
  // this whole design rests on quietly evaporates.
  const steamIdsKey = useMemo(
    () => [...new Set((steamIds || []).map(String))].sort().join(','),
    [steamIds],
  );

  // Keyed on instanceId ALONE — never on steamIdsKey. `configured: false` is a
  // property of the instance, not of who happens to be connected, so clearing
  // the latch on a join or leave turns "one request for the life of the drawer"
  // into one request per roster change. The cost is that a provider configured
  // while the drawer is open is not picked up until it is reopened, which is
  // the right behaviour for a config change.
  //
  // The same effect resets the DATA. Without it, instance A's column and
  // numbers survive into instance B's first render, and a player on both
  // servers carries A's rating into B's table.
  useEffect(() => {
    stopPollingRef.current = false;
    setRanks({});
    setConfigured(false);
  }, [instanceId]);

  useEffect(() => {
    if (!enabled || !instanceId || !steamIdsKey) {
      return undefined;
    }

    let cancelled = false;

    const fetchOnce = async () => {
      if (stopPollingRef.current) return;
      try {
        const result = await getInstanceRanks(instanceId, steamIdsKey);
        if (cancelled) return;
        setRanks(result.ranks);
        setConfigured(result.configured);
        if (!result.configured) {
          // An instance that will never have a provider costs one request,
          // not one every 30s for the life of the drawer.
          stopPollingRef.current = true;
        }
      } catch (error) {
        if (cancelled) return;
        if (error?.response?.status === 404) {
          // The instance was deleted while its drawer is open. Stop, rather
          // than polling a dead instance every 30s for the life of the drawer.
          setConfigured(false);
          stopPollingRef.current = true;
          return;
        }
        // Keep the last good data: a failed poll means no fresh ranks, not a
        // reason to blank a table the operator is reading. `configured` is
        // deliberately left UNTOUCHED — forcing it true here would render a
        // provider column on an instance that may have none.
      }
    };

    fetchOnce();
    const timer = setInterval(fetchOnce, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [instanceId, steamIdsKey, enabled]);

  return { ranks, configured };
}
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend-react && pnpm vitest run src/hooks/__tests__/useRankData.test.js`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend-react/src/hooks/useRankData.js frontend-react/src/hooks/__tests__/useRankData.test.js
git commit -m "feat(rank): add useRankData polling hook"
```

---

## Task 11: `RankProviderTab` and the modal tab

**Files:**
- Create: `frontend-react/src/components/instances/RankProviderTab.jsx`
- Create: `frontend-react/src/components/instances/__tests__/RankProviderTab.test.jsx`
- Modify: `frontend-react/src/components/instances/EditInstanceConfigModal.jsx` (tab button + panel only)

- [ ] **Step 1: Write the tab component**

Create `frontend-react/src/components/instances/RankProviderTab.jsx`:

```jsx
import React, { useCallback, useEffect, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { getRankProvider, saveRankProvider, deleteRankProvider } from '../../services/api';

const PROVIDERS = [
  { value: '', label: 'None' },
  { value: 'qlstats', label: 'qlstats' },
  { value: 'slipgate', label: 'Slipgate' },
  { value: 'elo_service', label: 'Thunderdome elo-service' },
];

// qlstats has no auth; every other provider needs a credential.
const NEEDS_API_KEY = { qlstats: false, slipgate: true, elo_service: true };

const EMPTY = {
  provider_type: '', base_url: '', api_key: '', game_type: '',
  extra: {}, enabled: true,
};

export default function RankProviderTab({ instanceId }) {
  const [form, setForm] = useState(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getRankProvider(instanceId)
      .then((config) => {
        if (cancelled) return;
        setForm(config ? { ...EMPTY, ...config, extra: config.extra || {} } : EMPTY);
      })
      .catch(() => { if (!cancelled) setError('Could not load the rank provider settings.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [instanceId]);

  const update = useCallback((field, value) => {
    setForm((previous) => ({ ...previous, [field]: value }));
    setStatus(null);
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      if (!form.provider_type) {
        await deleteRankProvider(instanceId);
        setForm(EMPTY);
        setStatus('Rank provider removed.');
      } else {
        const saved = await saveRankProvider(instanceId, form);
        setForm({ ...EMPTY, ...saved, extra: saved.extra || {} });
        setStatus('Rank provider saved.');
      }
    } catch (err) {
      setError(err?.error?.message || 'Could not save the rank provider settings.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <p className="text-sm text-[var(--text-secondary)] italic p-4">Loading…</p>;
  }

  const needsKey = NEEDS_API_KEY[form.provider_type];

  return (
    <div className="p-4 space-y-4 max-w-xl">
      <p className="text-sm text-[var(--text-secondary)]">
        Show each connected player&apos;s rating in this instance&apos;s Live Status table.
      </p>

      <label className="block">
        <span className="block text-xs uppercase tracking-wide text-[var(--text-secondary)] mb-1">
          Provider
        </span>
        <select
          className="w-full bg-[var(--surface-base)] border border-[var(--surface-border)] rounded px-3 py-2 text-sm"
          value={form.provider_type}
          onChange={(e) => update('provider_type', e.target.value)}
        >
          {PROVIDERS.map((p) => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
      </label>

      {form.provider_type && (
        <>
          <label className="block">
            <span className="block text-xs uppercase tracking-wide text-[var(--text-secondary)] mb-1">
              Base URL
            </span>
            <input
              type="text"
              className="w-full bg-[var(--surface-base)] border border-[var(--surface-border)] rounded px-3 py-2 text-sm font-mono"
              value={form.base_url || ''}
              placeholder={form.provider_type === 'slipgate'
                ? 'https://slipgate.gg/api/v1'
                : 'http://host:5002'}
              onChange={(e) => update('base_url', e.target.value)}
            />
          </label>

          {needsKey && (
            <label className="block">
              <span className="block text-xs uppercase tracking-wide text-[var(--text-secondary)] mb-1">
                {form.provider_type === 'slipgate' ? 'Upload token' : 'API key'}
              </span>
              <input
                type="text"
                className="w-full bg-[var(--surface-base)] border border-[var(--surface-border)] rounded px-3 py-2 text-sm font-mono"
                value={form.api_key || ''}
                onChange={(e) => update('api_key', e.target.value)}
              />
            </label>
          )}

          {form.provider_type === 'qlstats' && (
            <label className="block">
              <span className="block text-xs uppercase tracking-wide text-[var(--text-secondary)] mb-1">
                Rating system
              </span>
              <select
                className="w-full bg-[var(--surface-base)] border border-[var(--surface-border)] rounded px-3 py-2 text-sm"
                value={form.extra?.rating_system || 'elo'}
                onChange={(e) => update('extra', { ...form.extra, rating_system: e.target.value })}
              >
                <option value="elo">elo</option>
                <option value="elo_b">elo_b</option>
              </select>
            </label>
          )}

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={!!form.enabled}
              onChange={(e) => update('enabled', e.target.checked)}
            />
            Enabled
          </label>

          <div>
            <button
              type="button"
              className="flex items-center gap-1 text-xs uppercase tracking-wide text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              onClick={() => setAdvancedOpen((open) => !open)}
            >
              {advancedOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              Advanced
            </button>
            {advancedOpen && (
              <label className="block mt-2">
                <span className="block text-xs uppercase tracking-wide text-[var(--text-secondary)] mb-1">
                  Game type override
                </span>
                <input
                  type="text"
                  className="w-full bg-[var(--surface-base)] border border-[var(--surface-border)] rounded px-3 py-2 text-sm font-mono"
                  value={form.game_type || ''}
                  placeholder="ffa_auto"
                  onChange={(e) => update('game_type', e.target.value)}
                />
                <span className="block mt-1 text-xs text-[var(--text-secondary)]">
                  Leave blank to follow the server&apos;s current game type. Set this
                  only for providers with their own pool names, such as
                  elo-service&apos;s <code>ffa_auto</code>.
                </span>
              </label>
            )}
          </div>
        </>
      )}

      {error && <p className="text-sm text-red-500">{error}</p>}
      {status && <p className="text-sm text-[var(--accent-primary)]">{status}</p>}

      <button
        type="button"
        onClick={handleSave}
        disabled={saving}
        className="px-4 py-2 rounded bg-[var(--accent-primary)] text-black text-sm font-semibold disabled:opacity-50"
      >
        {saving ? 'Saving…' : 'Save'}
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Add the tab button**

In `EditInstanceConfigModal.jsx`, add `Trophy` to the existing `lucide-react` import, then add one entry to the tab array at `:1195-1199`, after the `admins` entry:

```javascript
                            { key: 'rank', icon: Trophy, label: 'Rank Provider' },
```

- [ ] **Step 3: Update the tab-type comment**

At `:145`, change the comment to match:

```javascript
  const [activeMainTab, setActiveMainTab] = useState(initialTab); // 'config' | 'scripts' | 'factories' | 'hooks' | 'admins' | 'rank'
```

- [ ] **Step 4: Add the panel**

Import the tab at the top of the modal:

```javascript
import RankProviderTab from './RankProviderTab';
```

Then, next to the existing `admins` panel render, add:

```jsx
                        {activeMainTab === 'rank' && (
                          <RankProviderTab instanceId={instanceId} />
                        )}
```

**The prop is `instanceId`, not `instance?.id`.** `EditInstanceConfigModal` destructures `{ isOpen, onClose, instanceId, instanceName: initialInstanceName, onConfigSaved, initialTab }` at `:76-83` — there is no `instance` in scope, so `instance?.id` evaluates to `undefined` and sends every request to `/api/instances/undefined/rank-provider`. `OwnerAdminEditor` at `:1291` already passes `instanceId={instanceId}`; follow it.

**Keep the `&&` conditional. Do not copy the `admins` panel's structure.** That panel is kept mounted and hidden by a class (`:1286-1297`), with a comment saying why: `OwnerAdminEditor` fills the operators cache the access.txt autocomplete reads. `RankProviderTab` warms nothing — it fires a `GET` on mount and nothing else depends on it — so keeping it mounted would issue a request on every modal open regardless of which tab is showing. Conditional rendering is the right choice here precisely because the two panels differ.

The modal gains a tab button and a panel and nothing else; it is already 1413 lines against a 500-line hard limit.

- [ ] **Step 5: Test the tab**

This is the only new component with branching logic, and the save-vs-delete fork in particular issues a `DELETE` on the path an operator reaches by picking "None" — easy to break silently later. Three cases, not five: keep this scoped.

Create `frontend-react/src/components/instances/__tests__/RankProviderTab.test.jsx`, following `HooksTab.test.jsx`, the repo's precedent for testing a tab body in isolation:

```javascript
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import RankProviderTab from '../RankProviderTab';
import * as api from '../../../services/api';

vi.mock('../../../services/api');

describe('RankProviderTab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getRankProvider = vi.fn().mockResolvedValue(null);
    api.saveRankProvider = vi.fn().mockResolvedValue({});
    api.deleteRankProvider = vi.fn().mockResolvedValue({});
  });

  it('issues a delete rather than a save when the provider is None', async () => {
    api.getRankProvider = vi.fn().mockResolvedValue({
      provider_type: 'slipgate', base_url: 'https://slipgate.gg/api/v1',
      api_key: 'tok', game_type: null, extra: {}, enabled: true,
    });
    render(<RankProviderTab instanceId={7} />);
    await screen.findByLabelText(/provider/i);
    fireEvent.change(screen.getByLabelText(/provider/i), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(api.deleteRankProvider).toHaveBeenCalledWith(7));
    expect(api.saveRankProvider).not.toHaveBeenCalled();
  });

  it('hides the API key field for qlstats and shows it for the others', async () => {
    render(<RankProviderTab instanceId={7} />);
    await screen.findByLabelText(/provider/i);
    fireEvent.change(screen.getByLabelText(/provider/i), { target: { value: 'qlstats' } });
    expect(screen.queryByLabelText(/api key|upload token/i)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/provider/i), { target: { value: 'slipgate' } });
    expect(screen.getByLabelText(/upload token/i)).toBeInTheDocument();
  });

  it('persists an elo_b selection into extra', async () => {
    render(<RankProviderTab instanceId={7} />);
    await screen.findByLabelText(/provider/i);
    fireEvent.change(screen.getByLabelText(/provider/i), { target: { value: 'qlstats' } });
    fireEvent.change(screen.getByLabelText(/base url/i),
      { target: { value: 'http://qlstats.net' } });
    fireEvent.change(screen.getByLabelText(/rating system/i), { target: { value: 'elo_b' } });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(api.saveRankProvider).toHaveBeenCalled());
    expect(api.saveRankProvider.mock.calls[0][1].extra)
      .toEqual({ rating_system: 'elo_b' });
  });
});
```

These query by accessible label, so the `<label>`/`<span>` pairs in Step 1 need the field text associated with the control — use `htmlFor`/`id` or keep the control inside its `<label>`, which the Step 1 markup already does.

Run: `cd frontend-react && pnpm vitest run src/components/instances/__tests__/RankProviderTab.test.jsx`
Expected: PASS (3 tests)

- [ ] **Step 6: Lint and check the modal did not balloon**

Run: `cd frontend-react && pnpm lint`
Expected: no new errors.

Run: `grep -c '' src/components/instances/EditInstanceConfigModal.jsx`
Expected: within ~10 lines of 1413. More than that means logic leaked into the modal that belongs in `RankProviderTab.jsx`.

- [ ] **Step 7: Commit**

```bash
git add frontend-react/src/components/instances/RankProviderTab.jsx frontend-react/src/components/instances/__tests__/RankProviderTab.test.jsx frontend-react/src/components/instances/EditInstanceConfigModal.jsx
git commit -m "feat(rank): add rank provider configuration tab"
```

---

## Task 12: The ELO column

**Files:**
- Create: `frontend-react/src/components/instances/PlayerRankCell.jsx`
- Modify: `frontend-react/src/components/instances/LiveServerStatusModal.jsx`
- Test: `frontend-react/src/components/instances/__tests__/LiveServerStatusModal.test.jsx` (append)

- [ ] **Step 1: Write the failing tests**

**The existing file has none of the helpers these tests need — create them.** `LiveServerStatusModal.test.jsx` is 165 lines, imports only `render, screen, fireEvent` from `@testing-library/react`, defines `baseInstance` and `baseStatus` (whose `players` is `[]`), and calls `render(<LiveServerStatusModal ... />)` inline in every test. There is no `renderModal` and no `statusWithPlayers`. Add all three pieces below before appending the tests, or the four snippets cannot run.

Add to the existing import:

```javascript
import { render, screen, fireEvent, within } from '@testing-library/react';
```

Add next to `baseStatus`:

```javascript
const statusWithPlayers = {
  ...baseStatus,
  players: [
    { name: 'PlayerOne', steam: '76561198000000001', team: 'red', score: 5, ping: 30 },
  ],
};

const renderModal = (props = {}) => render(
  <LiveServerStatusModal
    isOpen
    onClose={() => {}}
    instance={baseInstance}
    serverStatus={baseStatus}
    {...props}
  />,
);
```

Add with the other mocks, at the top of the file:

```javascript
const mockUseRankData = vi.fn(() => ({ ranks: {}, configured: false }));
vi.mock('../../../hooks/useRankData', () => ({
  useRankData: (...args) => mockUseRankData(...args),
}));
```

**Do not drop that module mock as redundant.** All nine pre-existing tests in this file begin invoking `useRankData` the moment the modal calls it, and the mock is the only reason they keep passing without a network layer. Its default return (`configured: false`) is also what keeps those tests seeing the table exactly as it is on `main`.

Now append the four new tests:

```javascript
  it('hides the rank column entirely when no provider is configured', async () => {
    // Operators who never use this feature see the table exactly as before.
    mockUseRankData.mockReturnValue({ ranks: {}, configured: false });
    renderModal({ isOpen: true, serverStatus: statusWithPlayers });
    expect(screen.queryByRole('columnheader', { name: /elo/i })).not.toBeInTheDocument();
  });

  it('shows the rank column when a provider is configured', async () => {
    mockUseRankData.mockReturnValue({
      ranks: { 76561198000000001: { display: '1650', provisional: false } },
      configured: true,
    });
    renderModal({ isOpen: true, serverStatus: statusWithPlayers });
    expect(screen.getByRole('columnheader', { name: /elo/i })).toBeInTheDocument();
    expect(screen.getByText('1650')).toBeInTheDocument();
  });

  it('merges on the string steam id', async () => {
    // serverchecker.py writes exactly one identity field, "steam": str(steam_id).
    // String on both sides, always — an int key here misses every lookup.
    mockUseRankData.mockReturnValue({
      ranks: { 76561198000000001: { display: '1650', provisional: false } },
      configured: true,
    });
    renderModal({ isOpen: true, serverStatus: statusWithPlayers });
    const row = screen.getByText('PlayerOne').closest('tr');
    expect(within(row).getByText('1650')).toBeInTheDocument();
  });

  it('renders an em dash for a player with no rating', async () => {
    mockUseRankData.mockReturnValue({ ranks: {}, configured: true });
    renderModal({ isOpen: true, serverStatus: statusWithPlayers });
    const row = screen.getByText('PlayerOne').closest('tr');
    expect(within(row).getByText('—')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `cd frontend-react && pnpm vitest run src/components/instances/__tests__/LiveServerStatusModal.test.jsx`
Expected: FAIL — cannot resolve `../../../hooks/useRankData` mock target / no ELO header.

- [ ] **Step 3: Write the cell component**

Create `frontend-react/src/components/instances/PlayerRankCell.jsx`:

```jsx
import React from 'react';

/**
 * One rank cell. Its own file because LiveServerStatusModal is already 344
 * lines against a 300-line soft limit.
 *
 * `display` is printed whole and never parsed — Slipgate's field is named
 * display, not rating, and may be a label such as "1650 (Gold)".
 */
export default function PlayerRankCell({ rank }) {
  return (
    <td className="px-3 py-2 font-mono text-theme-secondary text-right">
      {rank?.display ?? '—'}
    </td>
  );
}
```

- [ ] **Step 4: Wire the hook into the modal**

In `LiveServerStatusModal.jsx`, add the imports:

```javascript
import { useRankData } from '../../hooks/useRankData';
import PlayerRankCell from './PlayerRankCell';
```

After the existing `sortedPlayers` memo, add:

```javascript
    // serverchecker.py:229-231 writes exactly one identity field,
    // "steam": str(p.steam_id). The p.steam || p.steamid || p.steam_id
    // fallback below is defensive, not evidence of three shapes.
    const steamIds = useMemo(
        () => sortedPlayers
            .map((p) => String(p.steam || p.steamid || p.steam_id || ''))
            .filter(Boolean),
        [sortedPlayers],
    );

    // enabled is required: this modal is mounted unconditionally in two places.
    const { ranks, configured: rankConfigured } = useRankData(
        instance?.id, steamIds, { enabled: isOpen && !!instance?.id },
    );
```

**The prop is `instance`, not `instanceId`.** This component destructures `{ isOpen, onClose, instance, serverStatus }` at `LiveServerStatusModal.jsx:68` — there is no `instanceId` in scope, so writing one is a `ReferenceError` on an undefined identifier. Use `instance?.id` in both places, as written above. Note that this is the opposite of Task 11, where `EditInstanceConfigModal` receives a bare `instanceId` and has no `instance`.

- [ ] **Step 5: Add the conditional header**

Between the `Team` and `Score` headers (`:301-302`) — rank data is a property of the player, closer to identity than to live match state:

```jsx
                                                                {rankConfigured && (
                                                                    <th className="px-3 py-2 font-medium text-right">ELO</th>
                                                                )}
```

- [ ] **Step 6: Add the conditional cell**

In the row body, between the team cell and the score cell (`:315-320`):

```jsx
                                                                    {rankConfigured && (
                                                                        <PlayerRankCell
                                                                            rank={ranks[String(p.steam || p.steamid || p.steam_id || '')]}
                                                                        />
                                                                    )}
```

- [ ] **Step 7: Run the tests**

Run: `cd frontend-react && pnpm vitest run src/components/instances/__tests__/LiveServerStatusModal.test.jsx`
Expected: PASS, including the pre-existing tests in that file.

- [ ] **Step 8: Lint**

Run: `cd frontend-react && pnpm lint`
Expected: no new errors.

- [ ] **Step 9: Visually verify**

This is a CSS/UI change, so it gets a real render, not just a passing test. Use the `playwright-screenshots` skill: start the dev server, log in with the permanent `admin:admin` dev credentials, configure a provider on an instance, and open the Live Status drawer.

Check specifically:
- With a provider configured, the ELO column appears between Team and Score and the numbers line up right-aligned with Score and Ping.
- With no provider, the table is pixel-identical to `main`.
- The column does not push Ping off the edge at a narrow drawer width.

A pre-implementation review of this feature noted that five separate defects all surface as the same symptom — a column of dashes against a healthy provider. A screenshot is the cheapest way to catch it; this repo has already shipped a casing bug through a full review that a render would have caught.

- [ ] **Step 10: Commit**

```bash
git add frontend-react/src/components/instances/PlayerRankCell.jsx frontend-react/src/components/instances/LiveServerStatusModal.jsx frontend-react/src/components/instances/__tests__/LiveServerStatusModal.test.jsx
git commit -m "feat(rank): show player ratings in the Live Status table"
```

---

## Task 13: Documentation

Per `CLAUDE.md`, docs land in the same PR as the change.

**Files:** `docs/api_reference.md`, `docs/architecture.md`, `docs/development_guidelines.md`, `docs/user/operations/live-status.md`, `docs/user/operations/rank-providers.md` (new), `mkdocs.yml`, `docs/user/index.json`

- [ ] **Step 1: Document the four endpoints**

In `docs/api_reference.md`, matching the file's existing entry format:

- `GET /api/instances/<id>/rank-provider` — current config or `null`. `api_key` is returned in clear text.
- `PUT /api/instances/<id>/rank-provider` — upsert `{provider_type, base_url, api_key, game_type, extra, enabled}`. `provider_type` and `base_url` required; `game_type` optional (blank derives from the live game type).
- `DELETE /api/instances/<id>/rank-provider` — remove.
- `GET /api/instances/<id>/ranks?steam_ids=a,b,c` — `{"data": {steam_id: {rating, display, provisional}}, "configured": bool}`. Always 200.

- [ ] **Step 2: Update the architecture doc**

In `docs/architecture.md`, add `RankProviderConfig` to the schema note and a short paragraph on the adapter pattern: a `provider_type` string selects an adapter from a registry; adding a provider is a new module plus a registry line, never a schema or route change.

- [ ] **Step 3: Document the pattern as a template**

In `docs/development_guidelines.md`, note `ui/rank_providers/` as the template for future external-service integrations: an ABC with a narrow return type, one adapter per file, a registry keyed by a stored string, errors swallowed at the adapter boundary, and a Redis cache keyed by a config+input fingerprint.

- [ ] **Step 4: Write the user page**

Create `docs/user/operations/rank-providers.md` covering: what the feature does, the three providers, where the setting lives (Edit Configuration → Rank Provider), what each field means, that the game type follows the server automatically and the override is only for pool names like `ffa_auto`, and that a blank column means no provider is configured while a dash means that one player has no rating.

- [ ] **Step 5: Register the new page in both places**

A new user page needs two hand-maintained registrations. Missing either leaves it unreachable from one surface:

1. A `nav:` entry in `mkdocs.yml` under the Operations section.
2. An entry in `docs/user/index.json`, which backs the in-app help.

- [ ] **Step 6: Update the live-status page and its screenshot**

`docs/user/operations/live-status.md` documents the player table field-by-field under "What You See" and "Player Sorting Logic", and embeds `../images/instance-live-status.png` at `:10`. Add the ELO column to the prose, and re-record the screenshot against an instance with a provider configured, using the `playwright-screenshots` skill.

This is the slowest item on the list because it needs the feature running against a real provider. Do it here rather than discovering it at PR time.

- [ ] **Step 7: Commit**

```bash
git add docs/ mkdocs.yml
git commit -m "docs: document rank provider integration"
```

---

## Task 14: PR, then the version bump

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feature/rank-provider-integration
```

**Stop here.** Do not open a PR. Wait for the user to say "create a PR" — this rule is not overridden by a skill, a passing review, or a "resume".

- [ ] **Step 2: After the user asks for a PR, open it**

The PR body must state that **`flask db upgrade` is part of this deployment** — this change adds a table, and without the migration step the deployed app raises `no such table: rank_provider_config` on first use.

- [ ] **Step 3: Bump all four version references, after the PR number exists**

Per this project's changelog convention the bump lands *after* the PR opens so the entry can cite the real number. All four must agree:

- `VERSION`
- `docs/user/version.json`
- `docs/user/releases.md` — the changelog entry, linking the real PR number, never an em-dash placeholder
- `README.md` — the `![Version](https://img.shields.io/badge/version-X.Y.Z-blue)` badge

Drift between them causes a wrong footer version, a spurious "update available" notice, or a stale badge.

```bash
git add VERSION docs/user/version.json docs/user/releases.md README.md
git commit -m "chore: bump version for rank provider integration"
git push
```

- [ ] **Step 4: Wait for review and explicit merge approval**

Watch the check-runs. Do not re-run the suite locally and do not compare against the base branch locally — CI owns that. **Never merge without the user explicitly saying so.** After merging: `git checkout main && git pull`.

---

## Deferred follow-ups

Reviewed and consciously left out of this slice. Do not implement these now.

- **Explicit rate limit on `/ranks`.** The 64-id cap plus the 60s cache already bounds outbound fan-out, and the endpoint is behind `@jwt_required()` on a single-user app.
- **Column header wording.** "ELO" is imprecise for Slipgate's tiers and elo-service's `mu`/`sort_score` scale; "Rank" or "Rating" would be more accurate. Cosmetic, and better decided once the column has been seen against all three providers.
- **Sorting by rating, and rendering `provisional`.** `RankResult` carries both fields so neither needs a schema change later. The locked display decision is deliberately minimal, and adding a sort was not requested.
- **A Redis `SET NX` single-flight lock** around the provider fetch. Explicitly rejected during the review as overengineering: it adds lock lifetime, stale-lock timeout and a waiter path to a request whose contract is "never fail", to save one duplicate HTTP call for a single user.
- **Rounding the elo-service display to the plugin's precision.** The adapter renders `f'{rating:g}'`, so `1802.5`, while `ranked.py:466` and `:672` wrap the value in `int()` and the in-game `!rating` shows `1802`. Cosmetic, and rounding discards precision the service actually returns. Better decided once the column has been rendered against all three providers, alongside the deferred header wording. If it is left as is, the difference is intentional.
- **Citing the source of qlstats' `_SUPPORTED` set.** The eight short codes are read off `Gametype` enum members rather than literal strings (`balance.py:48-57`), so their provenance is inferred. The values themselves are correct — `minqlxtended/_enums.py:344-363` is a `StrEnum` whose values match `minqlx/_core.py:54-55` code for code. A one-line comment would remove the question at review time; nothing is wrong without it.

---

## Self-review notes

Checked against the spec section by section. Coverage: Provider API shapes → Tasks 4-6; Game type derivation → Tasks 4-7; Architecture and interface → Task 3; Data flow → Tasks 7, 10, 12; steam_ids validation → Task 7; Caching → Task 7; Data model and migration → Task 1; Lifecycle wiring → Task 2; API → Task 8; Secret boundary → Tasks 1 and 8; Frontend changes → Tasks 9-12; Error handling → Tasks 4-8; Testing → every task; Documentation impact → Task 13; Version bump → Task 14.

Two spec ambiguities are resolved at the top of this plan rather than left to the implementer: the qlstats `base_url`/`extra.rating_system` split, and reading the live game type server-side from the status blob.

One signature detail worth restating, because it spans tasks: `fetch_ratings(steam_ids, game_type, instance_id=None)` is declared in `base.py` (Task 3, amended in Task 4 Step 3) and all three adapters implement that exact signature. `map_game_type(qlsm_gametype)` likewise.

---
**Review loop closed:** 2026-09-20
- Findings: `docs/findings/2026-09-20-rank-provider-integration-findings.md`
- Assessment: `docs/assess-review-findings/2026-09-20-rank-provider-integration-assessment.md`
- Spec: `docs/superpowers/specs/2026-09-20-rank-provider-integration-design.md`

---
**Review loop closed (round 2):** 2026-09-20
- Findings: `docs/findings/2026-09-20-rank-provider-integration-findings-r2.md`
- Assessment: `docs/assess-review-findings/2026-09-20-rank-provider-integration-assessment-r2.md`
- Accepted findings folded in: 1 (the two frontend wiring props were reversed —
  Task 12 uses `instance?.id`, Task 11 uses `instanceId`, hedge removed),
  2 (`1f`→`1flag` added to `_GAME_TYPE_MAP` and the parametrized test; the
  eleven-codes claim reconciled), 3 (the live Redis `gametype` is a bare
  lowercase short code such as `'ca'` under both runtimes — recorded next to
  `_live_gametype`, no normalization added), 4 (an autouse Redis stub for the
  route tests, and the provider-failure test now asserts the transport was
  reached), 5 (`configured` starts `false` and the `catch` leaves it untouched),
  6 (`ranks` and `configured` reset when `instanceId` changes), 7 (the stop
  latch is keyed on `instanceId` alone), 8 (`sort_score or mu`, plus the
  `{'sort_score': 0, 'mu': 22.5}` fixture), 9 (qlstats omits an
  `elo == 0, games == 0` bucket, plus the fixture player), 10 (migration test
  stamps at `20260915120000` and runs one revision each way; ini path from
  `__file__`; `sqlalchemy.url` line dropped), 11 (Task 12 Step 1 now creates
  `renderModal`, `statusWithPlayers` and the `within` import, and says why the
  module mock must stay), 12 (the rank panel is conditionally rendered and the
  "match the admins tab" instruction is gone), 13 (`balance.py:181` corrected to
  `:308` in both places), 14 (`extra` validation: string values, a 2048-char
  serialized bound, qlstats `rating_system` restricted to `elo`/`elo_b`, with
  four `PUT` tests), 15 (`/ranks` docstring reworded; the hook treats a `404` as
  `configured: false` and stops polling), 18 (`ranked.py:597` dropped),
  22 (Slipgate's single-player path documented as unused; the bulk `404` branch
  commented as belt-and-braces), 23 (`RankProviderTab.test.jsx` added to Task 11
  with three scoped cases)
- Deferred: 19 (rounding the elo-service display to the plugin's `int()`
  precision), 21 (citing the enum source of qlstats' `_SUPPORTED` set)
- Rejected, documents already correct: 16, 17 (the `:301-302` and `:315-320`
  citations), 20 (the Task 3 Step 5 note about the registry test staying red)
