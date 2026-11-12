"""证券交易需要 instrument_id 与成交明细支持

Revision ID: 0004
Revises: 0003
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE investment_transactions
    ADD COLUMN instrument_id UUID REFERENCES instruments(id);
""")


def downgrade() -> None:
    op.execute("ALTER TABLE investment_transactions DROP COLUMN instrument_id;")
