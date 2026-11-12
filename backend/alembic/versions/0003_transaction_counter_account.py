"""转账业务需要记录转入账户 counter_account_id

Revision ID: 0003
Revises: 0002
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE investment_transactions
    ADD COLUMN counter_account_id UUID REFERENCES investment_accounts(id);
""")


def downgrade() -> None:
    op.execute("ALTER TABLE investment_transactions DROP COLUMN counter_account_id;")
