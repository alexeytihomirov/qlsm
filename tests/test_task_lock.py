import pytest
from unittest.mock import ANY, MagicMock, call, patch

from ui import task_lock
from ui.task_lock import acquire_lock, acquire_locks, release_lock, release_locks


class ScriptRedis:
    """Small Redis double that evaluates the lock scripts' effects."""

    def __init__(self):
        self.values = {}
        self.expiries = {}
        self.sets = {}

    def execute_command(self, command, script, key_count, *args):
        assert command == 'EVAL'
        keys = args[:key_count]
        argv = args[key_count:]
        if "'SADD'" in script:
            return self._acquire_entity(keys, argv)
        if "'SMEMBERS'" in script:
            return self._acquire_maintenance(keys, argv)
        if "'GET', KEYS[1]" in script:
            return self._release(script, keys, argv)
        return self._force_release(keys)

    def _acquire_entity(self, keys, argv):
        key, maintenance_key, index_key = keys
        token, ttl = argv
        if maintenance_key in self.values or key in self.values:
            return 0
        self.values[key] = token
        self.expiries[key] = int(ttl)
        self.sets.setdefault(index_key, set()).add(key)
        return 1

    def _acquire_maintenance(self, keys, argv):
        key, index_key = keys
        token, ttl = argv
        if key in self.values:
            return 0
        # Walk the index the way the script does, dropping entries whose lock
        # has expired rather than treating them as live.
        for tracked in sorted(self.sets.get(index_key, set())):
            if tracked in self.values:
                return 0
            self.sets[index_key].discard(tracked)
        self.values[key] = token
        self.expiries[key] = int(ttl)
        return 1

    def _release(self, script, keys, argv):
        key = keys[0]
        if self.values.get(key) != argv[0]:
            return 0
        if "'SREM', KEYS[2], KEYS[1]" in script:
            self.sets.get(keys[1], set()).discard(key)
        del self.values[key]
        self.expiries.pop(key, None)
        return 1

    def _force_release(self, keys):
        key, index_key = keys
        self.sets.get(index_key, set()).discard(key)
        self.expiries.pop(key, None)
        return 1 if self.values.pop(key, None) is not None else 0


@pytest.fixture
def mock_redis():
    """Provide a mock Redis client via the app extension."""
    mock = MagicMock()
    with patch('ui.task_lock._get_redis') as get_redis:
        get_redis.return_value = mock
        yield mock

class TestAcquireLock:
    def test_acquire_succeeds(self, mock_redis):
        mock_redis.execute_command.return_value = 1
        result = acquire_lock('host', 1, 'token-abc', ttl=300)
        assert result is True
        mock_redis.execute_command.assert_called_once_with(
            'EVAL', ANY, 3, 'task_lock:host:1', 'maintenance_lock:backup',
            'task_lock:index', 'token-abc', 300,
        )

    def test_acquire_fails_when_locked(self, mock_redis):
        mock_redis.execute_command.return_value = 0
        result = acquire_lock('host', 1, 'token-abc', ttl=300)
        assert result is False

    def test_acquire_uses_correct_key_format(self, mock_redis):
        mock_redis.execute_command.return_value = 1
        acquire_lock('instance', 42, 'tok', ttl=120)
        mock_redis.execute_command.assert_called_once_with(
            'EVAL', ANY, 3, 'task_lock:instance:42', 'maintenance_lock:backup',
            'task_lock:index', 'tok', 120,
        )

    def test_acquire_refuses_while_a_backup_holds_maintenance(self):
        redis_client = ScriptRedis()
        assert task_lock.acquire_maintenance_lock(redis_client, 'backup-owner')

        with patch('ui.task_lock._get_redis', return_value=redis_client):
            assert acquire_lock('host', 1, 'task-owner', ttl=300) is False

class TestReleaseLock:
    def test_release_own_lock(self, mock_redis):
        mock_redis.execute_command.return_value = 1
        result = release_lock('host', 1, 'token-abc')
        assert result is True

    def test_release_someone_elses_lock(self, mock_redis):
        mock_redis.execute_command.return_value = 0
        result = release_lock('host', 1, 'wrong-token')
        assert result is False

    def test_release_nonexistent_lock(self, mock_redis):
        mock_redis.execute_command.return_value = 0
        result = release_lock('host', 999, 'any-token')
        assert result is False


