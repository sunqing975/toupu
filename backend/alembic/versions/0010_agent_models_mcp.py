# 0010 —— M7 Agent 框架：可配置模型 + 外部 MCP 挂载
# 风格与 0008/0009 一致：原生 op.execute DDL，gen_random_uuid() 主键，JSONB 扩展列。
from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agent_models (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'openai-compatible',
            base_url TEXT NOT NULL,
            model TEXT NOT NULL,
            api_key TEXT,
            is_default BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE agent_mcp_servers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            transport TEXT NOT NULL CHECK (transport IN ('stdio', 'http')),
            command TEXT,
            url TEXT,
            config JSONB,
            enabled BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX idx_agent_models_default ON agent_models (is_default)")
    op.execute("CREATE INDEX idx_agent_mcp_enabled ON agent_mcp_servers (enabled)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_mcp_servers")
    op.execute("DROP TABLE IF EXISTS agent_models")
