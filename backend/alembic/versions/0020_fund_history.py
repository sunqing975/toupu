"""Auditable, idempotent user-confirmed fund history imports."""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE fund_history_imports (
        id UUID PRIMARY KEY,
        account_id UUID NOT NULL REFERENCES investment_accounts(id),
        instrument_id UUID NOT NULL REFERENCES instruments(id),
        request_key VARCHAR(100) NOT NULL UNIQUE,
        payload JSONB NOT NULL,
        result JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE(account_id,instrument_id)
    )""")


def downgrade():
    op.execute("DROP TABLE fund_history_imports")
