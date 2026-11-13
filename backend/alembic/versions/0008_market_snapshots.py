"""M5 行情与收益：行情/净值 + 持仓/组合快照（迁移可从空库执行）

- market_quotes / fund_nav_history：MANUAL Provider 录入的标准化行情（估值输入，不是交易事实）
- position_snapshots / portfolio_snapshots：可删除重建的派生结果（database-design §3）
- 依据 docs/ledger-rules.md §17（公式先落文档再实现）

Revision ID: 0008
Revises: 0007
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        -- 股票/ETF 日行情（§13：供应商/采集时间/市场时间/数据类型/延迟/复权/质量）
        CREATE TABLE market_quotes (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            instrument_id  UUID NOT NULL REFERENCES instruments(id),
            quote_date     DATE NOT NULL,
            provider       TEXT NOT NULL,
            provider_code  TEXT,
            collected_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            market_time    TIMESTAMPTZ,
            data_type      TEXT NOT NULL CHECK (data_type IN ('OFFICIAL', 'ESTIMATED')),
            price          NUMERIC(20, 6) NOT NULL CHECK (price >= 0),
            adjust_type    TEXT NOT NULL DEFAULT 'NONE'
                           CHECK (adjust_type IN ('NONE', 'PRE', 'POST')),
            quality_status TEXT NOT NULL DEFAULT 'FRESH'
                           CHECK (quality_status IN ('FRESH', 'STALE', 'SUSPENDED', 'NO_QUOTE')),
            delayed        BOOLEAN NOT NULL DEFAULT false,
            currency       TEXT NOT NULL DEFAULT 'CNY',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (instrument_id, quote_date, provider, data_type, adjust_type)
        );
        CREATE INDEX idx_market_quotes_lookup ON market_quotes (instrument_id, quote_date);

        -- 基金正式净值（盘中估值与正式净值以 data_type 区分，估值不用于核算，§13）
        CREATE TABLE fund_nav_history (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            instrument_id     UUID NOT NULL REFERENCES instruments(id),
            nav_date          DATE NOT NULL,
            provider          TEXT NOT NULL,
            provider_code     TEXT,
            collected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            data_type         TEXT NOT NULL CHECK (data_type IN ('OFFICIAL', 'ESTIMATED')),
            nav               NUMERIC(20, 6) NOT NULL CHECK (nav > 0),
            accumulated_nav   NUMERIC(20, 6),
            quality_status    TEXT NOT NULL DEFAULT 'FRESH'
                              CHECK (quality_status IN ('FRESH', 'STALE', 'SUSPENDED', 'NO_QUOTE')),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (instrument_id, nav_date, provider, data_type)
        );
        CREATE INDEX idx_fund_nav_lookup ON fund_nav_history (instrument_id, nav_date);

        -- 逐账户×品种持仓快照（派生结果，同一日期 rebuild 先删后建，§17.7）
        CREATE TABLE position_snapshots (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            snapshot_date   DATE NOT NULL,
            account_id      UUID NOT NULL REFERENCES investment_accounts(id),
            instrument_id   UUID NOT NULL REFERENCES instruments(id),
            quantity        NUMERIC(20, 6) NOT NULL,
            book_cost       NUMERIC(20, 6) NOT NULL,
            quote_price     NUMERIC(20, 6),
            quote_status    TEXT NOT NULL
                            CHECK (quote_status IN ('FRESH', 'STALE', 'UNKNOWN', 'ESTIMATED')),
            quote_date      DATE,
            quote_provider  TEXT,
            market_value    NUMERIC(20, 6),
            unrealized      NUMERIC(20, 6),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (snapshot_date, account_id, instrument_id)
        );

        -- 组合快照（MDD/TWR 的统一口径净值序列，§17.6/§17.7）
        CREATE TABLE portfolio_snapshots (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            snapshot_date     DATE NOT NULL UNIQUE,
            cash_total        NUMERIC(20, 6) NOT NULL,
            market_value      NUMERIC(20, 6) NOT NULL,
            total_assets      NUMERIC(20, 6) NOT NULL,
            realized_total    NUMERIC(20, 6) NOT NULL,
            dividend_income   NUMERIC(20, 6) NOT NULL,
            unrealized_total  NUMERIC(20, 6) NOT NULL,
            coverage          NUMERIC(9, 6) NOT NULL CHECK (coverage >= 0 AND coverage <= 1),
            valued_positions  INT NOT NULL DEFAULT 0,
            total_positions   INT NOT NULL DEFAULT 0,
            data_quality      TEXT NOT NULL
                              CHECK (data_quality IN ('COMPLETE', 'PARTIAL', 'NO_QUOTES')),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS portfolio_snapshots;
        DROP TABLE IF EXISTS position_snapshots;
        DROP TABLE IF EXISTS fund_nav_history;
        DROP TABLE IF EXISTS market_quotes;
        """
    )
