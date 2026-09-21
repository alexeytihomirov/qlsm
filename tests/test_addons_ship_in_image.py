"""`addons/` must reach the Docker image.

This exists because of a real miss on 2026-09-14: `addons/` was un-ignored in
.gitignore but not in .dockerignore, so the addon system deployed without any
addons in it. Everything looked healthy -- the routes answered, the migration
ran -- and the only symptom was that no addon appeared. Cheap test, expensive
failure mode.

.dockerignore here is a strict allowlist (`*` first, then `!` lines), and this
checks the pairing rather than reimplementing Docker's matching rules.
"""
import os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _lines(filename):
    with open(os.path.join(REPO_ROOT, filename), encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]


def test_dockerignore_is_still_a_strict_allowlist():
    """If this ever stops being true the other assertions mean nothing."""
    assert _lines('.dockerignore')[0] == '*'


def test_addons_directory_is_unignored_for_the_image():
    lines = _lines('.dockerignore')
    assert '!addons/' in lines, 'addons/ would be absent from the Docker image'
    assert '!addons/**' in lines, 'addon files would be absent from the Docker image'


def test_addons_directory_is_unignored_for_git():
    lines = _lines('.gitignore')
    assert '!addons/' in lines
    assert '!addons/**' in lines


def test_the_bundled_addons_actually_exist():
    """Guards the other direction: the allowlist entries are not stale.

    Only demo-management ships bundled (baked into the image). The other
    addons (telemetry-relay, demo-stream, qlmatch-packer) live in the
    separate qlsm-extra repo and are installed by the operator onto the
    ADDON_PACKAGES_DIR volume instead -- see qlsm-extra/README.md."""
    addons_dir = os.path.join(REPO_ROOT, 'addons')
    assert os.path.isdir(addons_dir)
    shipped = {
        name for name in os.listdir(addons_dir)
        if os.path.isfile(os.path.join(addons_dir, name, 'qlsm-addon.json'))
    }
    assert {'demo-management'} <= shipped
    assert not ({'telemetry-relay', 'demo-stream', 'qlmatch-packer'} & shipped), (
        'these addons moved to the separate qlsm-extra repo and must not be bundled'
    )
