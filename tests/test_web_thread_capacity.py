"""Real gthread/Engine.IO regression; never starts the development stack."""
import base64
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def probe(port, timeout=1):
    start = time.monotonic()
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/ping', timeout=timeout) as response:
        assert response.status == 200
        assert response.read() == b'pong'
    return time.monotonic() - start


def connect(port):
    sock = socket.create_connection(('127.0.0.1', port), timeout=3)
    key = base64.b64encode(os.urandom(16)).decode()
    try:
        sock.sendall((
            'GET /socket.io/?EIO=4&transport=websocket HTTP/1.1\r\n'
            f'Host: 127.0.0.1:{port}\r\n'
            'Upgrade: websocket\r\nConnection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n'
        ).encode())
        response = b''
        while b'\r\n\r\n' not in response:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError('Connection closed before upgrade')
            response += chunk
        assert b' 101 ' in response.split(b'\r\n', 1)[0]
        return sock
    except BaseException:
        sock.close()
        raise


def scenario(root, threads, count):
    (root / 'capacity_app.py').write_text(
        'from flask import Flask\nfrom flask_socketio import SocketIO\n'
        'app=Flask(__name__)\nsio=SocketIO(app, async_mode="threading")\n'
        '@app.get("/ping")\ndef ping(): return "pong"\n'
    )
    held = []
    with (root / 'server.log').open('w+') as log:
        # Pass the bound listener to the child, eliminating the port-allocation gap.
        with socket.socket() as allocator:
            allocator.bind(('127.0.0.1', 0))
            allocator.listen()
            port = allocator.getsockname()[1]
            process = subprocess.Popen([
                sys.executable, '-m', 'gunicorn', '--workers=1', f'--threads={threads}',
                f'--bind=fd://{allocator.fileno()}', '--graceful-timeout=1',
                'capacity_app:app',
            ], cwd=root, stdout=log, stderr=log, pass_fds=(allocator.fileno(),))
        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    probe(port)
                    break
                except (OSError, TimeoutError):
                    if process.poll() is not None or time.monotonic() >= deadline:
                        log.seek(0)
                        raise RuntimeError(log.read())
                    time.sleep(0.05)
            for _ in range(count):
                held.append(connect(port))
            if count == threads:
                with pytest.raises((OSError, TimeoutError)):
                    probe(port)
            else:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    times = list(pool.map(lambda _: probe(port, 2), range(32)))
                assert len(times) == 32
                assert max(times) < 2
            for sock in held:
                sock.close()
            held.clear()
            assert probe(port, 3) < 3
        finally:
            for sock in held:
                sock.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_compose_has_configurable_socket_headroom():
    command = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())['services']['web']['command']
    assert '--threads=${WEB_THREADS:-48}' in command
    assert '--workers=1' in command


@pytest.mark.parametrize('threads,connections', [(12, 12), (48, 24)])
def test_http_with_persistent_websockets(tmp_path, threads, connections):
    scenario(tmp_path, threads, connections)
