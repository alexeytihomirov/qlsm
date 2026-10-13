"""Bounded isolated capacity reproduction, using only stdlib + app dependencies.

Run inside the deployed image with --network=none and no production mounts.
Does not connect to Redis, SQLite, game servers, or the development stack.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


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


def scenario(threads, count):
    with tempfile.TemporaryDirectory(prefix='capacity-', dir=os.environ.get('TMPDIR')) as directory:
        root = Path(directory)
        (root / 'capacity_app.py').write_text(
            'from flask import Flask\nfrom flask_socketio import SocketIO\n'
            'app=Flask(__name__)\nsio=SocketIO(app, async_mode="threading")\n'
            '@app.get("/ping")\ndef ping(): return "pong"\n'
        )
        with socket.socket() as allocator:
            allocator.bind(('127.0.0.1', 0))
            port = allocator.getsockname()[1]
        held = []
        with (root / 'server.log').open('w+') as log:
            process = subprocess.Popen([
                sys.executable, '-m', 'gunicorn', '--workers=1', f'--threads={threads}',
                f'--bind=127.0.0.1:{port}', '--graceful-timeout=1', 'capacity_app:app',
            ], cwd=root, stdout=log, stderr=log)
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
                    try:
                        probe(port)
                    except (OSError, TimeoutError):
                        result = {'threads': threads, 'websockets': count, 'http_timeout': True}
                    else:
                        raise AssertionError('Expected thread starvation was not reproduced')
                else:
                    with ThreadPoolExecutor(max_workers=8) as pool:
                        times = list(pool.map(lambda _: probe(port, 2), range(32)))
                    result = {'threads': threads, 'websockets': count,
                              'http_requests': len(times), 'max_seconds': max(times)}
                for sock in held:
                    sock.close()
                held.clear()
                result['recovery_seconds'] = probe(port, 3)
                print(json.dumps(result), flush=True)
                return result
            finally:
                for sock in held:
                    sock.close()
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == '__main__':
    scenario(12, 12)
    scenario(48, 24)
