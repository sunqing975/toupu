"""Durable Agent runs, ordered events and explicit tool approval."""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE agent_runs (
            id UUID PRIMARY KEY, conversation_id UUID NOT NULL REFERENCES agent_conversations(id),
            request_key TEXT UNIQUE NOT NULL, status TEXT NOT NULL,
            input JSONB NOT NULL, cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX agent_runs_one_active ON agent_runs(conversation_id)
            WHERE status IN ('QUEUED','RUNNING','WAITING_APPROVAL');
        CREATE TABLE agent_run_events (
            run_id UUID NOT NULL REFERENCES agent_runs(id), seq INTEGER NOT NULL,
            event JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(run_id, seq)
        );
        CREATE TABLE agent_tool_approvals (
            id UUID PRIMARY KEY, run_id UUID NOT NULL REFERENCES agent_runs(id),
            call_id TEXT NOT NULL, name TEXT NOT NULL, arguments JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING', result TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(), decided_at TIMESTAMPTZ,
            UNIQUE(run_id, call_id)
        );
    """)


def downgrade() -> None:
    op.execute(
        "DROP TABLE agent_tool_approvals; DROP TABLE agent_run_events; DROP TABLE agent_runs"
    )
