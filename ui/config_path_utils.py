"""Shared validation, listing, and pruning helpers for nested config/plugin
folders. Used by ui/routes/instance_routes.py and ui/routes/preset_api_routes.py
to avoid duplicating path-depth and reserved-name logic in both files."""

import os
import re

RESERVED_CONFIG_FOLDER_NAMES = {'scripts', 'factories', 'user-hooks'}
MAX_CONFIG_FOLDER_DEPTH = 3  # pure folder paths, e.g. a/b/c
MAX_CONFIG_FILE_DEPTH = 4    # 3 folders + filename, e.g. a/b/c/file.cfg

_FOLDER_NAME_RE = re.compile(r'^[A-Za-z0-9._-]+$')


def validate_path_segment(name, allowed_extensions=None):
    """Validate a single path segment (file or folder name).

    Returns an error message, or None if valid. When allowed_extensions is
    None, treat name as a folder segment and skip the extension check.
    """
    if not isinstance(name, str) or not name:
        return "Invalid name"
    if '/' in name or '\\' in name or '..' in name or name.startswith('.'):
        return f"Invalid name: {name}"
    if not _FOLDER_NAME_RE.match(name):
        return f"Invalid characters in: {name}"
    if len(name) > 64:
        return f"Name too long: {name}"
    if allowed_extensions is not None:
        ext = os.path.splitext(name)[1].lower()
        if ext not in allowed_extensions:
            return f"Disallowed extension {ext} for {name}"
    return None


def validate_relative_config_path(path, allowed_extensions, max_depth=MAX_CONFIG_FILE_DEPTH):
    """Validate a relative file path. Each segment is validated, depth is
    capped, and every folder segment (all but the last) is checked against
    RESERVED_CONFIG_FOLDER_NAMES."""
    if not isinstance(path, str) or not path:
        return "Invalid path"
    if path.startswith('/') or path.endswith('/'):
        return f"Invalid path: {path}"
    segments = path.split('/')
    if len(segments) > max_depth:
        return f"Path too deep: {path} (max depth {max_depth})"
    for i, segment in enumerate(segments):
        is_last = (i == len(segments) - 1)
        err = validate_path_segment(segment, allowed_extensions if is_last else None)
        if err:
            return err
        if not is_last and segment.lower() in RESERVED_CONFIG_FOLDER_NAMES:
            return f"Reserved folder name: {segment}"
    return None


def validate_config_folder_path(path, max_depth=MAX_CONFIG_FOLDER_DEPTH):
    """Validate a pure folder path (e.g. a config_folders entry). No file
    extension anywhere; every segment is checked against reserved names."""
    if not isinstance(path, str) or not path:
        return "Invalid path"
    if path.startswith('/') or path.endswith('/'):
        return f"Invalid path: {path}"
    segments = path.split('/')
    if len(segments) > max_depth:
        return f"Path too deep: {path} (max depth {max_depth})"
    for segment in segments:
        err = validate_path_segment(segment, None)
        if err:
            return err
        if segment.lower() in RESERVED_CONFIG_FOLDER_NAMES:
            return f"Reserved folder name: {segment}"
    return None


def expand_with_ancestors(paths):
    """Given relative folder paths, return a set containing each path and
    all of its ancestor directories (e.g. 'a/b/c' expands to
    {'a', 'a/b', 'a/b/c'})."""
    expanded = set()
    for path in paths:
        parts = path.split('/')
        for i in range(1, len(parts) + 1):
            expanded.add('/'.join(parts[:i]))
    return expanded


def list_folders_recursive(base_dir, reserved_names=RESERVED_CONFIG_FOLDER_NAMES,
                            max_depth=MAX_CONFIG_FOLDER_DEPTH):
    """Return all managed folder relative paths under base_dir (any depth up
    to max_depth), excluding reserved dirs."""
    if not os.path.isdir(base_dir):
        return []
    found = []
    for root, dirs, _files in os.walk(base_dir):
        rel_root = os.path.relpath(root, base_dir)
        depth = 0 if rel_root == '.' else len(rel_root.split(os.sep))
        dirs[:] = sorted(d for d in dirs if d.lower() not in reserved_names)
        for d in dirs:
            rel_path = d if rel_root == '.' else f"{rel_root}/{d}".replace(os.sep, '/')
            found.append(rel_path)
        if depth + 1 >= max_depth:
            dirs[:] = []
    return found


def prune_orphan_folders(base_dir, desired_folders, reserved_names=RESERVED_CONFIG_FOLDER_NAMES):
    """Remove empty managed folders not in desired_folders (or an ancestor of
    one), deepest first, leaving non-empty folders untouched."""
    keep = expand_with_ancestors(desired_folders)
    existing = list_folders_recursive(base_dir, reserved_names)
    for rel_path in sorted(existing, key=lambda p: p.count('/'), reverse=True):
        if rel_path in keep:
            continue
        folder_path = os.path.join(base_dir, *rel_path.split('/'))
        try:
            os.rmdir(folder_path)
        except OSError:
            pass
