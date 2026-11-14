# 0013 —— Agent 会话持久化 + 消息历史（用户反馈：历史会话也要存）。
# 风格与 0008~0012 一致：原生 op.execute DDL，gen_random_uuid() 主键。
# 设计：会话与消息分表；agent_id / model_id 故意不加外键，
# 这样删除 Agent 或模型配置后，历史对话依然完整可查。
from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agent_conversations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            title TEXT NOT NULL DEFAULT '',
            agent_id TEXT,
            model_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE agent_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL
                REFERENCES agent_conversations (id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            agent_name TEXT,
            model_name TEXT,
            model_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_agent_messages_conversation "
        "ON agent_messages (conversation_id, created_at)"
    )
    op.execute(
        "CREATE INDEX idx_agent_conversations_updated "
        "ON agent_conversations (updated_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_messages")
    op.execute("DROP TABLE IF EXISTS agent_conversations")
