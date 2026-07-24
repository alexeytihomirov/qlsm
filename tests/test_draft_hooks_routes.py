"""Tests for draft user-hooks upload/delete API routes."""
import io
import os

import pytest

from tests.helpers import auth_headers

ELF = b"\x7fELF" + b"\x00" * 64


@pytest.fixture
def headers(app):
    return auth_headers(app, "u")


@pytest.fixture
def preset_with_scripts(tmp_path):
    scripts_dir = tmp_path / "configs" / "presets" / "default" / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "balance.py").write_text("# balance\n")
    return tmp_path


@pytest.fixture
def draft_id(client, headers, preset_with_scripts, monkeypatch):
    """Create a draft seeded from the default preset; return its id."""
    monkeypatch.setattr(
        "ui.routes.draft_routes.CONFIGS_BASE", str(preset_with_scripts / "configs")
    )
    resp = client.post(
        "/api/drafts/", json={"source": "preset", "preset": "default"}, headers=headers
    )
    assert resp.status_code == 201
    return resp.get_json()["data"]["draft_id"]


def _upload(client, headers, draft_id, filename, content):
    return client.post(
        f"/api/drafts/{draft_id}/hooks",
        data={"file": (io.BytesIO(content), filename)},
        headers=headers,
        content_type="multipart/form-data",
    )


def _user_hooks_path(app, draft_id, filename):
    return os.path.join(
        app.config["DRAFTS_BASE"], draft_id, "user-hooks", filename
    )


def test_upload_writes_file_and_returns_metadata(client, headers, draft_id, app):
    res = _upload(client, headers, draft_id, "alpha.so", ELF)
    assert res.status_code == 201
    body = res.get_json()["data"]
    assert body["filename"] == "alpha.so"
    assert body["enabled"] is False
    assert body["order"] is None
    assert body["description"] == ""
    assert body["size"] == len(ELF)
    assert os.path.isfile(_user_hooks_path(app, draft_id, "alpha.so"))


def test_upload_rejects_duplicate(client, headers, draft_id):
    _upload(client, headers, draft_id, "dup.so", ELF)
    res = _upload(client, headers, draft_id, "dup.so", ELF)
    assert res.status_code == 409


def test_upload_rejects_non_so(client, headers, draft_id):
    assert _upload(client, headers, draft_id, "bad.txt", ELF).status_code == 400


def test_upload_rejects_non_elf(client, headers, draft_id):
    assert _upload(client, headers, draft_id, "bad.so", b"NOTELF").status_code == 400


def test_upload_rejects_reserved_name(client, headers, draft_id):
    res = _upload(client, headers, draft_id, "force_rate.so", ELF)
    assert res.status_code == 400
    assert "reserved" in res.get_json()["error"]["message"].lower()


def test_upload_rejects_path_traversal(client, headers, draft_id):
    assert _upload(client, headers, draft_id, "../escape.so", ELF).status_code == 400


def test_upload_rejects_empty_file(client, headers, draft_id):
    assert _upload(client, headers, draft_id, "empty.so", b"").status_code == 400


def test_upload_rejects_oversize(client, headers, draft_id):
    from ui.routes.draft_routes import MAX_BINARY_FILE_SIZE
    big = b"\x7fELF" + b"\x00" * MAX_BINARY_FILE_SIZE
    assert _upload(client, headers, draft_id, "big.so", big).status_code == 400


def test_upload_bad_draft_id_400(client, headers):
    assert _upload(client, headers, "not-a-uuid", "a.so", ELF).status_code == 400


def test_upload_missing_draft_404(client, headers):
    import uuid
    res = _upload(client, headers, str(uuid.uuid4()), "a.so", ELF)
    assert res.status_code == 404


def test_upload_requires_auth(client, draft_id):
    res = client.post(
        f"/api/drafts/{draft_id}/hooks",
        data={"file": (io.BytesIO(ELF), "a.so")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 401


def test_delete_removes_file(client, headers, draft_id, app):
    _upload(client, headers, draft_id, "gone.so", ELF)
    res = client.delete(f"/api/drafts/{draft_id}/hooks/gone.so", headers=headers)
    assert res.status_code == 204
    assert not os.path.isfile(_user_hooks_path(app, draft_id, "gone.so"))


def test_delete_missing_file_404(client, headers, draft_id):
    res = client.delete(f"/api/drafts/{draft_id}/hooks/nope.so", headers=headers)
    assert res.status_code == 404


def test_delete_bad_draft_id_400(client, headers):
    res = client.delete("/api/drafts/not-a-uuid/hooks/a.so", headers=headers)
    assert res.status_code == 400
