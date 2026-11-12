"""v0.0.1 基础账本首轮 13 张表（依据 docs/database-design.md 第一轮迁移范围）

约定：UUID 主键 gen_random_uuid()；时间 TIMESTAMPTZ、业务日期 DATE；
金额/价格/份额 NUMERIC；枚举用 TEXT + CHECK，便于后续扩展。

Revision ID: 0001
Revises:
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DDL = """
-- ========== 基础数据 ==========

CREATE TABLE investment_accounts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    account_type TEXT NOT NULL CHECK (account_type IN ('BROKER', 'FUND_PLATFORM', 'BANK', 'CASH')),
    currency    CHAR(3) NOT NULL DEFAULT 'CNY',
    status      TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'FROZEN', 'CLOSED')),
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE instruments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_type TEXT NOT NULL CHECK (instrument_type IN ('FUND', 'ETF', 'STOCK')),
    market          TEXT NOT NULL,
    exchange        TEXT,
    code            TEXT NOT NULL,
    name            TEXT NOT NULL,
    currency        CHAR(3) NOT NULL DEFAULT 'CNY',
    status          TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'DELISTED')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 基金无交易所，exchange 允许为空；唯一性按 market + code 保证
CREATE UNIQUE INDEX uq_instruments_market_code ON instruments (market, code);

CREATE TABLE instrument_identifiers (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id UUID NOT NULL REFERENCES instruments(id),
    provider      TEXT NOT NULL,
    provider_code TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_code)
);

-- ========== 交易事实 ==========

CREATE TABLE investment_transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id          UUID NOT NULL REFERENCES investment_accounts(id),
    transaction_type    TEXT NOT NULL CHECK (transaction_type IN (
        'STOCK_BUY', 'STOCK_SELL', 'ETF_BUY', 'ETF_SELL',
        'FUND_SUBSCRIBE', 'FUND_REDEEM', 'FUND_CONVERT',
        'CASH_DIVIDEND', 'DIVIDEND_REINVEST',
        'DEPOSIT', 'WITHDRAW', 'ACCOUNT_TRANSFER',
        'BONUS_SHARES', 'STOCK_SPLIT', 'OTHER_CORPORATE_ACTION',
        'FEE_ADJUSTMENT', 'OPENING_BALANCE')),
    status              TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN (
        'DRAFT', 'CONFIRMED', 'PARTIAL', 'POSTED', 'REVERSED', 'CANCELLED')),
    confirmation_status TEXT CHECK (confirmation_status IN ('PENDING', 'CONFIRMED', 'FAILED')),
    business_date       DATE NOT NULL,
    currency            CHAR(3) NOT NULL DEFAULT 'CNY',
    total_amount        NUMERIC(20, 6),
    memo                TEXT,
    reversal_of_id      UUID REFERENCES investment_transactions(id),
    idempotency_key     TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_transactions_idempotency_key
    ON investment_transactions (idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE INDEX idx_transactions_account ON investment_transactions (account_id, business_date);

CREATE TABLE trade_executions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID NOT NULL REFERENCES investment_transactions(id),
    sequence_no    INT NOT NULL,
    execution_date DATE NOT NULL,
    quantity       NUMERIC(20, 6) NOT NULL CHECK (quantity > 0),
    price          NUMERIC(20, 6) NOT NULL CHECK (price > 0),
    gross_amount   NUMERIC(20, 6) NOT NULL,
    fee_amount     NUMERIC(20, 6) NOT NULL DEFAULT 0 CHECK (fee_amount >= 0),
    net_amount     NUMERIC(20, 6) NOT NULL,
    fee_detail     JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (transaction_id, sequence_no)
);

