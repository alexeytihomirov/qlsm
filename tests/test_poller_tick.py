"""`poller.tick` fires once per status-poller cycle and can never hurt it.

The poller is a long-running daemon: a handler that raises, or that is slow,
must not stop it polling hosts. The loop is driven for a fixed number of
cycles with a fake stop event and a fake clock, so nothing sleeps.
"""
import logging
import signal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ui.addons.hooks import HOOK_SCOPES


class _FakeStopEvent:
    """Reports 'not set' for `cycles` checks, then 'set'; wait() never sleeps."""
    cycles = 1

    def __init__(self):
        self._checks = 0

    def is_set(self):
        self._checks += 1
        return self._checks > self.cycles

    def set(self):
        self._checks = self.cycles + 1

    def wait(self, timeout=None):
        return False


@pytest.fixture
def run_poller(app):
    """Run `flask run-status-poller` for N cycles; returns the CLI result."""
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}

    def _run(cycles=1, clock=None):
        _FakeStopEvent.cycles = cycles
        patches = [patch('ui.cli.threading.Event', _FakeStopEvent)]
        if clock is not None:
            patches.append(patch('ui.cli.time', SimpleNamespace(monotonic=clock)))
        for p in patches:
            p.start()
        try:
            return app.test_cli_runner().invoke(app.cli.commands['run-status-poller'])
        finally:
            for p in patches:
                p.stop()

    yield _run
    for sig, handler in saved.items():
        signal.signal(sig, handler)


def test_poller_tick_is_a_global_hook():
    assert HOOK_SCOPES['poller.tick'] == 'global'


def test_tick_is_dispatched_once_per_cycle_after_the_poll(run_poller):
    calls = []
    with patch('ui.task_logic.server_status_poll.poll_all_hosts',
               side_effect=lambda: calls.append('poll')), \
            patch('ui.addons.dispatch',
                  side_effect=lambda hook, *a, **k: calls.append(hook)):
        result = run_poller(cycles=3)
    assert result.exit_code == 0
    assert calls == ['poll', 'poller.tick'] * 3


def test_tick_still_fires_when_the_poll_cycle_fails(run_poller):
    with patch('ui.task_logic.server_status_poll.poll_all_hosts',
               side_effect=RuntimeError('ssh down')), \
            patch('ui.addons.dispatch') as dispatch:
        result = run_poller(cycles=1)
    assert result.exit_code == 0
    dispatch.assert_called_once_with('poller.tick')


def test_a_raising_handler_does_not_stop_the_loop(app, run_poller, caplog):
    """dispatch() isolates handlers itself; the loop also survives dispatch
    itself blowing up (e.g. a broken registry)."""
    with patch('ui.task_logic.server_status_poll.poll_all_hosts') as poll, \
            patch('ui.addons.dispatch', side_effect=RuntimeError('boom')) as dispatch, \
            caplog.at_level(logging.ERROR, logger='ui.cli'):
        result = run_poller(cycles=3)
    assert result.exit_code == 0
    assert poll.call_count == 3
    assert dispatch.call_count == 3
    assert 'poller.tick dispatch failed' in caplog.text


def test_a_slow_tick_logs_a_warning(run_poller, caplog):
    # monotonic() is read before and after the dispatch: 12s apart
    ticks = iter([100.0, 112.0])
    with patch('ui.task_logic.server_status_poll.poll_all_hosts'), \
            patch('ui.addons.dispatch'), \
            caplog.at_level(logging.WARNING, logger='ui.cli'):
        run_poller(cycles=1, clock=lambda: next(ticks))
    assert 'poller.tick handlers took 12.0s' in caplog.text


def test_a_fast_tick_logs_no_warning(run_poller, caplog):
    ticks = iter([100.0, 100.5])
    with patch('ui.task_logic.server_status_poll.poll_all_hosts'), \
            patch('ui.addons.dispatch'), \
            caplog.at_level(logging.WARNING, logger='ui.cli'):
        run_poller(cycles=1, clock=lambda: next(ticks))
    assert 'poller.tick' not in caplog.text


def test_session_is_rolled_back_after_each_tick(run_poller):
    """dispatch() swallows handler errors, so a handler that left the shared
    session needing a rollback would fail every later cycle without this."""
    with patch('ui.task_logic.server_status_poll.poll_all_hosts'), \
            patch('ui.addons.dispatch'), \
            patch('ui.db.session.rollback') as rollback:
        result = run_poller(cycles=2)
    assert result.exit_code == 0
    assert rollback.call_count == 2
