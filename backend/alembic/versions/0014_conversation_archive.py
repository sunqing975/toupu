"""Preserve conversation history with reversible archival."""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_conversations ADD COLUMN archived_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE agent_conversations DROP COLUMN archived_at")
