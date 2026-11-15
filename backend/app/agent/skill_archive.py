"""Bounded, inert skill directories. Never extract or execute archive paths."""

import base64
import io
import stat
import zipfile
from pathlib import PurePosixPath

from fastapi import HTTPException

MAX_ARCHIVE = 10 * 1024 * 1024
MAX_TOTAL = 20 * 1024 * 1024
MAX_FILE = 5 * 1024 * 1024
MAX_ENTRIES = 512


def safe_path(path: str) -> str:
    if (
        not path
        or len(path) > 512
        or "\\" in path
        or ":" in path
        or any(ord(c) < 32 for c in path)
        or path.startswith("/")
        or any(p in ("", ".", "..") for p in path.split("/"))
    ):
        raise HTTPException(422, "技能文件路径不安全")
    return path


def pack_files(files: dict[str, bytes]) -> dict[str, str]:
    return {path: base64.b64encode(data).decode("ascii") for path, data in files.items()}


def unpack_files(config: dict) -> dict[str, bytes]:
    files = config.get("files")
    if files is None:  # Legacy single-file packages become one-file directories.
        return {"SKILL.md": config.get("content", "").encode("utf-8")}
    return {path: base64.b64decode(data) for path, data in files.items()}


def read_zip(data: bytes) -> dict[str, bytes]:
    if len(data) > MAX_ARCHIVE:
        raise HTTPException(413, "ZIP 不能超过10MiB")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ENTRIES:
                raise HTTPException(422, "ZIP 最多包含512个条目")
            files: dict[str, bytes] = {}
            seen: set[str] = set()
            total = 0
            for entry in entries:
                path = safe_path(entry.filename.rstrip("/") if entry.is_dir() else entry.filename)
                mode = entry.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise HTTPException(422, "ZIP 不允许符号链接或特殊文件")
                if entry.flag_bits & 1:
                    raise HTTPException(422, "不支持加密 ZIP")
                if path.casefold() in seen:
                    raise HTTPException(422, "ZIP 包含重复文件路径")
                seen.add(path.casefold())
                total += entry.file_size
                if entry.file_size > MAX_FILE or total > MAX_TOTAL:
                    raise HTTPException(413, "解压后单文件最多5MiB、总计最多20MiB")
                if entry.is_dir():
                    continue
                if path.startswith("__MACOSX/") or PurePosixPath(path).name == ".DS_Store":
                    continue
                with archive.open(entry) as source:
                    content = source.read(MAX_FILE + 1)
                if len(content) > MAX_FILE:
                    raise HTTPException(413, "技能文件超过5MiB")
                files[path] = content
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, OSError):
        raise HTTPException(422, "ZIP 损坏或压缩格式不受支持") from None
    # Accept a flat archive or one enclosing directory, never silently drop siblings.
    if "SKILL.md" not in files:
        roots = {p.split("/")[0] for p in files}
        if len(roots) == 1 and all("/" in p for p in files):
            files = {p.split("/", 1)[1]: value for p, value in files.items()}
    if "SKILL.md" not in files:
        raise HTTPException(422, "ZIP 必须包含根目录 SKILL.md，或一个包含 SKILL.md 的技能目录")
    if any(p != "SKILL.md" and PurePosixPath(p).name.casefold() == "skill.md" for p in files):
        raise HTTPException(422, "一次仅支持导入一个技能目录")
    paths = {p.casefold() for p in files}
    for path in files:
        if any(
            str(parent).casefold() in paths
            for parent in PurePosixPath(path).parents
            if str(parent) != "."
        ):
            raise HTTPException(422, "ZIP 文件与目录路径冲突")
    return files


def entry_content(files: dict[str, bytes]) -> str:
    try:
        return files["SKILL.md"].decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeDecodeError:
        raise HTTPException(422, "SKILL.md 必须为 UTF-8 文本") from None


def text_content(data: bytes) -> str | None:
    if len(data) > 100_000 or b"\0" in data:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def manifest(files: dict[str, bytes]) -> list[dict]:
    return [
        {"path": path, "size": len(data), "readable": text_content(data) is not None}
        for path, data in sorted(files.items())
    ]
