# 数据库设计与初始表清单

## 1. 数据库约定

- PostgreSQL。
- 主键优先 UUID（`gen_random_uuid()`）；行情大表可使用 BIGINT identity。
- 时间统一存储 `TIMESTAMPTZ`；业务交易日期使用 `DATE`。
- 金额、价格、份额、数量使用 `NUMERIC`，禁止 `REAL`/`DOUBLE PRECISION` 做金融事实字段。
- 代码和枚举使用稳定字符串；Python Enum 与数据库约束保持一致。
- JSONB 仅用于来源原始数据、非核心扩展属性和导入原始行，不把核心业务字段塞入 JSON。
- 所有表通过 Alembic 管理；禁止手工改生产数据库 schema。

## 2. 核心表分组

### 基础数据

- `investment_accounts`
- `instruments`
- `instrument_identifiers`
- `trading_calendars`（后续）
- `trading_rules`（后续）

### 交易事实

- `investment_transactions`
- `trade_executions`
- `fund_order_details`（建议新增：申购/赎回申请特有字段）
- `fund_confirmations`
- `corporate_actions`
- `corporate_action_records`

### 账本

- `ledger_accounts`
- `journal_entries`
- `journal_lines`
- `transaction_reversals`（可由 reversal_of_id 实现，也可独立表）

### 持仓与收益

- `position_lots`
- `position_lot_disposals`
- `position_snapshots`
- `portfolio_snapshots`
- `account_balance_snapshots`

### 市场数据

- `market_quotes`
- `fund_nav_history`
- `data_sync_jobs`
- `data_sync_logs`

### 风险和 Agent

- `risk_rules`
- `risk_events`
- `investment_plans`
- `investment_plan_actions`
- `agent_tokens`
- `agent_operations`
- `operation_proposals`
- `audit_logs`

### 文件导入

- `import_batches`
- `import_records`
- `import_templates`
- `import_field_mappings`

## 3. 重要设计说明

### 交易表不要承担所有细节

`investment_transactions` 是统一业务事件索引，具体资产类型细节放在关联表中。证券实际成交放 `trade_executions`；场外基金申请和确认放基金专用表。不要把基金确认字段和股票成交字段都做成大量可空列。

### 账务科目需要明确维度

证券资产科目至少按 `investment_account_id + instrument_id + currency` 区分；现金科目按账户和币种区分。科目唯一约束需要结合 `account_type` 做部分唯一索引或采用明确 `account_code` 生成策略。

### 借贷平衡

普通 CHECK 约束不能校验跨行合计。必须通过事务内 PostingService 校验，并增加数据库层保护（延迟约束触发器或受控存储过程）。禁止允许应用角色任意直接写入已过账分录。

### 过账幂等

`journal_entries.transaction_id` 应唯一，或使用独立 `idempotency_key`。外部导入记录也要保存来源和外部唯一编号。冲正记录需要明确关联原交易和原 journal entry。

### 持仓快照不是事实

快照可删除重建。必须能从已过账账本事件重建数量和成本。PositionLot 和 lot disposal 是成本分摊轨迹，不能取代原始成交/确认记录。

## 4. 第一轮迁移范围

第一轮只创建：

1. `investment_accounts`
2. `instruments`
3. `instrument_identifiers`
4. `investment_transactions`
5. `trade_executions`
6. `fund_order_details`
7. `fund_confirmations`
8. `ledger_accounts`
9. `journal_entries`
10. `journal_lines`
11. `position_lots`
12. `position_lot_disposals`
13. `audit_logs`

第二轮再增加公司行为、行情、快照、导入、风险和 Agent 表。这样可以先验证账本，不必一次性维护所有表。

## 5. 建议的 API 资源

- `/api/v1/accounts`
- `/api/v1/instruments`
- `/api/v1/transactions`
- `/api/v1/transactions/{id}/confirm`
- `/api/v1/transactions/{id}/post`
- `/api/v1/transactions/{id}/reverse`
- `/api/v1/transactions/{id}/executions`
- `/api/v1/fund-orders/{id}/confirmation`
- `/api/v1/ledger/accounts`
- `/api/v1/ledger/entries`
- `/api/v1/positions`
- `/api/v1/imports`

正式 API 设计时需区分用户可调用的用例和内部服务接口，不要把 `/post` 暴露为 Agent 可随意调用的写接口。
