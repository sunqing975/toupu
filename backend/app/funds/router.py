# 场外基金 API（M3）：申请（申购/赎回/红利再投资/现金分红）、确认、失败、详情。
#
# 生命周期见 docs/ledger-rules.md §15。基金交易与证券交易分离：证券走
# /api/v1/transactions（成交明细），基金走本模块（申请 + 确认结果）。
# 过账/冲正/取消复用交易模块的通用端点（/api/v1/transactions/{id}/post|reverse）。
#
# 规则依据 agent.md：金额一律 Decimal，禁止 float；已过账数据不可变，只能冲正；
# Agent 不直接写账本；确认数据到达前不得过账、不得增减份额。
import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Literal, get_args

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.models import InvestmentAccount
from app.audit import record_audit
from app.core.errors import BusinessError
from app.db.session import get_db
from app.funds.models import FundConfirmation, FundOrderDetail
from app.instruments.models import Instrument
from app.transactions.models import InvestmentTransaction
from app.transactions.router import EntryOut, _entry_to_out

router = APIRouter(prefix="/api/v1/funds", tags=["funds"])

FundTxnType = Literal[
    "FUND_SUBSCRIBE",
    "FUND_REDEEM",
    "CASH_DIVIDEND",
    "DIVIDEND_REINVEST",
]
# 需要两段式确认的交易类型
TWO_STAGE_TYPES = ("FUND_SUBSCRIBE", "FUND_REDEEM", "DIVIDEND_REINVEST")


class FundOrderIn(BaseModel):
    transaction_type: FundTxnType
    account_id: uuid.UUID
    instrument_id: uuid.UUID
    business_date: date
    platform: str = Field(default="default", max_length=50)
    # 申购：实际扣款总额（含申购费，必填）；现金分红：到账金额（必填）
    apply_amount: Decimal | None = Field(default=None, gt=0)
    # 赎回：申请赎回份额（必填）；红利再投资：预计份额（可空）
    apply_shares: Decimal | None = Field(default=None, gt=0)
    expected_fee: Decimal | None = Field(default=None, ge=0)
    memo: str | None = None
    idempotency_key: str | None = None

    @model_validator(mode="after")
    def check_shape(self) -> "FundOrderIn":
        if (
            self.transaction_type in ("FUND_SUBSCRIBE", "CASH_DIVIDEND")
            and self.apply_amount is None
        ):
            raise ValueError("申购与现金分红必须指定申请金额 apply_amount")
        if self.transaction_type == "FUND_REDEEM" and self.apply_shares is None:
            raise ValueError("赎回必须指定申请份额 apply_shares")
        return self


class FundConfirmationIn(BaseModel):
    confirmation_date: date
    nav: Decimal = Field(gt=0)
    confirmed_shares: Decimal = Field(gt=0)
    confirmed_amount: Decimal = Field(gt=0)
    fee_amount: Decimal = Field(default=Decimal(0), ge=0)
    raw: dict[str, Any] | None = None


class FundOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    instrument_id: uuid.UUID
    transaction_type: str
    status: str
    confirmation_status: str | None
    business_date: date
    confirmation_date: date | None = None
    currency: str
    total_amount: Decimal | None
    memo: str | None
    platform: str
    apply_amount: Decimal | None
    apply_shares: Decimal | None
    expected_fee: Decimal | None


class FundConfirmationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    confirmation_date: date
    nav: Decimal
    confirmed_shares: Decimal
    confirmed_amount: Decimal
    fee_amount: Decimal


class FundOrderDetailOut(FundOrderOut):
    confirmation: FundConfirmationOut | None = None
    entry: EntryOut | None = None


def _to_out(db: Session, txn: InvestmentTransaction, order: FundOrderDetail) -> FundOrderDetailOut:
    out = FundOrderDetailOut(
        id=txn.id,
        account_id=txn.account_id,
        instrument_id=txn.instrument_id,  # type: ignore[arg-type]
        transaction_type=txn.transaction_type,
        status=txn.status,
        confirmation_status=txn.confirmation_status,
        business_date=txn.business_date,
        currency=txn.currency,
        total_amount=txn.total_amount,
        memo=txn.memo,
        platform=order.platform,
        apply_amount=order.apply_amount,
        apply_shares=order.apply_shares,
        expected_fee=order.expected_fee,
    )
    conf = db.query(FundConfirmation).filter_by(transaction_id=txn.id).one_or_none()
    if conf is not None:
        out.confirmation = FundConfirmationOut.model_validate(conf, from_attributes=True)
    from app.ledger.models import JournalEntry

    out.entry = _entry_to_out(
        db, db.query(JournalEntry).filter_by(transaction_id=txn.id).one_or_none()
    )
    return out


