"""`addons/` must reach the Docker image.

Un-ignoring a directory in .gitignore but not in .dockerignore is silent: the
files are committed and pushed, the routes still answer, the migration still
runs, and the only symptom is that nothing appears. Cheap test, expensive
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


def test_the_allowlist_is_not_stale():
    """Guards the other direction: the allowlist entries still cover something.

    No feature addon ships in the image; an operator installs one onto the
    ADDON_PACKAGES_DIR volume. What addons/ still has to reach the image is
    its documentation and the reference examples an operator copies onto that
    volume to try them, so the allowlist entries are still doing work."""
    addons_dir = os.path.join(REPO_ROOT, 'addons')
    assert os.path.isdir(addons_dir)
    assert os.path.isfile(os.path.join(addons_dir, 'README.md'))
    assert os.path.isdir(os.path.join(addons_dir, '_examples'))


def test_no_feature_addon_is_bundled():
    """A bundled addon would be a feature QLSM cannot be shipped without."""
    addons_dir = os.path.join(REPO_ROOT, 'addons')
    shipped = {
        name for name in os.listdir(addons_dir)
        if os.path.isfile(os.path.join(addons_dir, name, 'qlsm-addon.json'))
    }
    assert shipped == set(), (
        f'{sorted(shipped)} would ship inside the image; addons belong in a '
        f'repository the operator installs from, not in core'
    )
