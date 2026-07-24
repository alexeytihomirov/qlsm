"""Upload/delete endpoints for a draft workspace's user-hooks/ directory.

These stage LD_PRELOAD .so hooks during instance creation, before an instance
row exists. On instance create, the draft's user-hooks/ is copied into the new
instance (see ui/routes/instance_routes.py) and enabled_hooks is filtered
against what is on disk.
"""
import os

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from werkzeug.utils import secure_filename

from ui.routes.draft_routes import (
    ELF_MAGIC,
    MAX_BINARY_FILE_SIZE,
    _draft_exists,
    _get_draft_base_path,
    _get_draft_user_hooks_path,
    _validate_draft_id,
)
from ui.routes.instance_hooks_routes import _validate_filename

draft_hooks_bp = Blueprint("draft_hooks_api", __name__)


@draft_hooks_bp.route("/<draft_id>/hooks", methods=["POST"])
@jwt_required()
def upload_draft_hook(draft_id):
    if not _validate_draft_id(draft_id):
        return jsonify({"error": {"message": "Invalid draft ID"}}), 400
    if not _draft_exists(draft_id):
        return jsonify({"error": {"message": "Draft not found"}}), 404

    if "file" not in request.files:
        return jsonify({"error": {"message": "No file provided"}}), 400
    upload = request.files["file"]
    if not upload.filename:
        return jsonify({"error": {"message": "No filename"}}), 400

    filename = secure_filename(upload.filename)
    if filename != upload.filename:
        return jsonify({"error": {"message": "filename contains forbidden characters"}}), 400
    error = _validate_filename(filename)
    if error:
        return jsonify({"error": {"message": error}}), 400

    upload.seek(0, 2)
    size = upload.tell()
    upload.seek(0)
    if size == 0:
        return jsonify({"error": {"message": "Empty file"}}), 400
    if size > MAX_BINARY_FILE_SIZE:
        return jsonify({"error": {"message": f"File exceeds {MAX_BINARY_FILE_SIZE} bytes"}}), 400
    if upload.read(4) != ELF_MAGIC:
        return jsonify({"error": {"message": "Not a valid ELF binary"}}), 400
    upload.seek(0)

    hooks_dir = _get_draft_user_hooks_path(draft_id)
    os.makedirs(hooks_dir, exist_ok=True)
    target = os.path.join(hooks_dir, filename)
    # Atomic exclusive create so two concurrent same-name uploads can't race
    # past an os.path.exists() check and silently overwrite each other.
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return jsonify({"error": {"message": f"{filename} already exists"}}), 409
    with os.fdopen(fd, "wb") as handle:
        upload.save(handle)
    os.utime(_get_draft_base_path(draft_id), None)

    return jsonify({"data": {
        "filename": filename,
        "size": os.path.getsize(target),
        "modified": int(os.path.getmtime(target)),
        "enabled": False,
        "order": None,
        "description": "",
    }}), 201


@draft_hooks_bp.route("/<draft_id>/hooks/<filename>", methods=["DELETE"])
@jwt_required()
def delete_draft_hook(draft_id, filename):
    if not _validate_draft_id(draft_id):
        return jsonify({"error": {"message": "Invalid draft ID"}}), 400
    if not _draft_exists(draft_id):
        return jsonify({"error": {"message": "Draft not found"}}), 404
    error = _validate_filename(filename)
    if error:
        return jsonify({"error": {"message": error}}), 400

    target = os.path.join(_get_draft_user_hooks_path(draft_id), filename)
    if not os.path.isfile(target):
        return jsonify({"error": {"message": f"{filename} not found"}}), 404
    os.remove(target)
    os.utime(_get_draft_base_path(draft_id), None)
    return ("", 204)
