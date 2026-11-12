"""journal_lines 增加 line_no，保证分录行按过账顺序确定性返回

Revision ID: 0005
Revises: 0004
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE journal_lines
            ADD COLUMN line_no INTEGER NOT NULL DEFAULT 0;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE journal_lines DROP COLUMN line_no;")
