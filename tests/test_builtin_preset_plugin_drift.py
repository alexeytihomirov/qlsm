"""Built-in default presets must carry the same plugin code as their pool.

A plugin that exists in both a built-in preset's scripts/ and the runtime's
ql-assets pool ships twice: new instances get the preset copy, and the host
pool backfills the pool copy. When the two drift, a fix lands in one place and
never reaches half the servers. That happened to seven minqlx plugins before
b547508, including a "supersecret" default Discord admin password that only
the preset still had.

Only files present in both trees are compared. Preset-only plugins (highfps,
footsteps) and pool plugins a preset doesn't ship (serverchecker.py and the
opt-in extras) are not drift.
"""
import os

import pytest

PAIRS = [
    ('configs/presets/_builtin/default/scripts', 'ql-assets/data/minqlx-plugins'),
    ('configs/presets/_builtin/default-minqlxtended/scripts', 'ql-assets/data/minqlxtended-plugins'),
]

# '<preset dir>/<relpath>' -> why this preset copy is allowed to differ.
# Keep it empty unless a difference is deliberate, and say why.
ALLOWED_DIFFERENCES = {}


def _python_files(root):
    found = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for name in filenames:
            if name.endswith('.py'):
                found.add(os.path.relpath(os.path.join(dirpath, name), root))
    return found


def _read(path):
    with open(path, 'rb') as handle:
        return handle.read()


@pytest.mark.parametrize('preset_dir,pool_dir', PAIRS)
def test_shared_plugins_match_the_pool(preset_dir, pool_dir):
    shared = _python_files(preset_dir) & _python_files(pool_dir)
    assert shared, f'no shared plugins found between {preset_dir} and {pool_dir}'

    drifted = sorted(
        rel for rel in shared
        if _read(os.path.join(preset_dir, rel)) != _read(os.path.join(pool_dir, rel))
        and f'{preset_dir}/{rel}' not in ALLOWED_DIFFERENCES
    )
    assert drifted == [], (
        f'{preset_dir} and {pool_dir} disagree on: {", ".join(drifted)}. '
        'Copy the correct version into both, or add an ALLOWED_DIFFERENCES '
        'entry explaining why they differ.'
    )


def test_allowed_differences_still_differ():
    """An allowlist entry whose files match again is stale; remove it."""
    stale = []
    for key in ALLOWED_DIFFERENCES:
        for preset_dir, pool_dir in PAIRS:
            prefix = preset_dir + '/'
            if key.startswith(prefix):
                rel = key[len(prefix):]
                if _read(os.path.join(preset_dir, rel)) == _read(os.path.join(pool_dir, rel)):
                    stale.append(key)
                break
        else:
            stale.append(key)
    assert stale == [], f'stale ALLOWED_DIFFERENCES entries: {stale}'