def _get(db: Session, order_id: uuid.UUID) -> tuple[InvestmentTransaction, FundOrderDetail]:
    order = db.query(FundOrderDetail).filter_by(transaction_id=order_id).one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="基金申请不存在")
    txn = db.get(InvestmentTransaction, order_id)
    if txn is None:  # pragma: no cover - 外键保证一致
        raise HTTPException(status_code=404, detail="基金申请不存在")
    return txn, order


@router.post("/orders", status_code=status.HTTP_201_CREATED, response_model=FundOrderDetailOut)
def create_order(payload: FundOrderIn, db: Session = Depends(get_db)) -> FundOrderDetailOut:
    if db.get(InvestmentAccount, payload.account_id) is None:
        raise HTTPException(status_code=404, detail="投资账户不存在")
    if db.get(Instrument, payload.instrument_id) is None:
        raise HTTPException(status_code=404, detail="投资品种不存在")

    # 现金分红以平台到账为既成事实，创建即确认；其余为两段式申请（§15.1）
    is_cash_dividend = payload.transaction_type == "CASH_DIVIDEND"
    txn_status = "CONFIRMED" if is_cash_dividend else "DRAFT"
    confirmation_status = "CONFIRMED" if is_cash_dividend else "PENDING"
    # total_amount：申购/现金分红取实际金额；赎回/再投资确认前无实际金额，保持 NULL
    total_amount = (
        payload.apply_amount
        if payload.transaction_type
        in (
            "FUND_SUBSCRIBE",
            "CASH_DIVIDEND",
        )
        else None
    )

    txn = InvestmentTransaction(
        account_id=payload.account_id,
        instrument_id=payload.instrument_id,
        transaction_type=payload.transaction_type,
        status=txn_status,
        confirmation_status=confirmation_status,
        business_date=payload.business_date,
        total_amount=total_amount,
        memo=payload.memo,
        idempotency_key=payload.idempotency_key,
    )
    db.add(txn)
    try:
        db.flush()
        order = FundOrderDetail(
            transaction_id=txn.id,
            platform=payload.platform,
            apply_amount=payload.apply_amount,
            apply_shares=payload.apply_shares,
            expected_fee=payload.expected_fee,
        )
        db.add(order)
        db.commit()
    except Exception:
        db.rollback()
        raise BusinessError("重复请求：相同幂等键的基金申请已存在") from None
    db.refresh(txn)
    db.refresh(order)
    record_audit(
        db,
        "fund.order.create",
        "investment_transaction",
        str(txn.id),
        {"type": txn.transaction_type},
    )
    db.commit()
    return _to_out(db, txn, order)


@router.get("/orders", response_model=list[FundOrderOut])
def list_orders(
    account_id: uuid.UUID | None = None,
    transaction_type: FundTxnType | None = None,
    instrument_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
) -> list[FundOrderOut]:
    query = (
        select(InvestmentTransaction, FundOrderDetail, FundConfirmation)
        .join(FundOrderDetail, FundOrderDetail.transaction_id == InvestmentTransaction.id)
        .outerjoin(FundConfirmation, FundConfirmation.transaction_id == InvestmentTransaction.id)
        .where(InvestmentTransaction.transaction_type.in_(list(get_args(FundTxnType))))
        .order_by(
            InvestmentTransaction.business_date.desc(),
            InvestmentTransaction.created_at.desc(),
        )
    )
    if account_id:
        query = query.where(InvestmentTransaction.account_id == account_id)
    if instrument_id:
        query = query.where(InvestmentTransaction.instrument_id == instrument_id)
    if transaction_type:
        query = query.where(InvestmentTransaction.transaction_type == transaction_type)
    if active_only:
        query = query.where(InvestmentTransaction.status.notin_(["CANCELLED", "REVERSED"]))
        query = query.where(
            (InvestmentTransaction.confirmation_status.is_(None))
            | (InvestmentTransaction.confirmation_status != "FAILED")
        )
    if status_filter:
        query = query.where(InvestmentTransaction.status == status_filter)
    rows = db.execute(query.limit(100)).all()
    return [
        FundOrderOut(
            id=txn.id,
            account_id=txn.account_id,
            instrument_id=txn.instrument_id,  # type: ignore[arg-type]
            transaction_type=txn.transaction_type,
            status=txn.status,
            confirmation_status=txn.confirmation_status,
            business_date=txn.business_date,
            confirmation_date=conf.confirmation_date if conf else None,
            currency=txn.currency,
            total_amount=txn.total_amount,
            memo=txn.memo,
            platform=order.platform,
            apply_amount=order.apply_amount,
            apply_shares=order.apply_shares,
            expected_fee=order.expected_fee,
        )
        for txn, order, conf in rows
    ]