CREATE TABLE fund_order_details (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID NOT NULL UNIQUE REFERENCES investment_transactions(id),
    platform       TEXT NOT NULL,
    apply_amount   NUMERIC(20, 6) NOT NULL CHECK (apply_amount > 0),
    expected_fee   NUMERIC(20, 6),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE fund_confirmations (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id    UUID NOT NULL UNIQUE REFERENCES investment_transactions(id),
    confirmation_date DATE NOT NULL,
    nav               NUMERIC(20, 6) NOT NULL CHECK (nav > 0),
    confirmed_shares  NUMERIC(20, 6) NOT NULL CHECK (confirmed_shares > 0),
    confirmed_amount  NUMERIC(20, 6) NOT NULL,
    fee_amount        NUMERIC(20, 6) NOT NULL DEFAULT 0,
    raw               JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ========== 账本 ==========

CREATE TABLE ledger_accounts (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_type         TEXT NOT NULL CHECK (account_type IN (
        'CASH', 'SECURITY', 'FEE_EXPENSE', 'DIVIDEND_INCOME',
        'REALIZED_GAIN', 'REALIZED_LOSS', 'OPENING_BALANCE', 'TRANSFER_CLEARING')),
    investment_account_id UUID REFERENCES investment_accounts(id),
    instrument_id        UUID REFERENCES instruments(id),
    currency             CHAR(3) NOT NULL DEFAULT 'CNY',
    name                 TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- NULLS NOT DISTINCT：同一组合（含 NULL）唯一，PG18 原生支持
    UNIQUE NULLS NOT DISTINCT (account_type, investment_account_id, instrument_id, currency)
);

CREATE TABLE journal_entries (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id       UUID NOT NULL UNIQUE REFERENCES investment_transactions(id),
    entry_type           TEXT NOT NULL DEFAULT 'NORMAL' CHECK (entry_type IN ('NORMAL', 'REVERSAL')),
    reversal_of_entry_id UUID REFERENCES journal_entries(id),
    posted_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    memo                 TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- transaction_id 唯一：一笔交易最多一条有效分录，保证过账幂等

CREATE TABLE journal_lines (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_id          UUID NOT NULL REFERENCES journal_entries(id),
    ledger_account_id UUID NOT NULL REFERENCES ledger_accounts(id),
    direction         TEXT NOT NULL CHECK (direction IN ('DEBIT', 'CREDIT')),
    amount            NUMERIC(20, 6) NOT NULL CHECK (amount > 0),
    memo              TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_journal_lines_entry ON journal_lines (entry_id);

-- ========== 持仓批次 ==========

CREATE TABLE position_lots (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    investment_account_id UUID NOT NULL REFERENCES investment_accounts(id),
    instrument_id         UUID NOT NULL REFERENCES instruments(id),
    origin_transaction_id UUID NOT NULL REFERENCES investment_transactions(id),
    lot_origin            TEXT NOT NULL CHECK (lot_origin IN ('TRADE', 'OPENING_BALANCE', 'CORPORATE_ACTION')),
    open_date             DATE NOT NULL,
    quantity              NUMERIC(20, 6) NOT NULL CHECK (quantity > 0),
    remaining_quantity    NUMERIC(20, 6) NOT NULL CHECK (remaining_quantity >= 0),
    unit_cost             NUMERIC(20, 6) NOT NULL,
    total_cost            NUMERIC(20, 6) NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE position_lot_disposals (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lot_id                  UUID NOT NULL REFERENCES position_lots(id),
    disposal_transaction_id UUID NOT NULL REFERENCES investment_transactions(id),
    quantity                NUMERIC(20, 6) NOT NULL CHECK (quantity > 0),
    cost_amount             NUMERIC(20, 6) NOT NULL,
    disposal_date           DATE NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (lot_id, disposal_transaction_id)
);

-- ========== 审计 ==========

CREATE TABLE audit_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    detail      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_logs_entity ON audit_logs (entity_type, entity_id);
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("""
DROP TABLE IF EXISTS audit_logs, position_lot_disposals, position_lots,
    journal_lines, journal_entries, ledger_accounts,
    fund_confirmations, fund_order_details, trade_executions,
    investment_transactions, instrument_identifiers, instruments,
    investment_accounts CASCADE
""")