class TestAcquireLocks:
    @patch('ui.task_lock.acquire_lock', return_value=True)
    def test_deduplicates_and_acquires_ids_in_ascending_order(self, mock_acquire):
        result = acquire_locks('instance', [9, 2, 9, 4], 'batch-token', ttl=3660)

        assert result is True
        assert mock_acquire.call_args_list == [
            call('instance', 2, 'batch-token', 3660),
            call('instance', 4, 'batch-token', 3660),
            call('instance', 9, 'batch-token', 3660),
        ]

    @patch('ui.task_lock.release_lock', return_value=True)
    @patch('ui.task_lock.acquire_lock', side_effect=[True, True, False])
    def test_failed_acquisition_releases_every_owned_partial_lock(
        self, mock_acquire, mock_release
    ):
        result = acquire_locks('instance', [3, 1, 2], 'batch-token', ttl=1260)

        assert result is False
        assert mock_acquire.call_args_list == [
            call('instance', 1, 'batch-token', 1260),
            call('instance', 2, 'batch-token', 1260),
            call('instance', 3, 'batch-token', 1260),
        ]
        assert mock_release.call_args_list == [
            call('instance', 1, 'batch-token'),
            call('instance', 2, 'batch-token'),
        ]

    @patch('ui.task_lock.release_lock', return_value=True)
    @patch(
        'ui.task_lock.acquire_lock',
        side_effect=[True, RuntimeError('redis down')],
    )
    def test_acquisition_exception_releases_owned_locks_and_propagates(
        self, mock_acquire, mock_release
    ):
        with pytest.raises(RuntimeError, match='redis down'):
            acquire_locks('instance', [2, 1], 'batch-token', ttl=1260)

        assert mock_acquire.call_args_list == [
            call('instance', 1, 'batch-token', 1260),
            call('instance', 2, 'batch-token', 1260),
        ]
        mock_release.assert_called_once_with('instance', 1, 'batch-token')


class TestReleaseLocks:
    @patch('ui.task_lock.release_lock', side_effect=[RuntimeError('redis down'), True, True])
    def test_attempts_every_unique_id_when_one_release_raises(self, mock_release):
        release_locks('instance', [4, 2, 4, 3], 'batch-token')

        assert mock_release.call_args_list == [
            call('instance', 2, 'batch-token'),
            call('instance', 3, 'batch-token'),
            call('instance', 4, 'batch-token'),
        ]


class TestMaintenanceLock:
    def test_acquisition_fails_while_another_backup_holds_it(self):
        redis_client = ScriptRedis()
        assert task_lock.acquire_maintenance_lock(redis_client, 'first-owner')

        assert task_lock.acquire_maintenance_lock(redis_client, 'second-owner') is False
        assert redis_client.values['maintenance_lock:backup'] == 'first-owner'

    def test_acquisition_fails_while_an_entity_lock_is_held(self):
        redis_client = ScriptRedis()
        with patch('ui.task_lock._get_redis', return_value=redis_client):
            assert acquire_lock('instance', 9, 'task-owner', ttl=300)

        assert task_lock.acquire_maintenance_lock(redis_client, 'backup-owner') is False

    @pytest.mark.parametrize('first', ['maintenance', 'entity'])
    def test_atomic_acquisitions_cannot_both_win(self, first):
        redis_client = ScriptRedis()
        with patch('ui.task_lock._get_redis', return_value=redis_client):
            operations = {
                'maintenance': lambda: task_lock.acquire_maintenance_lock(
                    redis_client, 'backup-owner'
                ),
                'entity': lambda: acquire_lock('host', 1, 'task-owner', ttl=300),
            }
            second = 'entity' if first == 'maintenance' else 'maintenance'

            assert operations[first]() is True
            assert operations[second]() is False

    def test_acquisition_ignores_unrelated_keys_instead_of_scanning(self):
        """RQ shares this Redis, so its keys must not read as held locks."""
        redis_client = ScriptRedis()
        redis_client.values.update({
            'rq:job:abc123': 'queued',
            'rq:results:abc123': 'done',
            'task_lock_lookalike': 'not-a-lock',
        })

        assert task_lock.acquire_maintenance_lock(redis_client, 'backup-owner')
        assert 'SCAN' not in task_lock._ACQUIRE_MAINTENANCE_SCRIPT

    def test_acquisition_prunes_index_entries_whose_lock_expired(self):
        redis_client = ScriptRedis()
        with patch('ui.task_lock._get_redis', return_value=redis_client):
            assert acquire_lock('host', 4, 'task-owner', ttl=300)

        # The TTL lapses without a release, leaving only the index entry.
        del redis_client.values['task_lock:host:4']

        assert task_lock.acquire_maintenance_lock(redis_client, 'backup-owner')
        assert redis_client.sets['task_lock:index'] == set()

    def test_released_entity_lock_stops_blocking_acquisition(self):
        redis_client = ScriptRedis()
        with patch('ui.task_lock._get_redis', return_value=redis_client):
            assert acquire_lock('host', 4, 'task-owner', ttl=300)
            assert task_lock.acquire_maintenance_lock(redis_client, 'owner') is False
            assert release_lock('host', 4, 'task-owner')

        assert redis_client.sets['task_lock:index'] == set()
        assert task_lock.acquire_maintenance_lock(redis_client, 'backup-owner')

    def test_force_released_lock_stops_blocking_acquisition(self):
        redis_client = ScriptRedis()
        with patch('ui.task_lock._get_redis', return_value=redis_client):
            assert acquire_lock('host', 4, 'task-owner', ttl=300)
            assert task_lock.force_release_lock('host', 4)

        assert redis_client.sets['task_lock:index'] == set()
        assert task_lock.acquire_maintenance_lock(redis_client, 'backup-owner')

    def test_only_owner_can_release(self):
        redis_client = ScriptRedis()
        assert task_lock.acquire_maintenance_lock(redis_client, 'backup-owner')

        assert task_lock.release_maintenance_lock(redis_client, 'other-owner') is False
        assert redis_client.values['maintenance_lock:backup'] == 'backup-owner'
        assert task_lock.release_maintenance_lock(redis_client, 'backup-owner') is True
        assert 'maintenance_lock:backup' not in redis_client.values

    def test_ttl_outlasts_a_backup_since_nothing_refreshes_it(self):
        redis_client = ScriptRedis()
        assert task_lock.acquire_maintenance_lock(redis_client, 'backup-owner')

        assert redis_client.expiries['maintenance_lock:backup'] == 1800
        assert task_lock.MAINTENANCE_LOCK_TTL == 1800


