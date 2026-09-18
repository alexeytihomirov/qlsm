"""Unit tests for demo_native_manifest.py's packer_command() argv builder.

Ported from ql-server-core/tests/test_demo_native_manifest.py when the native
multi-POV demo capture plugin (demo_native_autorecord.py /
demo_native_manifest.py) moved into ql-assets/data/minqlx-plugins/ — the
plugin pool is this repo's source of truth (see
qlsm-plugin-pool-vs-builtin-preset-duplication in project memory), so its
tests move here too, same convention test_match_restore_*.py already uses
for sys.path'ing into the pool.

demo_native_manifest.py used to also build the .qlmatch manifest/zip itself
(an in-process fallback for when the external packer/Node was missing); that
fallback -- and its tests -- moved out once qlmatch-packer became the
format's sole owner (see addons/qlmatch-packer/). What is left here is the
pure, testable argv-building for launching the external packer.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "ql-assets", "data", "minqlx-plugins")
)

MATCH_ID = "20260817T120000Z"
MAP_NAME = "overkill"


def test_packer_command_builds_minimal_argv():
    from demo_native_manifest import packer_command

    cmd = packer_command("/usr/bin/node", "/home/ql/qlmatch-packer/pack.mjs",
                         "/home/ql/qlds-27960/demos", MATCH_ID)
    assert cmd == [
        "/usr/bin/node", "/home/ql/qlmatch-packer/pack.mjs",
        "--dir", "/home/ql/qlds-27960/demos",
        "--match-id", MATCH_ID,
    ]


def test_packer_command_appends_template_and_targets_only_when_set():
    from demo_native_manifest import packer_command

    cmd = packer_command("node", "pack.mjs", "/demos", MATCH_ID, MAP_NAME,
                         name_template="{date}_{map}_{players}",
                         rclone_targets="gdrive:demos,/mnt/archive")
    assert cmd[-4:] == ["--name-template", "{date}_{map}_{players}",
                       "--rclone-targets", "gdrive:demos,/mnt/archive"]
    assert "--name-template" not in packer_command("node", "p", "/d", MATCH_ID, MAP_NAME)


def test_packer_command_omits_map_when_empty():
    # No --map: the packer derives mapname from each POV's own gamestate
    # serverinfo, which is authoritative where a caller-side value is not.
    from demo_native_manifest import packer_command

    assert "--map" not in packer_command("node", "pack.mjs", "/demos", MATCH_ID)
    cmd = packer_command("node", "pack.mjs", "/demos", MATCH_ID, MAP_NAME)
    assert cmd[cmd.index("--map") + 1] == MAP_NAME
