"""SKILL.md instruction packages, separate from callable business tools."""

import re
import uuid
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.models import AgentSkill
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/agent/skill-packages", tags=["skill-packages"])
ROOT = Path(__file__).resolve().parents[2] / "skills"


def parse_skill(content: str) -> tuple[str, str, str]:
    if len(content) > 100_000 or not content.startswith("---\n"):
        raise HTTPException(422, "需要带 YAML frontmatter 的 SKILL.md（最大 100KB）")
    parts = content.split("---", 2)
    if len(parts) != 3:
        raise HTTPException(422, "SKILL.md frontmatter 缺少结束标记")
    try:
        metadata = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        raise HTTPException(422, "SKILL.md YAML 格式错误") from None
    if not isinstance(metadata, dict):
        raise HTTPException(422, "SKILL.md 元数据必须为对象")
    name, description = metadata.get("name"), metadata.get("description")
    if (
        not isinstance(name, str)
        or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
        or len(name) > 64
    ):
        raise HTTPException(422, "name 必须为小写字母、数字和连字符，最长64字符")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise HTTPException(422, "description 必填且最长1024字符")
    if len(parts) != 3 or not parts[2].strip():
        raise HTTPException(422, "SKILL.md 正文不能为空")
    return name, description, parts[2].strip()


def seed(db: Session) -> None:
    for path in sorted(ROOT.glob("*/SKILL.md")):
        content = path.read_text()
        name, description, _ = parse_skill(content)
        if db.scalar(select(AgentSkill).where(AgentSkill.key == "package:" + name)) is None:
            db.add(
                AgentSkill(
                    key="package:" + name,
                    name=name,
                    description=description,
                    category="instruction",
                    builtin=True,
                    enabled=True,
                    config={"content": content},
                )
            )
    db.commit()


def packages(db: Session) -> list[AgentSkill]:
    seed(db)
    return list(db.scalars(select(AgentSkill).where(AgentSkill.category == "instruction")))


def out(row: AgentSkill) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description,
        "enabled": row.enabled,
        "builtin": row.builtin,
        "content": (row.config or {}).get("content", ""),
    }


class PackageIn(BaseModel):
    content: str = Field(max_length=100_000)


class PackagePatch(BaseModel):
    content: str | None = Field(default=None, max_length=100_000)
    enabled: bool | None = None


@router.get("")
def listing(db: Session = Depends(get_db)) -> list[dict]:
    return [out(row) for row in packages(db)]


@router.post("", status_code=201)
def install(payload: PackageIn, db: Session = Depends(get_db)) -> dict:
    name, description, _ = parse_skill(payload.content)
    seed(db)
    if db.scalar(select(AgentSkill).where(AgentSkill.key == "package:" + name)):
        raise HTTPException(409, "同名技能已存在，请编辑现有技能")
    row = AgentSkill(
        key="package:" + name,
        name=name,
        description=description,
        category="instruction",
        builtin=False,
        enabled=True,
        config={"content": payload.content},
    )
    db.add(row)
    db.commit()
    return out(row)


@router.patch("/{package_id}")
def update(package_id: uuid.UUID, payload: PackagePatch, db: Session = Depends(get_db)) -> dict:
    row = db.get(AgentSkill, package_id)
    if row is None or row.category != "instruction":
        raise HTTPException(404, "技能不存在")
    if payload.content is not None:
        name, description, _ = parse_skill(payload.content)
        if name != row.name:
            raise HTTPException(422, "修改正文时不能更改技能 name")
        row.description = description
        row.config = {"content": payload.content}
    if payload.enabled is not None:
        row.enabled = payload.enabled
    db.commit()
    return out(row)


def catalog_prompt(db: Session) -> str:
    rows = [r for r in packages(db) if r.enabled]
    return "\n可用 SKILL.md 技能（需要时先调用 load_skill 加载步骤）：\n" + "\n".join(
        f"- {r.name}: {r.description}" for r in rows
    )


def load_skill(db: Session, name: str) -> str:
    row = db.scalar(select(AgentSkill).where(AgentSkill.key == "package:" + name))
    if row is None or not row.enabled or row.category != "instruction":
        return "技能不存在或已停用"
    return (row.config or {}).get("content", "")


LOAD_SCHEMA = {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": "按名称加载 SKILL.md 完整指令，再遵循其工作步骤调用业务工具。",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
}
