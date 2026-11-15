"""Advisory-level immutable flows without fictional fund shares."""

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE advisory_flows (
        id UUID PRIMARY KEY,
        account_id UUID NOT NULL REFERENCES investment_accounts(id),
        portfolio_name VARCHAR(100) NOT NULL,
        external_id VARCHAR(100) NOT NULL,
        kind VARCHAR(20) NOT NULL CHECK(kind IN ('CONTRIBUTION','WITHDRAWAL','FEE','REFUND')),
        occurred_on DATE NOT NULL,
        confirmed_on DATE,
        amount NUMERIC(20,2) NOT NULL CHECK(amount > 0),
        subsidy NUMERIC(20,2) NOT NULL DEFAULT 0 CHECK(subsidy >= 0 AND subsidy <= amount),
        fee_scope VARCHAR(20) NOT NULL CHECK(fee_scope IN ('INTERNAL','EXTERNAL','UNKNOWN')),
        evidence JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE(account_id,portfolio_name,external_id)
    )""")


def downgrade():
    op.execute("DROP TABLE advisory_flows")
