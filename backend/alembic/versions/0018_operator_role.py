"""Separate built-in operator from investment analysis role."""

import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    # Preserve user prompts/model/MCP settings, append current role policy at runtime.
    op.execute(
        sa.text("""
        UPDATE agent_definitions a
        SET description = :description,
            enabled_skill_keys = COALESCE((
                SELECT jsonb_agg(k) FROM jsonb_array_elements_text(a.enabled_skill_keys) AS k
                WHERE k NOT IN ('analyze_portfolio_concentration', 'analyze_returns_attribution',
                                'scan_risk_events', 'draft_rebalance_plan')
            ), '[]'::jsonb)
        WHERE a.key = 'toupu-assistant' AND a.is_builtin = true
    """).bindparams(
            description="投谱程序操作助手：管理资料、查询记录、辅助录入和使用功能，不参与投资分析或买卖建议。"
        )
    )


def downgrade():
    # Do not silently restore removed permissions.
    pass
