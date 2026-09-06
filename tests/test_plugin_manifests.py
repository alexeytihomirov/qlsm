"""Both plugin baselines must ship a manifest, and it must match the files."""
import json
import os

from ui.plugin_compat import baseline_digest
from scripts.gen_plugin_manifest import QLSM_PLUGINS_BY_RUNTIME

BASELINES = ['minqlx-plugins', 'minqlxtended-plugins']

# QLSM's own plugins, ported to each runtime's API -- not upstream code. This
# fork's minqlx-plugins pool is a different, smaller curated set than
# minqlxtended-plugins' (most of the seven QLSM ports minqlxtended-plugins
# carries were never carried here) -- see the comment on
# QLSM_PLUGINS_BY_RUNTIME['minqlx'] in scripts/gen_plugin_manifest.py, which
# is imported here rather than duplicated so the two cannot drift apart.
QLSM_PLUGINS = list(QLSM_PLUGINS_BY_RUNTIME['minqlx'])


def _dir(name):
    return os.path.join('ql-assets', 'data', name)


def test_every_baseline_has_a_manifest():
    for name in BASELINES:
        assert os.path.isfile(os.path.join(_dir(name), 'manifest.json')), \
            f"{name} has no manifest.json -- baseline_hashes() would return {{}} " \
            f"and every plugin would be stripped in that direction"


def test_manifest_covers_every_py_file_and_hashes_match():
    for name in BASELINES:
        directory = _dir(name)
        with open(os.path.join(directory, 'manifest.json'), encoding='utf-8') as fh:
            files = json.load(fh)['files']
        on_disk = sorted(f for f in os.listdir(directory) if f.endswith('.py'))
        assert sorted(files) == on_disk, f"{name}: manifest and directory disagree"
        for filename in on_disk:
            with open(os.path.join(directory, filename), encoding='utf-8') as fh:
                text = fh.read()
            assert files[filename]['sha256'] == baseline_digest(text), \
                f"{name}/{filename}: manifest hash does not match the file"


def test_minqlx_qlsm_ports_are_marked_qlsm():
    with open(os.path.join(_dir('minqlx-plugins'), 'manifest.json'), encoding='utf-8') as fh:
        files = json.load(fh)['files']
    for filename in QLSM_PLUGINS:
        assert files[filename]['origin'] == 'qlsm', filename
    non_qlsm = [f for f in files if f not in QLSM_PLUGINS]
    mislabeled = [f for f in non_qlsm if files[f]['origin'] != 'upstream']
    assert mislabeled == [], f"non-QLSM files marked something other than upstream: {mislabeled}"
