"""M4 导入与期初资产：导入批次/原始行/模板/字段映射 + 期初余额明细

- import_templates / import_field_mappings：模板与字段映射定义
- import_batches / import_records：原始行保存、校验/去重状态、错误定位
- opening_balance_details：期初现金/持仓的来源可信度与估值日期
- 期初分录沿用 0001 已有的 OPENING_BALANCE 业务类型 / 科目类型 / lot_origin，无需改 CHECK

Revision ID: 0007
Revises: 0006
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE import_templates (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code         TEXT NOT NULL UNIQUE,
            name         TEXT NOT NULL,
            description  TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE import_field_mappings (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            template_id    UUID NOT NULL REFERENCES import_templates(id),
            source_column  TEXT NOT NULL,
            target_field   TEXT NOT NULL,
            required       BOOLEAN NOT NULL DEFAULT false,
            UNIQUE (template_id, source_column)
        );

        CREATE TABLE import_batches (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            template_id      UUID NOT NULL REFERENCES import_templates(id),
            file_name        TEXT NOT NULL,
            file_hash        TEXT NOT NULL,
            status           TEXT NOT NULL DEFAULT 'DRAFT'
                             CHECK (status IN ('DRAFT', 'CONFIRMED', 'CANCELLED')),
            raw_headers      JSONB,
            row_count        INT NOT NULL DEFAULT 0,
            error_count      INT NOT NULL DEFAULT 0,
            duplicate_count  INT NOT NULL DEFAULT 0,
            memo             TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            confirmed_at     TIMESTAMPTZ
        );

        -- 文件级去重：同一模板下相同文件内容不可重复导入（CANCELLED 批次允许重新上传）
        CREATE UNIQUE INDEX uq_import_batches_file
            ON import_batches (template_id, file_hash) WHERE status != 'CANCELLED';

        CREATE TABLE import_records (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id        UUID NOT NULL REFERENCES import_batches(id),
            row_no          INT NOT NULL,
            status          TEXT NOT NULL CHECK (status IN
                             ('VALID', 'ERROR', 'DUPLICATE', 'IMPORTED', 'SKIPPED')),
            dedup_key       TEXT,
            normalized      JSONB,
            raw             JSONB NOT NULL,
            errors          JSONB,
            transaction_id  UUID REFERENCES investment_transactions(id),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (batch_id, row_no)
        );

        CREATE INDEX idx_import_records_dedup ON import_records (dedup_key);

        CREATE TABLE opening_balance_details (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            transaction_id  UUID NOT NULL UNIQUE REFERENCES investment_transactions(id),
            row_kind        TEXT NOT NULL CHECK (row_kind IN ('CASH', 'POSITION')),
            quantity        NUMERIC(20, 6),
            total_cost      NUMERIC(20, 6),
            cost_source     TEXT,
            valuation_date  DATE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    # 内置模板与字段映射随迁移落库，保证空库可直接导入（agent.md §12 DoD）。
    op.execute(
        """
        INSERT INTO import_templates (code, name, description)
        VALUES ('OPENING_BALANCE_V1', '期初资产导入（第一版）',
                '期初现金 + 期初持仓；支持 CSV / Excel(.xlsx)');

        INSERT INTO import_field_mappings
            (template_id, source_column, target_field, required)
        SELECT t.id, m.source_column, m.target_field, m.required
          FROM import_templates t
          CROSS JOIN (VALUES
              ('row_kind',       'row_kind',       true),
              ('account_name',   'account_name',   true),
              ('business_date',  'business_date',  true),
              ('amount',         'amount',         false),
              ('market',         'market',         false),
              ('code',           'code',           false),
              ('quantity',       'quantity',       false),
              ('total_cost',     'total_cost',     false),
              ('currency',       'currency',       false),
              ('cost_source',    'cost_source',    false),
              ('valuation_date', 'valuation_date', false),
              ('external_id',    'external_id',    false),
              ('memo',           'memo',           false)
          ) AS m(source_column, target_field, required)
         WHERE t.code = 'OPENING_BALANCE_V1';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS opening_balance_details;
        DROP TABLE IF EXISTS import_records;
        DROP TABLE IF EXISTS import_batches;
        DROP TABLE IF EXISTS import_field_mappings;
        DROP TABLE IF EXISTS import_templates;
        """
    )
