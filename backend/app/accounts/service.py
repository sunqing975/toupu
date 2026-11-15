"""Account metadata creation; never creates transactions or ledger entries."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.models import InvestmentAccount
from app.audit import record_audit


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    account_type: Literal["BROKER", "FUND_PLATFORM"]
    currency: Literal["CNY"] = "CNY"
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("账户名称不能为空")
        return value


def find_account(db: Session, name: str) -> InvestmentAccount | None:
    return db.scalar(select(InvestmentAccount).where(InvestmentAccount.name == name))


def create_account_record(db: Session, payload: AccountCreate, *, source: str) -> InvestmentAccount:
    """Flush only: caller owns account + audit transaction."""
    account = InvestmentAccount(**payload.model_dump())
    db.add(account)
    db.flush()
    record_audit(db, "CREATE_ACCOUNT", "account", str(account.id), {"source": source})
    return account
