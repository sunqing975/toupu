"""账户类型收紧：第一版仅券商/基金平台（银行与独立现金账户暂缓）

Revision ID: 0002
Revises: 0001
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE investment_accounts
    DROP CONSTRAINT investment_accounts_account_type_check;
ALTER TABLE investment_accounts
    ADD CONSTRAINT investment_accounts_account_type_check
    CHECK (account_type IN ('BROKER', 'FUND_PLATFORM'));
""")


def downgrade() -> None:
    op.execute("""
ALTER TABLE investment_accounts
    DROP CONSTRAINT investment_accounts_account_type_check;
ALTER TABLE investment_accounts
    ADD CONSTRAINT investment_accounts_account_type_check
    CHECK (account_type IN ('BROKER', 'FUND_PLATFORM', 'BANK', 'CASH'));
""")
