# M4 导入 API：上传（multipart CSV/Excel）、批次列表/详情/原始行预览、人工确认、取消。
# 导入阶段绝不直接写正式账本；过账由 confirm 端点经 PostingService 完成（agent.md §7）。
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.errors import BusinessError
from app.db.session import get_db
from app.imports.models import ImportBatch, ImportFieldMapping, ImportRecord, ImportTemplate
from app.imports.service import TEMPLATE_CODE, cancel_batch, confirm_batch, create_batch

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])


class BatchOut(BaseModel):
    id: uuid.UUID
    template_code: str
    file_name: str
    file_hash: str
    status: str
    row_count: int
    error_count: int
    duplicate_count: int
    memo: str | None
    created_at: datetime
    confirmed_at: datetime | None


class RowError(BaseModel):
    row_no: int
    field: str
    message: str


class RecordOut(BaseModel):
    id: uuid.UUID
    row_no: int
    status: str
    dedup_key: str | None
    normalized: dict[str, Any] | None
    raw: dict[str, Any]
    errors: list[RowError]


class BatchDetailOut(BatchOut):
    raw_headers: list[str] | None
    records: list[RecordOut]


class TemplateOut(BaseModel):
    code: str
    name: str
    description: str | None
    columns: list[str]


def _to_batch_out(db: Session, batch: ImportBatch) -> BatchOut:
    template = db.get(ImportTemplate, batch.template_id)
    return BatchOut(
        id=batch.id,
        template_code=template.code if template else "",
        file_name=batch.file_name,
        file_hash=batch.file_hash,
        status=batch.status,
        row_count=batch.row_count,
        error_count=batch.error_count,
        duplicate_count=batch.duplicate_count,
        memo=batch.memo,
        created_at=batch.created_at,
        confirmed_at=batch.confirmed_at,
    )


def _to_detail_out(db: Session, batch: ImportBatch) -> BatchDetailOut:
    base = _to_batch_out(db, batch)
    records = (
        db.query(ImportRecord).filter_by(batch_id=batch.id).order_by(ImportRecord.row_no).all()
    )
    return BatchDetailOut(
        **base.model_dump(),
        raw_headers=batch.raw_headers,
        records=[
            RecordOut(
                id=r.id,
                row_no=r.row_no,
                status=r.status,
                dedup_key=r.dedup_key,
                normalized=r.normalized,
                raw=r.raw,
                errors=[RowError(**e) for e in (r.errors or [])],
            )
            for r in records
        ],
    )


def _get_batch(db: Session, batch_id: uuid.UUID) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="导入批次不存在")
    return batch


@router.get("/template", response_model=TemplateOut)
def get_template(db: Session = Depends(get_db)) -> TemplateOut:
    """返回内置期初资产模板与列清单（供前端展示上传说明）。"""
    template = db.query(ImportTemplate).filter_by(code=TEMPLATE_CODE).one_or_none()
    if template is None:
        raise BusinessError("内置导入模板未初始化，请确认迁移已执行")
    mappings = (
        db.query(ImportFieldMapping)
        .filter_by(template_id=template.id)
        .order_by(ImportFieldMapping.source_column)
        .all()
    )
    return TemplateOut(
        code=template.code,
        name=template.name,
        description=template.description,
        columns=[m.source_column for m in mappings],
    )


@router.post("/batches", response_model=BatchDetailOut, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = File(...),
    memo: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> BatchDetailOut:
    template = db.query(ImportTemplate).filter_by(code=TEMPLATE_CODE).one_or_none()
    if template is None:
        raise BusinessError("内置导入模板未初始化，请确认迁移已执行")
    content = await file.read()
    try:
        batch = create_batch(db, template, file.filename or "upload.csv", content, memo)
    except BusinessError:
        db.rollback()
        raise
    return _to_detail_out(db, batch)


@router.get("/batches", response_model=list[BatchOut])
def list_batches(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[BatchOut]:
    q = db.query(ImportBatch)
    if status_filter:
        q = q.filter(ImportBatch.status == status_filter)
    return [_to_batch_out(db, b) for b in q.order_by(ImportBatch.created_at.desc()).limit(100)]


@router.get("/batches/{batch_id}", response_model=BatchDetailOut)
def get_batch(batch_id: uuid.UUID, db: Session = Depends(get_db)) -> BatchDetailOut:
    return _to_detail_out(db, _get_batch(db, batch_id))


@router.post("/batches/{batch_id}/confirm", response_model=BatchDetailOut)
def confirm(batch_id: uuid.UUID, db: Session = Depends(get_db)) -> BatchDetailOut:
    batch = confirm_batch(db, _get_batch(db, batch_id))
    return _to_detail_out(db, batch)


@router.post("/batches/{batch_id}/cancel", response_model=BatchDetailOut)
def cancel(batch_id: uuid.UUID, db: Session = Depends(get_db)) -> BatchDetailOut:
    batch = cancel_batch(db, _get_batch(db, batch_id))
    return _to_detail_out(db, batch)
