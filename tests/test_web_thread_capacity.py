"""Real gthread/Engine.IO regression; never starts the development stack."""
from pathlib import Path

import pytest
import yaml

from scripts.probe_web_thread_capacity import scenario

ROOT = Path(__file__).resolve().parents[1]


def test_compose_has_configurable_socket_headroom():
    command = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())['services']['web']['command']
    assert '--threads=${WEB_THREADS:-48}' in command
    assert '--workers=1' in command


@pytest.mark.parametrize('threads,connections,starved', [(12, 12, True), (48, 24, False)])
def test_http_with_persistent_websockets(threads, connections, starved):
    result = scenario(threads, connections)
    assert result['recovery_seconds'] < 3
    if starved:
        assert result['http_timeout'] is True
    else:
        assert result['http_requests'] == 32
        assert result['max_seconds'] < 2