@router.get("/orders/{order_id}", response_model=FundOrderDetailOut)
def get_order(order_id: uuid.UUID, db: Session = Depends(get_db)) -> FundOrderDetailOut:
    txn, order = _get(db, order_id)
    return _to_out(db, txn, order)


@router.post("/orders/{order_id}/confirm", response_model=FundOrderDetailOut)
def confirm_order(
    order_id: uuid.UUID, payload: FundConfirmationIn, db: Session = Depends(get_db)
) -> FundOrderDetailOut:
    txn, order = _get(db, order_id)
    if txn.transaction_type not in TWO_STAGE_TYPES:
        raise BusinessError("现金分红无需确认")
    if txn.status != "DRAFT" or txn.confirmation_status != "PENDING":
        raise BusinessError("该基金申请不能重复确认")

    # 金额守恒（§15.2）：申购实际扣款 = 净申购金额 + 申购费
    if (
        txn.transaction_type == "FUND_SUBSCRIBE"
        and order.apply_amount != payload.confirmed_amount + payload.fee_amount
    ):
        raise BusinessError("申购金额不守恒：实际扣款应等于净申购金额加申购费")

    conf = FundConfirmation(
        transaction_id=txn.id,
        confirmation_date=payload.confirmation_date,
        nav=payload.nav,
        confirmed_shares=payload.confirmed_shares,
        confirmed_amount=payload.confirmed_amount,
        fee_amount=payload.fee_amount,
        raw=payload.raw,
    )
    db.add(conf)
    txn.status = "CONFIRMED"
    txn.confirmation_status = "CONFIRMED"
    if txn.transaction_type in ("FUND_REDEEM", "DIVIDEND_REINVEST"):
        txn.total_amount = payload.confirmed_amount
    record_audit(
        db,
        "fund.order.confirm",
        "investment_transaction",
        str(txn.id),
        {"shares": str(payload.confirmed_shares), "amount": str(payload.confirmed_amount)},
    )
    db.commit()
    db.refresh(txn)
    db.refresh(order)
    return _to_out(db, txn, order)


@router.post("/orders/{order_id}/fail", response_model=FundOrderOut)
def fail_order(order_id: uuid.UUID, db: Session = Depends(get_db)) -> FundOrderOut:
    txn, order = _get(db, order_id)
    if txn.status != "DRAFT" or txn.confirmation_status != "PENDING":
        raise BusinessError("只有待确认的申请可以标记失败")
    txn.confirmation_status = "FAILED"
    txn.status = "CANCELLED"
    record_audit(db, "fund.order.fail", "investment_transaction", str(txn.id))
    db.commit()
    return FundOrderOut(
        id=txn.id,
        account_id=txn.account_id,
        instrument_id=txn.instrument_id,  # type: ignore[arg-type]
        transaction_type=txn.transaction_type,
        status=txn.status,
        confirmation_status=txn.confirmation_status,
        business_date=txn.business_date,
        currency=txn.currency,
        total_amount=txn.total_amount,
        memo=txn.memo,
        platform=order.platform,
        apply_amount=order.apply_amount,
        apply_shares=order.apply_shares,
        expected_fee=order.expected_fee,
    )
