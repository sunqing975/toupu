# 投资账户 API：基础 CRUD。账户一旦被账本引用，删除会因外键冲突被拒绝（409）。
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts.models import InvestmentAccount
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])

AccountType = Literal["BROKER", "FUND_PLATFORM", "BANK", "CASH"]
AccountStatus = Literal["ACTIVE", "FROZEN", "CLOSED"]


class AccountIn(BaseModel):
    name: str
    account_type: AccountType
    currency: str = "CNY"
    notes: str | None = None


class AccountPatch(BaseModel):
    name: str | None = None
    status: AccountStatus | None = None
    notes: str | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    account_type: str
    currency: str
    status: str
    notes: str | None


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AccountOut)
def create_account(payload: AccountIn, db: Session = Depends(get_db)) -> InvestmentAccount:
    account = InvestmentAccount(**payload.model_dump())
    db.add(account)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="账户名已存在") from None
    db.refresh(account)
    return account


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)) -> list[InvestmentAccount]:
    return list(db.query(InvestmentAccount).order_by(InvestmentAccount.name))


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: uuid.UUID, db: Session = Depends(get_db)) -> InvestmentAccount:
    account = db.get(InvestmentAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")
    return account


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: uuid.UUID, payload: AccountPatch, db: Session = Depends(get_db)
) -> InvestmentAccount:
    account = db.get(InvestmentAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="账户名已存在") from None
    db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    account = db.get(InvestmentAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")
    try:
        db.delete(account)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="账户已被账本数据引用，不能删除") from None