class TestBackupMaintenanceLockContext:
    def test_context_releases_the_lock_on_the_way_out(self):
        redis_client = ScriptRedis()
        with patch('ui.task_lock._get_redis', return_value=redis_client):
            with task_lock.backup_maintenance_lock('backup-owner') as acquired:
                assert acquired is True
                assert redis_client.values['maintenance_lock:backup'] == 'backup-owner'

        assert 'maintenance_lock:backup' not in redis_client.values

    def test_context_yields_false_without_taking_a_held_lock(self):
        redis_client = ScriptRedis()
        with patch('ui.task_lock._get_redis', return_value=redis_client):
            assert acquire_lock('host', 1, 'task-owner', ttl=300)

            with task_lock.backup_maintenance_lock('backup-owner') as acquired:
                assert acquired is False

        assert 'maintenance_lock:backup' not in redis_client.values
        assert redis_client.values['task_lock:host:1'] == 'task-owner'

    def test_exception_in_the_body_still_releases_the_lock(self):
        redis_client = ScriptRedis()
        with (
            patch('ui.task_lock._get_redis', return_value=redis_client),
            pytest.raises(RuntimeError, match='restore failed'),
        ):
            with task_lock.backup_maintenance_lock('backup-owner'):
                raise RuntimeError('restore failed')

        assert 'maintenance_lock:backup' not in redis_client.values

    def test_release_only_removes_its_own_token(self):
        redis_client = ScriptRedis()
        with patch('ui.task_lock._get_redis', return_value=redis_client):
            with task_lock.backup_maintenance_lock('backup-owner'):
                # A TTL lapse and a fresh backup taking over mid-body.
                redis_client.values['maintenance_lock:backup'] = 'replacement-owner'

        assert redis_client.values['maintenance_lock:backup'] == 'replacement-owner'


class TestLockSuperseded:
    def test_false_when_owned(self, mock_redis):
        mock_redis.get.return_value = 'tok-a'
        assert task_lock.lock_superseded('instance', 1, 'tok-a') is False

    def test_true_when_other_token(self, mock_redis):
        mock_redis.get.return_value = 'tok-b'
        assert task_lock.lock_superseded('instance', 1, 'tok-a') is True

    def test_true_when_other_token_as_bytes(self, mock_redis):
        mock_redis.get.return_value = b'tok-b'
        assert task_lock.lock_superseded('instance', 1, 'tok-a') is True

    def test_false_when_key_missing(self, mock_redis):
        mock_redis.get.return_value = None
        assert task_lock.lock_superseded('instance', 1, 'tok-a') is False

    def test_false_when_token_none(self, mock_redis):
        mock_redis.get.return_value = 'tok-b'
        assert task_lock.lock_superseded('instance', 1, None) is False
