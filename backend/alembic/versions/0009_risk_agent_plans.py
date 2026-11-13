"""M6 风险与 Agent：确定性风险规则/事件 + Token/审计 + 提案/计划（迁移可从空库执行）

- risk_rules / risk_events：确定性风险扫描与事件（docs/risk-agent-rules.md §3/§4）
- investment_plans / investment_plan_actions：轻量决策记录，不触发账务
- agent_tokens / agent_operations：只存 sha256、只追加审计
- operation_proposals：Agent 只能建 PENDING，用户审批只生成 DRAFT

Revision ID: 0009
Revises: 0008
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        -- 风险规则（§6：scope×rule_type 组合由应用层校验；阈值 0<threshold<=1）
        CREATE TABLE risk_rules (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            scope            TEXT NOT NULL
                             CHECK (scope IN ('PORTFOLIO', 'ACCOUNT', 'INSTRUMENT')),
            rule_type        TEXT NOT NULL
                             CHECK (rule_type IN (
                                 'POSITION_WEIGHT', 'ACCOUNT_WEIGHT',
                                 'PORTFOLIO_DRAWDOWN', 'QUOTE_COVERAGE')),
            threshold        NUMERIC(9, 6) NOT NULL
                             CHECK (threshold > 0 AND threshold <= 1),
            severity         TEXT NOT NULL DEFAULT 'WARNING'
                             CHECK (severity IN ('INFO', 'WARNING', 'CRITICAL')),
            enabled          BOOLEAN NOT NULL DEFAULT true,
            cooldown_minutes INT NOT NULL DEFAULT 1440 CHECK (cooldown_minutes >= 0),
            memo             TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        -- 风险事件（dedup_key UNIQUE 保证同日重复扫描幂等；只改状态不删除）
        CREATE TABLE risk_events (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_id          UUID NOT NULL REFERENCES risk_rules(id),
            as_of            DATE NOT NULL,
            scope            TEXT NOT NULL,
            subject          TEXT NOT NULL,
            rule_type        TEXT NOT NULL,
            severity         TEXT NOT NULL,
            trigger_value    NUMERIC(20, 6),
            threshold        NUMERIC(9, 6) NOT NULL,
            message          TEXT NOT NULL,
            status           TEXT NOT NULL DEFAULT 'OPEN'
                             CHECK (status IN ('OPEN', 'ACKNOWLEDGED', 'IGNORED')),
            dedup_key        TEXT NOT NULL UNIQUE,
            triggered_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at      TIMESTAMPTZ,
            resolution_note  TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_risk_events_lookup ON risk_events (status, triggered_at DESC);
        CREATE INDEX idx_risk_events_rule ON risk_events (rule_id, subject);

        -- 投资计划（决策记录，不触发任何账务动作）
        CREATE TABLE investment_plans (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name           TEXT NOT NULL,
            description    TEXT,
            status         TEXT NOT NULL DEFAULT 'ACTIVE'
                           CHECK (status IN ('ACTIVE', 'ARCHIVED')),
            target_amount  NUMERIC(20, 6),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE investment_plan_actions (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            plan_id        UUID NOT NULL REFERENCES investment_plans(id) ON DELETE CASCADE,
            title          TEXT NOT NULL,
            note           TEXT,
            target_amount  NUMERIC(20, 6),
            sort_no        INT NOT NULL DEFAULT 0,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_plan_actions_plan ON investment_plan_actions (plan_id, sort_no);

        -- Agent Token：只存 sha256 明文散列，scopes 白名单由应用层校验
        CREATE TABLE agent_tokens (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name          TEXT NOT NULL,
            token_hash    TEXT NOT NULL UNIQUE,
            scopes        JSONB NOT NULL,
            active        BOOLEAN NOT NULL DEFAULT true,
            revoked_at    TIMESTAMPTZ,
            last_used_at  TIMESTAMPTZ,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        -- Agent 操作审计：只追加，失败调用也留痕（token_id 可空）
        CREATE TABLE agent_operations (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            token_id     UUID REFERENCES agent_tokens(id),
            resource     TEXT NOT NULL,
            scope        TEXT,
            http_status  INT NOT NULL,
            detail       JSONB,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_agent_ops_token ON agent_operations (token_id, created_at DESC);

        -- 待审批提案：Agent 只建 PENDING，用户审批只生成 DRAFT
        CREATE TABLE operation_proposals (
            id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            proposal_type             TEXT NOT NULL,
            status                    TEXT NOT NULL DEFAULT 'PENDING'
                                      CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED')),
            created_by                TEXT NOT NULL,
            payload                   JSONB NOT NULL,
            impact_preview            JSONB NOT NULL,
            validation_snapshot       JSONB NOT NULL,
            expires_at                TIMESTAMPTZ NOT NULL,
            resolved_at               TIMESTAMPTZ,
            resolved_by               TEXT,
            resolution_note           TEXT,
            resulting_transaction_id  UUID REFERENCES investment_transactions(id),
            created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_proposals_status ON operation_proposals (status, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS operation_proposals;
        DROP TABLE IF EXISTS agent_operations;
        DROP TABLE IF EXISTS agent_tokens;
        DROP TABLE IF EXISTS investment_plan_actions;
        DROP TABLE IF EXISTS investment_plans;
        DROP TABLE IF EXISTS risk_events;
        DROP TABLE IF EXISTS risk_rules;
        """
    )
