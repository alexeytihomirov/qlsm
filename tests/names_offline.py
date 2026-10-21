"""OFFLINE engine/Redis doubles, no sockets, native engine or Steam lookup.

Snapshots follow minqlx fbdd915 and minqlxtended a3de947 _player.py: name
returns cached _name + ^7; minqlx cvars stay cached after assignment, whereas
minqlxtended invalidates _userinfo but still retains the old _info snapshot.
Transport creates a FRESH pre-write Player per event, diffs/merges synchronously
as _handlers.py does, then updates backing state, not existing Player objects.
Set NAMES_ENGINE_ROOT=/workspace to exercise AST-extracted real engine setters
and getters instead of the equivalent offline implementations below.
"""
import ast
from collections import Counter
import os
from pathlib import Path
import re
import types
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    'ql-assets/data/minqlx-plugins/names.py',
    'configs/presets/_builtin/default/scripts/names.py',
    'ql-assets/data/minqlxtended-plugins/names.py',
    'configs/presets/_builtin/default-minqlxtended/scripts/names.py',
]


def clean(value):
    return re.sub(r'\^[0-9]', '', value)


class DB(dict):
    """Redis-like GET/EXISTS/DEL, including DEL's missing-key tolerance."""
    def __init__(self):
        super().__init__()
        self.calls = Counter()

    def get(self, key, default=None):
        self.calls['get'] += 1
        return super().get(key, default)

    def __contains__(self, key):
        self.calls['exists'] += 1
        return super().__contains__(key)

    def __getitem__(self, key):
        self.calls['get'] += 1
        return super().__getitem__(key)

    def __delitem__(self, key):
        self.calls['delete'] += 1
        self.pop(key, None)


class Plugin:
    def add_hook(self, *args, **kwargs):
        pass

    def add_command(self, *args, **kwargs):
        pass

    def set_cvar_once(self, *args):
        pass

    def get_cvar(self, name, cast=None):
        return self.enforce if name == 'qlx_enforceSteamName' else '!'

    clean_text = staticmethod(clean)


def extract(path, name, env, cls=None, setter=False):
    tree = ast.parse(path.read_text())
    scope = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                 and n.name == cls).body if cls else tree.body
    nodes = [n for n in scope if isinstance(n, ast.FunctionDef) and n.name == name]
    node = nodes[-1] if setter else nodes[0]
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), env)
    return env[name]


