"""Platform-reported holdings, separate from ledger-derived positions."""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE platform_asset_batches (
        id UUID PRIMARY KEY,
        account_id UUID NOT NULL REFERENCES investment_accounts(id),
        observed_on DATE NOT NULL,
        source VARCHAR(200) NOT NULL,
        request_key VARCHAR(100) NOT NULL UNIQUE,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE(account_id, observed_on)
    );
    CREATE TABLE platform_asset_items (
        id UUID PRIMARY KEY,
        batch_id UUID NOT NULL REFERENCES platform_asset_batches(id),
        name VARCHAR(100) NOT NULL,
        kind VARCHAR(20) NOT NULL CHECK(kind IN ('FUND', 'ADVISORY', 'STOCK', 'ETF')),
        code VARCHAR(20),
        market_value NUMERIC(20,2) NOT NULL CHECK(market_value >= 0),
        holding_pnl NUMERIC(20,2) NOT NULL,
        cumulative_pnl NUMERIC(20,2),
        quantity NUMERIC(24,8),
        valuation_date DATE,
        UNIQUE(batch_id, name)
    );
    """)


def downgrade():
    op.execute("DROP TABLE platform_asset_items; DROP TABLE platform_asset_batches;")
