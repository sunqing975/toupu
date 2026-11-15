"""Per-Agent instruction directory bindings."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "agent_definitions",
        sa.Column("skill_package_keys", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    # Preserve existing builtin behavior only; new custom Agents are deny-by-default.
    op.execute(
        "UPDATE agent_definitions SET skill_package_keys=(SELECT "
        "COALESCE(jsonb_agg(key),'[]'::jsonb) FROM agent_skills "
        "WHERE category='instruction') WHERE is_builtin=true"
    )


def downgrade():
    op.drop_column("agent_definitions", "skill_package_keys")
