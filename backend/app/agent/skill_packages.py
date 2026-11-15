"""SKILL.md instruction packages, separate from callable business tools."""

import hashlib
import json
import re
import uuid
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.models import AgentSkill
from app.agent.skill_archive import (
    MAX_ARCHIVE,
    entry_content,
    manifest,
    pack_files,
    read_zip,
    safe_path,
    text_content,
    unpack_files,
)
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/agent/skill-packages", tags=["skill-packages"])
ROOT = Path(__file__).resolve().parents[2] / "skills"


def parse_skill(content: str) -> tuple[str, str, str]:
    if len(content.encode("utf-8")) > 100_000 or not content.startswith("---\n"):
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
                    config={
                        "content": content,
                        "files": pack_files(
                            {
                                str(p.relative_to(path.parent)): p.read_bytes()
                                for p in path.parent.rglob("*")
                                if p.is_file() and not p.is_symlink()
                            }
                        ),
                    },
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
        "content": entry_content(unpack_files(row.config or {})),
        "files": manifest(unpack_files(row.config or {})),
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
    return install_files(db, {"SKILL.md": payload.content.encode("utf-8")})


def install_files(db: Session, files: dict[str, bytes]) -> dict:
    content = entry_content(files)
    name, description, _ = parse_skill(content)
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
        config={"content": content, "files": pack_files(files)},
    )
    db.add(row)
    db.commit()
    return out(row)


@router.post("/import", status_code=201)
async def import_zip(file: UploadFile, db: Session = Depends(get_db)) -> dict:
    try:
        data = await file.read(MAX_ARCHIVE + 1)
    finally:
        await file.close()
    return install_files(db, read_zip(data))


@router.get("/{package_id}/files")
def file_detail(package_id: uuid.UUID, path: str, db: Session = Depends(get_db)) -> dict:
    row = db.get(AgentSkill, package_id)
    if row is None or row.category != "instruction":
        raise HTTPException(404, "技能不存在")
    data = unpack_files(row.config or {}).get(safe_path(path))
    if data is None:
        raise HTTPException(404, "技能文件不存在")
    return {"path": path, "size": len(data), "content": text_content(data)}


@router.get("/{package_id}/download")
def download_file(package_id: uuid.UUID, path: str, db: Session = Depends(get_db)) -> Response:
    row = db.get(AgentSkill, package_id)
    if row is None or row.category != "instruction":
        raise HTTPException(404, "技能不存在")
    data = unpack_files(row.config or {}).get(safe_path(path))
    if data is None:
        raise HTTPException(404, "技能文件不存在")
    return Response(
        data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment", "X-Content-Type-Options": "nosniff"},
    )


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
        files = unpack_files(row.config or {})
        files["SKILL.md"] = payload.content.encode("utf-8")
        row.config = {**(row.config or {}), "content": payload.content, "files": pack_files(files)}
    if payload.enabled is not None:
        row.enabled = payload.enabled
    db.commit()
    return out(row)


def package_versions(db: Session, allowed: set[str]) -> dict[str, str]:
    return {
        r.key: hashlib.sha256(json.dumps(r.config or {}, sort_keys=True).encode()).hexdigest()
        for r in packages(db)
        if r.enabled and r.key in allowed
    }


def catalog_prompt(db: Session, allowed: set[str] | None = None) -> str:
    rows = [r for r in packages(db) if r.enabled and (allowed is None or r.key in allowed)]
    return "\n可用 SKILL.md 技能（需要时先调用 load_skill 加载步骤）：\n" + "\n".join(
        f"- {r.name}: {r.description}" for r in rows
    )


def load_skill(db: Session, name: str) -> str:
    row = db.scalar(select(AgentSkill).where(AgentSkill.key == "package:" + name))
    if row is None or not row.enabled or row.category != "instruction":
        return "技能不存在或已停用"
    files = unpack_files(row.config or {})
    content = entry_content(files)
    if len(files) == 1:
        return content
    return (
        content
        + "\n\n技能目录（通过 read_skill_file(name, path) 按需读取；脚本仅供阅读，不执行）：\n"
        + "\n".join(f"- {item['path']} ({item['size']} bytes)" for item in manifest(files))
    )


def read_skill_file(db: Session, name: str, path: str) -> str:
    row = db.scalar(select(AgentSkill).where(AgentSkill.key == "package:" + name))
    if row is None or not row.enabled or row.category != "instruction":
        return "技能不存在或已停用"
    try:
        data = unpack_files(row.config or {}).get(safe_path(path))
    except HTTPException:
        return "技能文件路径不安全"
    if data is None:
        return "技能文件不存在"
    return text_content(data) or "文件为二进制、空文件或超过100KB，请在技能管理页下载查看"


READ_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_skill_file",
        "description": "读取技能目录中的 UTF-8 引用文件或脚本源码（不执行），path 相对技能根目录。",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "path": {"type": "string"}},
            "required": ["name", "path"],
        },
    },
}


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
