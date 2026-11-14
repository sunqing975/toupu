# 0012 —— M7 Agent 框架对齐 WeKnora：技能目录 + Agent 实体（一等实体）。
# 风格与 0008/0009/0010 一致：原生 op.execute DDL，gen_random_uuid() 主键，JSONB 扩展列。
from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 技能目录：每个技能是可以在对话运行时被调用的工具能力。
    op.execute(
        """
        CREATE TABLE agent_skills (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            icon TEXT,
            category TEXT NOT NULL DEFAULT 'analysis',
            builtin BOOLEAN NOT NULL DEFAULT true,
            enabled BOOLEAN NOT NULL DEFAULT true,
            config JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    # Agent 实体：一等实体（对齐 WeKnora CustomAgent）。
    op.execute(
        """
        CREATE TABLE agent_definitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            icon TEXT,
            is_builtin BOOLEAN NOT NULL DEFAULT false,
            avatar_color TEXT,
            system_prompt TEXT NOT NULL DEFAULT '',
            model_id UUID,
            enabled_skill_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
            mcp_server_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX idx_agent_skills_builtin ON agent_skills (builtin)")
    op.execute("CREATE INDEX idx_agent_definitions_builtin ON agent_definitions (is_builtin)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_definitions")
    op.execute("DROP TABLE IF EXISTS agent_skills")
