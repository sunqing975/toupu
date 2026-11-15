import io
import stat
import uuid
import zipfile

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.agent.skill_archive import read_zip
from app.agent.skill_packages import load_skill, parse_skill, read_skill_file
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)
BASE = "/api/v1/agent/skill-packages"


def archive(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for path, data in entries:
            z.writestr(path, data)
    return buffer.getvalue()


def test_zip_directory_roundtrip_and_lazy_references():
    name = "zip-" + uuid.uuid4().hex
    content = f"---\nname: {name}\ndescription: ZIP workflow\n---\nRead references/guide.md"
    image = b"\x89PNG\x00binary"
    entries = [
        ("SKILL.md", content),
        ("references/guide.md", "参考资料"),
        ("scripts/check.py", "raise RuntimeError('must never execute')"),
        ("assets/chart.png", image),
    ]
    data = archive([("example/" + p, v) for p, v in entries])
    response = client.post(BASE + "/import", files={"file": ("example.zip", data)})
    assert response.status_code == 201, response.text
    package = response.json()
    endpoint = BASE + "/" + package["id"]
    assert {f["path"] for f in package["files"]} == {p for p, _ in entries}
    assert (
        client.get(endpoint + "/files", params={"path": "references/guide.md"}).json()["content"]
        == "参考资料"
    )
    assert (
        client.get(endpoint + "/files", params={"path": "assets/chart.png"}).json()["content"]
        is None
    )
    download = client.get(endpoint + "/download", params={"path": "assets/chart.png"})
    assert download.content == image
    assert download.headers["x-content-type-options"] == "nosniff"
    assert client.get(endpoint + "/files", params={"path": "../SKILL.md"}).status_code == 422
    assert client.get(endpoint + "/files", params={"path": "missing"}).status_code == 404
    with SessionLocal() as db:
        assert "references/guide.md" in load_skill(db, name)
        assert "read_skill_file" in load_skill(db, name)
        assert read_skill_file(db, name, "references/guide.md") == "参考资料"
    changed = client.patch(endpoint, json={"content": content + "\nUpdated"})
    assert changed.status_code == 200
    assert len(changed.json()["files"]) == 4
    assert client.get(endpoint + "/download", params={"path": "assets/chart.png"}).content == image
    assert client.post(BASE + "/import", files={"file": ("again.zip", data)}).status_code == 409
    client.patch(endpoint, json={"enabled": False})
    with SessionLocal() as db:
        assert read_skill_file(db, name, "references/guide.md") == "技能不存在或已停用"


@pytest.mark.parametrize(
    "entries",
    [
        [("../SKILL.md", "bad")],
        [("/SKILL.md", "bad")],
        [("C:/SKILL.md", "bad")],
        [("a\\SKILL.md", "bad")],
        [("SKILL.md", "x"), ("skill.md", "x")],
        [("SKILL.md", "x"), ("references", "file"), ("references/a.md", "x")],
        [("a/SKILL.md", "x"), ("b/SKILL.md", "x")],
        [("SKILL.md", "x"), ("nested/SKILL.md", "x")],
        [("readme.md", "no entry")],
    ],
)
def test_zip_rejects_unsafe_or_ambiguous_layout(entries):
    with pytest.raises(HTTPException) as error:
        read_zip(archive(entries))
    assert error.value.status_code == 422


def test_zip_limits_links_and_corruption():
    from app.agent import skill_archive

    for data, status in [
        (b"not a zip", 422),
        (b"x" * (skill_archive.MAX_ARCHIVE + 1), 413),
        (archive([("SKILL.md", b"x" * (skill_archive.MAX_FILE + 1))]), 413),
        (archive([(str(i), "") for i in range(513)]), 422),
    ]:
        with pytest.raises(HTTPException) as error:
            read_zip(data)
        assert error.value.status_code == status
    link = zipfile.ZipInfo("SKILL.md")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(HTTPException):
        read_zip(archive([(link, "/etc/passwd")]))
    assert read_zip(archive([("SKILL.md", "entry"), (".DS_Store", "ignored")])) == {
        "SKILL.md": b"entry"
    }


def test_builtin_skill_directory():
    response = client.get("/api/v1/agent/skill-packages")
    assert response.status_code == 200
    names = {row["name"] for row in response.json() if row["builtin"]}
    assert {"toupu-assistant", "portfolio-review"} <= names


def test_invalid_skill_files():
    for content in [
        "plain markdown",
        "---\nname: Bad_Name\ndescription: hi\n---\nbody",
        "---\n[]\n---\nbody",
    ]:
        with pytest.raises(HTTPException):
            parse_skill(content)


def test_import_update_toggle_package_and_lazy_load():
    name = "test-" + uuid.uuid4().hex
    content = f"---\nname: {name}\ndescription: Test workflow\n---\nRead data first."
    response = client.post("/api/v1/agent/skill-packages", json={"content": content})
    assert response.status_code == 201, response.text
    package = response.json()
    assert package["content"] == content
    assert client.post("/api/v1/agent/skill-packages", json={"content": content}).status_code == 409
    from app.agent.skill_packages import catalog_prompt, load_skill
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        assert name in catalog_prompt(db)
        assert load_skill(db, name) == content
    endpoint = f"/api/v1/agent/skill-packages/{package['id']}"
    assert client.patch(endpoint, json={"enabled": False}).status_code == 200
    with SessionLocal() as db:
        assert name not in catalog_prompt(db)
        assert load_skill(db, name) == "技能不存在或已停用"
