import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.agent.skill_packages import parse_skill
from app.main import app

client = TestClient(app)


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
