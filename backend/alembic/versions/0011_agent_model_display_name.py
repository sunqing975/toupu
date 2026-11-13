# 0011 —— M7 Agent 模型配置：增加可选的中文别名 display_name
# 风格与 0008~0010 一致：原生 op.execute DDL。
from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_models
        ADD COLUMN display_name TEXT;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE agent_models DROP COLUMN IF EXISTS display_name")