class Harness:
    def __init__(self, rel, monkeypatch):
        self.ext = 'minqlxtended' in rel
        runtime = 'minqlxtended' if self.ext else 'minqlx'
        module = types.ModuleType(runtime)
        module.Plugin = Plugin
        module.RET_USAGE, module.RET_STOP_ALL = 1, 3
        module.Return = types.SimpleNamespace(USAGE=1, STOP_ALL=3)
        module.setting = lambda name, default: default
        module.hook = module.command = lambda *a, **kw: lambda f: f
        module.client_command = self.client_command
        module.parse_variables = lambda raw, **kw: self.parse(raw)
        module.parse_infostring = self.parse
        module.format_infostring = self.format
        monkeypatch.setitem(__import__('sys').modules, runtime, module)
        env = {'__name__': 'offline_names'}
        exec(compile((ROOT / rel).read_text(), str(ROOT / rel), 'exec'), env)
        self.plugin = env['names']()
        self.plugin.db = DB()
        self.plugin.enforce = True
        self.version = env['VERSION']
        self.state, self.messages = {}, {}
        self.events, self.writes = [], []
        self.before_write = None
        self.mode = 'normal'
        self.after_hook = None
        self.Player = self.player_class(module)

    @staticmethod
    def parse(raw):
        parts = raw.lstrip('\\').split('\\')
        return dict(zip(parts[::2], parts[1::2]))

    @staticmethod
    def format(values):
        if any(c in str(v) for v in values.values() for c in '\\;"'):
            raise ValueError('forbidden infostring character')
        return ''.join(f'\\{k}\\{v}' for k, v in values.items())

    def player_class(self, module):
        h = self

        class Player:
            def __init__(self, slot):
                self.id = slot
                self.steam_id = h.state[slot]['sid']
                self._name = h.state[slot]['info']['name']
                self._info = types.SimpleNamespace(userinfo=''.join(
                    f'\\{k}\\{v}' for k, v in h.state[slot]['info'].items()))
                self._userinfo = None
                self._valid = True

            @property
            def cvars(self):
                if self._userinfo is None:
                    self._userinfo = h.parse(self._info.userinfo)
                return self._userinfo.copy()

            @cvars.setter
            def cvars(self, values):
                raw = h.format(values) if h.ext else ''.join(
                    f'\\{k}\\{v}' for k, v in values.items())
                module.client_command(self.id, f'userinfo "{raw}"')
                if h.ext:
                    self._userinfo = None

            @property
            def name(self):
                return self._name + '^7'

            @name.setter
            def name(self, value):
                values = self.cvars
                values['name'] = value
                self.cvars = values

            clean_name = property(lambda self: clean(self.name))

            def tell(self, value):
                h.messages[self.id].append(value)

        source_root = os.environ.get('NAMES_ENGINE_ROOT')
        if source_root:
            runtime = module.__name__
            path = Path(source_root) / runtime / 'python' / runtime / '_player.py'
            env = {runtime: module, 're': re, '_re_color_code': re.compile(r'\^[0-9]'),
                   'Any': Any, 'Mapping': Mapping}
            for name in ('name', 'cvars'):
                setattr(Player, name, property(extract(path, name, env, 'Player'),
                                              extract(path, name, env, 'Player', True)))
            Player.clean_name = property(extract(path, 'clean_name', env, 'Player'))
            if self.ext:
                for name in ('_set_userinfo', '_cvars'):
                    setattr(Player, name, extract(path, name, env, 'Player'))
        return Player

    def add(self, name='Same', slot=0, connect=True, loaded=True):
        self.state[slot] = {'sid': 76561198000000001 + slot, 'info': {'name': name}}
        self.messages[slot] = []
        if connect:
            p = self.snapshot(slot)
            if self.ext:
                self.plugin.handle_player_connect(p, False)
            else:
                self.plugin.handle_player_connect(p)
        if loaded:
            self.plugin.handle_player_loaded(self.snapshot(slot))
        return self.snapshot(slot)

    def snapshot(self, slot=0):
        return self.Player(slot)

    def key(self, slot=0):
        return f'minqlx:players:{self.state[slot]["sid"]}:colored_name'

    def raw(self, slot=0):
        return self.state[slot]['info']['name']

    def userinfo(self, player, changed):
        self.events.append((player.steam_id, changed.copy()))
        if self.ext:
            result = self.plugin.handle_userinfo(player, changed, self.format(changed))
        else:
            result = self.plugin.handle_userinfo(player, changed)
        if self.after_hook:
            self.after_hook(player, changed)
            result = changed
        return result

    def client_command(self, slot, command):
        self.writes.append(command)
        if self.before_write:
            self.before_write()
        if self.mode == 'blocked':
            return False
        if self.mode == 'error':
            raise RuntimeError('OFFLINE transport error')
        values = self.parse(command[len('userinfo "'):-1])
        self.change(slot=slot, **values)
        return True

    def change(self, slot=0, **values):
        old = self.state[slot]['info']
        new = dict(old, **values)
        changed = {k: v for k, v in new.items() if old.get(k) != v}
        if changed:
            result = self.userinfo(self.snapshot(slot), changed)
            if isinstance(result, dict):
                new.update(result)
        self.state[slot]['info'] = new

    def command(self, *parts, slot=0):
        return self.plugin.cmd_name(self.snapshot(slot), ['!name', *parts], None)

    def enforce(self, enabled):
        self.plugin.enforce = enabled
        if self.ext:
            self.plugin._qlx_enforceSteamName = enabled
