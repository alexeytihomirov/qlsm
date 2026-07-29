"""Tests for the shared config-path validation/listing/pruning helpers."""

import os
import pytest
from ui.config_path_utils import (
    RESERVED_CONFIG_FOLDER_NAMES,
    MAX_CONFIG_FOLDER_DEPTH,
    MAX_CONFIG_FILE_DEPTH,
    validate_path_segment,
    validate_relative_config_path,
    validate_config_folder_path,
    expand_with_ancestors,
    list_folders_recursive,
    prune_orphan_folders,
)

ALLOWED_EXT = {'.cfg', '.txt', '.ent'}


class TestConstants:
    def test_max_folder_depth_is_three(self):
        assert MAX_CONFIG_FOLDER_DEPTH == 3

    def test_max_file_depth_is_four(self):
        assert MAX_CONFIG_FILE_DEPTH == 4

    def test_reserved_names(self):
        assert RESERVED_CONFIG_FOLDER_NAMES == {'scripts', 'factories', 'user-hooks'}


class TestValidatePathSegment:
    def test_accepts_safe_name(self):
        assert validate_path_segment('foo.cfg', ALLOWED_EXT) is None

    def test_rejects_slash(self):
        assert validate_path_segment('a/b', ALLOWED_EXT) is not None

    def test_rejects_dotdot(self):
        assert validate_path_segment('..', ALLOWED_EXT) is not None

    def test_folder_segment_skips_extension_check(self):
        assert validate_path_segment('custom_entities', None) is None


class TestValidateRelativeConfigPath:
    def test_accepts_flat_file(self):
        assert validate_relative_config_path('server.cfg', ALLOWED_EXT) is None

    def test_accepts_three_folders_deep(self):
        assert validate_relative_config_path('a/b/c/file.cfg', ALLOWED_EXT) is None

    def test_rejects_four_folders_deep(self):
        err = validate_relative_config_path('a/b/c/d/file.cfg', ALLOWED_EXT)
        assert err is not None
        assert 'deep' in err.lower()

    def test_rejects_reserved_name_at_any_depth(self):
        err = validate_relative_config_path('a/scripts/file.cfg', ALLOWED_EXT)
        assert err is not None
        assert 'reserved' in err.lower()

    def test_rejects_leading_slash(self):
        assert validate_relative_config_path('/server.cfg', ALLOWED_EXT) is not None

    def test_custom_max_depth_still_honored(self):
        err = validate_relative_config_path('a/b/c.cfg', ALLOWED_EXT, max_depth=2)
        assert err is not None


class TestValidateConfigFolderPath:
    def test_accepts_three_levels(self):
        assert validate_config_folder_path('a/b/c') is None

    def test_rejects_four_levels(self):
        assert validate_config_folder_path('a/b/c/d') is not None

    def test_rejects_reserved_name_at_any_segment(self):
        assert validate_config_folder_path('a/factories') is not None

    def test_rejects_invalid_chars(self):
        assert validate_config_folder_path('a/b*d') is not None


class TestExpandWithAncestors:
    def test_expands_each_path_to_all_ancestors(self):
        result = expand_with_ancestors(['a/b/c'])
        assert result == {'a', 'a/b', 'a/b/c'}

    def test_handles_flat_paths(self):
        assert expand_with_ancestors(['a']) == {'a'}

    def test_handles_multiple_paths(self):
        result = expand_with_ancestors(['a/b', 'x'])
        assert result == {'a', 'a/b', 'x'}


class TestListFoldersRecursive:
    def test_lists_nested_folders(self, tmp_path):
        base = tmp_path / 'instance'
        (base / 'a' / 'b' / 'c').mkdir(parents=True)
        result = set(list_folders_recursive(str(base)))
        assert result == {'a', 'a/b', 'a/b/c'}

    def test_excludes_reserved_dirs(self, tmp_path):
        base = tmp_path / 'instance'
        (base / 'scripts').mkdir(parents=True)
        (base / 'keep').mkdir(parents=True)
        result = set(list_folders_recursive(str(base)))
        assert result == {'keep'}

    def test_stops_at_max_depth(self, tmp_path):
        base = tmp_path / 'instance'
        (base / 'a' / 'b' / 'c' / 'd').mkdir(parents=True)
        result = set(list_folders_recursive(str(base), max_depth=3))
        assert result == {'a', 'a/b', 'a/b/c'}

    def test_missing_dir_returns_empty(self, tmp_path):
        assert list_folders_recursive(str(tmp_path / 'nope')) == []


class TestPruneOrphanFolders:
    def test_removes_empty_folder_not_desired(self, tmp_path):
        base = tmp_path / 'instance'
        (base / 'gone').mkdir(parents=True)
        prune_orphan_folders(str(base), desired_folders=set())
        assert not (base / 'gone').exists()

    def test_keeps_desired_folder_and_its_ancestors(self, tmp_path):
        base = tmp_path / 'instance'
        (base / 'a' / 'b' / 'c').mkdir(parents=True)
        prune_orphan_folders(str(base), desired_folders={'a/b/c'})
        assert (base / 'a').exists()
        assert (base / 'a' / 'b').exists()
        assert (base / 'a' / 'b' / 'c').exists()

    def test_prunes_deepest_undesired_branch_but_keeps_desired_sibling(self, tmp_path):
        base = tmp_path / 'instance'
        (base / 'a' / 'b' / 'keep').mkdir(parents=True)
        (base / 'a' / 'b' / 'gone').mkdir(parents=True)
        prune_orphan_folders(str(base), desired_folders={'a/b/keep'})
        assert (base / 'a' / 'b' / 'keep').exists()
        assert not (base / 'a' / 'b' / 'gone').exists()

    def test_leaves_non_empty_orphan_alone(self, tmp_path):
        base = tmp_path / 'instance'
        folder = base / 'mystery'
        folder.mkdir(parents=True)
        (folder / 'unmanaged.README').write_text('keep me')
        prune_orphan_folders(str(base), desired_folders=set())
        assert folder.exists()
        assert (folder / 'unmanaged.README').exists()
