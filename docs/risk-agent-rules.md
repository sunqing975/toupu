# 风险与 Agent 实现口径（M6，第一版）

> 本文定义 M6 的业务规则。依据：`docs/agent.md` §2（不可违反约束）/§4（模块边界）/§8（Agent 安全边界）/§9（测试）/§11（禁止事项）/§12（DoD）、`docs/implementation-plan.md` M6、`docs/user-flow.md` §5/§6、`docs/domain-model.md`、`docs/database-design.md` §2、「风险和 Agent」表组、`docs/architecture.md` §4/§6、`docs/page-spec.md` §11/§12。
>
> **本里程碑不改变账务语义**（不新增交易类型、不改分录模板、不动 `ledger/`、`positions/` 的过账与成本逻辑），故按 agent.md §10 不修改 `docs/ledger-rules.md`；业务规则集中定义于本文。若后续要让 Agent 提案生成证券/基金交易，必须先补文档并重跑账务测试。

## 1. 范围与不做的事

**做**：确定性风险规则与扫描、风险事件与冷却、Agent Token 与只读 scope、Agent 只读查询网关（带数据时间/来源/估值缺失元信息）、待审批提案（Agent 只能建 `PENDING`，用户审批只生成 `DRAFT`）、轻量投资计划、所有写操作审计。

**不做**（明确排除，防止需求漂移）：

- 不接 LLM、不做自然语言解析、不接 MCP SDK / 外部 Agent 运行时（architecture §2 的 MCP 适配层是后续能力；本版只提供 REST，且 REST 就是唯一入口）。
- 不提供自动下单、不提供 `/post` `/confirm` `/reverse` 给 Agent、不提供任何账本写入工具（agent.md §2.10/§8、§11）。
- 不用 LLM 计算持仓/成本/收益/风险阈值（agent.md §2.11/§11）；风险数值一律由普通 Python + `Decimal` 计算。
- 不引入定时任务框架/消息队列/Redis/Kafka（architecture §6 的定时扫描留接口 `POST /api/v1/risk/scan` 由用户或外部调度触发，实现幂等可重跑）。
- 不做通知渠道发送（仅落 `risk_events` 与冷却状态，页面展示即「通知」）。
- 不做多用户、不做多币种、不改持仓成本口径。

## 2. 总原则（不可违反的落点）

| 约束 | 本版落点 |
|---|---|
| 账本是唯一事实 | 风险/查询只读「已派生」数据（`app/performance/service.derive()`、`position_lots`、`portfolio_snapshots`、`audit_logs`），不写 `journal_*`、`position_lots` |
| 风险引擎确定性 | `app/risk/engine.py` 纯函数：输入 `(rules, derived, snapshots, as_of, now)` → 输出事件列表；同一输入必得同一输出，无随机、无 LLM、`now` 可注入便于测试 |
| 缺失不伪装 | 报价 `UNKNOWN`/`ESTIMATED` 的持仓不参与权重计算，并在扫描结果里列 `skipped`；快照不足时回撤规则返回 `INSUFFICIENT_DATA` 不产生数值事件（沿用 §17「指标公式未定义或未覆盖估值时不得输出数字」） |
| Agent 默认只读 | `agent_tokens.scopes` 用白名单；`GET /api/v1/agent/{resource}` 只有 GET；唯一写是 `POST /api/v1/agent/proposals`（`write:proposals`），且只写 `operation_proposals` |
| 写操作先 proposal/draft | 审批 `approve` 只调用 `transactions.create_transaction` 生成 **`DRAFT`**，绝不 confirm/post；用户仍需走既有确认→过账流程 |
| 审批后重新校验 | `approve` 重新查账户/标的/金额，并比对创建时的 `validation_snapshot`，不一致或过期 → 拒绝审批（`409`），不盲目执行 |
| 可审计 | 规则增改、Agent Token 创建/吊销、Agent 每次查询、提案创建/审批/拒绝 全部写 `audit_logs`（`record_audit`）+ `agent_operations` |
| 金融数值禁 float | 阈值/触发值/金额全 `Decimal` + `NUMERIC(20,6)` / `NUMERIC(9,6)`，API 十进制字符串 |
| 模块化单体 | 新模块 `risk`、`agent`、`plans`；跨模块只读调用 `performance`/`positions`/`market_data` 的 Service，不写对方表 |

## 3. 数据模型（迁移 0009）

沿用 `database-design.md` §2「风险和 Agent」表组，7 张新表（`audit_logs` 已存在）：

| 表 | 关键字段 | 约束 |
|---|---|---|
| `risk_rules` | `scope`(`PORTFOLIO`/`ACCOUNT`/`INSTRUMENT`)、`rule_type`、`threshold NUMERIC(9,6)`、`severity`(`INFO`/`WARNING`/`CRITICAL`)、`enabled BOOL`、`cooldown_minutes INT`、`memo`、`created_at`/`updated_at` | `scope`+`rule_type` 一致性 CHECK；`threshold>0`；`cooldown_minutes>=0` |
| `risk_events` | `rule_id FK`、`as_of DATE`、`scope`、`subject TEXT`、`rule_type`、`severity`、`trigger_value NUMERIC(20,6)|null`、`threshold`、`message`、`status`(`OPEN`/`ACKNOWLEDGED`/`IGNORED`)、`dedup_key TEXT UNIQUE`、`triggered_at`、`resolved_at`、`resolution_note` | `UNIQUE(dedup_key)` 保证同日重复扫描幂等 |
| `investment_plans` | `name`、`description`、`status`(`ACTIVE`/`ARCHIVED`)、`target_amount NUMERIC(20,6)|null`、`created_at`/`updated_at` | `name` 非空 |
| `investment_plan_actions` | `plan_id FK`、`title`、`note`、`target_amount`、`sort_no`、`created_at` | `plan_id` 级联 |
| `agent_tokens` | `name`、`token_hash TEXT UNIQUE`（**只存 sha256，不存明文**）、`scopes JSONB`、`active BOOL`、`revoked_at`、`last_used_at`、`created_at` | scope 白名单由应用层校验 |
| `agent_operations` | `token_id FK`、`resource`、`scope`、`http_status INT`、`detail JSONB`、`created_at` | 只追加，不修改 |
| `operation_proposals` | `proposal_type`、`status`(`PENDING`/`APPROVED`/`REJECTED`/`EXPIRED`)、`created_by`、`payload JSONB`、`impact_preview JSONB`、`validation_snapshot JSONB`、`expires_at`、`resolved_at`、`resolved_by`、`resolution_note`、`resulting_transaction_id FK investment_transactions|null`、`created_at` | 只追加状态流转，不删 |

`risk_rules.scope × rule_type` 合法组合（服务端强校验，不在 DB 用复杂 CHECK）：

| `rule_type` | `scope` | 触发量 | 触发条件 | 主体 `subject` |
|---|---|---|---|---|
| `POSITION_WEIGHT` | `INSTRUMENT` | 单品种 `market_value / total_assets` | `> threshold` | `instrument_id` |
| `ACCOUNT_WEIGHT` | `ACCOUNT` | 单账户 `Σmarket_value / total_assets` | `> threshold` | `account_id` |
| `PORTFOLIO_DRAWDOWN` | `PORTFOLIO` | `max_drawdown(portfolio_snapshots)` | `< -threshold` | `"PORTFOLIO"` |
| `QUOTE_COVERAGE` | `PORTFOLIO` | `derive().coverage` | `< threshold` | `"PORTFOLIO"` |

阈值统一 `0 < threshold <= 1`（权重/覆盖率/回撤幅度均为比例，`NUMERIC(9,6)`）。所有触发量用 `Decimal`，六位量化后比较与落库。

## 4. 风险扫描（`app/risk/engine.py`，确定性）

**输入**：`rules`（enabled 的规则）、`derived`（`performance.derive(db, as_of)` 的结果）、`points`（`portfolio_snapshots` 的 `(date, total_assets)` 序列）、`as_of: date`、`now: datetime`（注入）、`existing_dedup_keys: set[str]`、`last_event_times: dict[tuple[rule_id, subject], datetime]`。

**每个规则的计算**：

1. `POSITION_WEIGHT`：按 `instrument_id` 聚合 `derived.positions` 中 `valued=True` 的 `market_value`；`total_assets = derived.total_assets`。`total_assets <= 0` → 整规则 `skipped`（原因「总资产非正，权重无意义」），不产生数值。未估值持仓计入 `skipped` 列表（原因「无有效报价」），**不按 0 计算权重**。`weight = (mv/total_assets).quantize(Q6)`；`weight > threshold` → 事件，`trigger_value=weight`。
2. `ACCOUNT_WEIGHT`：按 `account_id` 聚合，同上口径与跳过规则。
3. `PORTFOLIO_DRAWDOWN`：`mdd = max_drawdown(points)`；`status != "OK"` → 整规则 `skipped`（`INSUFFICIENT_DATA` + `missing` 日期），不产生数值；`mdd.value < -threshold` → 事件，`trigger_value=mdd.value`。
4. `QUOTE_COVERAGE`：`derived.total_positions == 0` → 跳过（无持仓不构成数据质量风险，覆盖率定义上为 1）；否则 `coverage < threshold` → 事件，`trigger_value=coverage`。

**事件生成与幂等**：

- `dedup_key = f"{rule.id}|{subject}|{as_of.isoformat()}"`。若已在 `existing_dedup_keys` → 跳过（同日重复扫描幂等）。
- **冷却**：若 `now - last_event_times[(rule.id, subject)] < cooldown_minutes` 分钟 → 跳过（跨日重复提醒抑制）。冷却只抑制新建事件，不影响已有事件的状态。
- `message` 为中文可读文本，含规则名、主体、触发值、阈值（例：「单品种集中度超限：贵州茅台 权重 0.350000 超过阈值 0.300000」）。
- 输出 `ScanResult(created: list[EventSpec], skipped: list[SkipSpec])`；`POST /api/v1/risk/scan` 返回 `created`/`skipped`/`evaluated_rules`/`as_of`，**不写账本**。

**人工基准**（测试必须复现，`total_assets=1000`）：

- 品种 A 市值 350、B 市值 150（其余为现金 500）→ `POSITION_WEIGHT(A)=0.350000`；阈值 `0.300000` → 触发 A，不触发 B。
- 账户 X 市值 600、Y 市值 0 → `ACCOUNT_WEIGHT(X)=0.600000`；阈值 `0.500000` → 触发 X。
- 快照 `[1000, 1200, 900, 1500]` → `MDD=-0.250000`；阈值 `0.200000` → 触发（`-0.25 < -0.20`）。
- `coverage=0.500000`、阈值 `0.800000` → 触发。
- 全部为 `Decimal`，结果 `.quantize(Decimal("0.000001"))`。

## 5. 风险事件处理

- `GET /api/v1/risk/events?status=&severity=&rule_id=&limit=`：默认按 `triggered_at desc`，返回列表。
- `POST /api/v1/risk/events/{id}/acknowledge`（body 可选 `note`）：仅 `OPEN` → `ACKNOWLEDGED`；写 `audit_logs`(`risk.event.acknowledge`)。
- `POST /api/v1/risk/events/{id}/ignore`（body 可选 `note`）：仅 `OPEN` → `IGNORED`；写审计。
- 已处理事件再次操作 → `409`「该风险事件已处理」。事件只改状态，**绝不删除**（留痕）；规则修改同样留痕。
- `cooldown_minutes` 默认 1440（1 天），可配 0（不冷却）。

## 6. 风险规则管理

- `POST /api/v1/risk/rules`（201）：校验 `scope × rule_type` 合法组合、`0 < threshold <= 1`、`cooldown_minutes >= 0`；非法 → `422`/`409`「风险规则范围与类型不匹配」。写 `audit_logs`(`risk.rule.create`)。
- `GET /api/v1/risk/rules`（含 disabled）、`PATCH /api/v1/risk/rules/{id}`（可改 threshold/severity/enabled/cooldown_minutes/memo，**不可改** `scope`/`rule_type`，避免历史事件失去可解释性 → 409「规则范围与类型不可修改」）。每次改审计。
- 禁用规则 `enabled=False` 不删除，扫描时跳过。

## 7. Agent Token 与只读 scope

- `POST /api/v1/agent/tokens`（201）：`name` + `scopes: list[str]`。用 `secrets.token_urlsafe(32)` 生成明文，**只在本次响应返回一次**；库里存 `sha256(明文).hexdigest()`。`scopes` 必须属于白名单且不重复：
  `read:accounts`、`read:positions`、`read:transactions`、`read:market`、`read:performance`、`read:risk`、`read:plans`、`read:proposals`、`write:proposals`。
  含任何其它 scope（尤其 `write:ledger` / `write:trades` / `post` / `*`）→ `422`「不允许的 scope」。审计 `agent.token.create`。
- `GET /api/v1/agent/tokens`：只返回元数据（id/name/scopes/active/时间），**永不返回 token_hash 或明文**。
- `POST /api/v1/agent/tokens/{id}/revoke`：置 `active=False`、`revoked_at=now`；审计。`GET` 时仍可见（留痕）。吊销后所有网关调用 `401`。

## 8. Agent 只读查询网关

- 统一前缀 `/api/v1/agent`，**除 `POST /proposals` 外只有 GET**；无 `/post`、无 `/confirm`、无 `/reverse`、无任何账本写入端点（architecture §4「agent 只调用公开 Application Service」、database-design §5「不要把 /post 暴露为 Agent 可随意调用的写接口」）。
- 所有请求必须带 `X-Agent-Token`；校验：存在 → `active` → 未吊销 → 所需 scope 在 `scopes` 内。失败分别 `401`「Agent Token 无效」/ `401`「Agent Token 已吊销」/ `403`「Agent Token 缺少 scope：{scope}」。
- 每次调用（成功或失败）写 `agent_operations`（token_id/resource/scope/http_status/detail）；成功时更新 `last_used_at`。
- 响应统一包裹元信息（满足 agent.md §8「工具返回数据应包含数据时间、来源、是否估值/延迟、缺失字段」）：

```json
{
  "data": [ ... ],
  "meta": {
    "as_of": "2026-11-13",
    "source": "ledger|valuation|snapshots|manual-quotes|risk-rules",
    "is_estimate": false,
    "is_delayed": false,
    "missing": ["..."],
    "queried_at": "2026-11-13T12:00:00+00:00"
  }
}
```

- 资源与所需 scope、来源：

| 资源 | scope | 数据来源 | 元信息要点 |
|---|---|---|---|
| `GET /agent/accounts` | `read:accounts` | `investment_accounts` | `source=ledger` |
| `GET /agent/positions` | `read:positions` | `/api/v1/positions` 同一 Service | `source=ledger` |
| `GET /agent/transactions` | `read:transactions` | `investment_transactions` 列表（只读） | `source=ledger` |
| `GET /agent/quotes` | `read:market` | `market_quotes` + `fund_nav_history` | `source=manual-quotes`、`is_delayed` 取 `delayed` 字段、`missing` 列无报价品种 |
| `GET /agent/valuation?as_of=` | `read:market` | `performance.derive` | `source=valuation`、`is_estimate=true` 当含 ESTIMATED、`missing` 列 UNKNOWN/ESTIMATED 品种 |
| `GET /agent/summary?as_of=` | `read:performance` | `performance.derive` | `source=valuation` |
| `GET /agent/returns?as_of=` | `read:performance` | `performance` 纯函数 | `source=snapshots`、缺估值时 `missing` 列日期 |
| `GET /agent/risk-events` | `read:risk` | `risk_events` | `source=risk-rules` |
| `GET /agent/plans` | `read:plans` | `investment_plans` | `source=ledger` |
| `GET /agent/proposals` | `read:proposals` | `operation_proposals` | `source=proposals` |

- 网关只读：不新增、不修改、不删除任何账本/持仓/分录/交易表；`agent_operations` 是唯一的写入（审计日志）。

## 9. 待审批提案（Agent → 用户）

**创建（Agent 侧）**：`POST /api/v1/agent/proposals`，需 `write:proposals` scope，body：

```json
{
  "proposal_type": "DRAFT_CASH_TRANSACTION",
  "payload": {
    "transaction_type": "DEPOSIT",
    "account_id": "<uuid>",
    "business_date": "2026-11-13",
    "amount": "10000.000000",
    "memo": "Agent 建议补记一笔入金"
  },
  "expires_hours": 48
}
```

- **v1 只支持 `DRAFT_CASH_TRANSACTION`**（`DEPOSIT`/`WITHDRAW`/`ACCOUNT_TRANSFER` 三种现金草稿），不生成证券/基金交易、不处理 executions（明确写进文档，防止误以为已支持自然语言记账全类型）。其它 `proposal_type` → `422`。
- 创建时立即校验并冻结 `validation_snapshot`：`account_id` 存在、`counter_account_id` 存在且不同（转账时）、`amount > 0`、日期合法、账户名/类型快照。校验失败 → `409`「提案数据校验失败：…」，**不落库**。
- `impact_preview` 明确展示：资产（账户名）、数量（无）、价格/净值（无）、费用（无）、金额、币种、影响说明「仅生成草稿，不入账，不改变余额/持仓」。
- `expires_at = now + expires_hours`（默认 48，范围 1..720）。
- 审计 `agent.proposal.create` + `agent_operations`。

**审批（用户侧，不接受 Agent Token）**：`POST /api/v1/plans/proposals/{id}/approve`，位于用户命名空间 `/api/v1/plans/**`，**不读 `X-Agent-Token`**，因此 Agent 无法调用：

- 仅 `PENDING` 且未过期 → 可审批；`APPROVED`/`REJECTED`/`EXPIRED` → `409`「该提案不能重复审批」；`now > expires_at` → 先置 `EXPIRED` 再 `409`「提案已过期，请重新生成」。
- **重新校验**（agent.md §8「审批后重新校验数据，不可盲目执行过期提案」）：账户仍存在、`counter_account_id` 仍存在且不同、`amount>0`、`account.name/type` 与 `validation_snapshot` 一致（防账户被改名/删除后误执行）。任一不符 → `409`「提案数据已变更，拒绝审批，请重新生成」。
- 通过后调用既有 `transactions.create_transaction`（同一 Service/校验），只创建 **`status=DRAFT`** 的交易；记录 `resulting_transaction_id`；提案置 `APPROVED`。**绝不调用 confirm/post**（由用户在交易页按既有状态机完成）。审计 `proposal.approve`。
- **拒绝**：`POST /api/v1/plans/proposals/{id}/reject`（`resolution_note` 可选）→ `REJECTED`，审计 `proposal.reject`。
- `GET /api/v1/plans/proposals?status=` 用户侧列表（含 `is_expired` 计算值）；`GET /api/v1/plans/proposals/{id}` 详情。

**幂等**：重复 `approve` 因状态非 `PENDING` 被拒；`resulting_transaction_id` 唯一关联，不重复建草稿。

## 10. 投资计划（轻量）

- `POST /api/v1/plans`（201）：`name` 必填、`description`、`target_amount` 可空 → `ACTIVE`。审计 `plan.create`。
- `GET /api/v1/plans`、`GET /api/v1/plans/{id}`（含 `actions` 按 `sort_no`）。
- `POST /api/v1/plans/{id}/actions`（201）：`title`/`note`/`target_amount`/`sort_no`。审计 `plan.action.create`。
- `POST /api/v1/plans/{id}/archive`：`ACTIVE` → `ARCHIVED`，审计。重复归档 `409`。
- 计划是**决策记录**，不触发任何账务动作；不做复杂工作流、不接通知渠道。

## 11. API 一览

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST/GET | `/api/v1/risk/rules` | 用户 | 规则 CRUD（PATCH 不可改 scope/type） |
| POST | `/api/v1/risk/scan` | 用户 | 确定性扫描，幂等 + 冷却 |
| GET | `/api/v1/risk/events` | 用户 | 事件列表/筛选 |
| POST | `/api/v1/risk/events/{id}/acknowledge\|ignore` | 用户 | 处理事件（留痕） |
| POST/GET | `/api/v1/agent/tokens` | 用户 | Token 创建（明文仅一次）/列表 |
| POST | `/api/v1/agent/tokens/{id}/revoke` | 用户 | 吊销 |
| GET | `/api/v1/agent/{resource}` | Agent Token | 只读网关（9 资源 + meta） |
| POST | `/api/v1/agent/proposals` | Agent Token (`write:proposals`) | 只建 PENDING 提案 |
| GET | `/api/v1/agent/proposals` | Agent Token (`read:proposals`) | 只读自己的提案列表 |
| GET | `/api/v1/plans/proposals` | 用户 | 提案列表（含 is_expired） |
| GET | `/api/v1/plans/proposals/{id}` | 用户 | 提案详情 |
| POST | `/api/v1/plans/proposals/{id}/approve\|reject` | 用户 | 审批 → 只建 DRAFT / 拒绝 |
| POST/GET | `/api/v1/plans` | 用户 | 投资计划 |
| GET | `/api/v1/plans/{id}` | 用户 | 计划详情（含 actions） |
| POST | `/api/v1/plans/{id}/actions` | 用户 | 新增计划条目 |
| POST | `/api/v1/plans/{id}/archive` | 用户 | 归档 |

## 12. 测试要求（agent.md §9 / §12 DoD）

六类齐全：正常 / 边界 / 幂等 / 失败回滚 / 权限（等价冲正更正类，本版无账本写入故用「越权被拒」）/ 精度。必须覆盖：

1. **人工基准**：§4 四条权重/回撤/覆盖率算式精确复现（纯函数测试，无 DB）。
2. **确定性**：同输入两次 `evaluate` 输出完全一致；`now` 注入后冷却行为确定。
3. **缺失不伪装**：未估值持仓不参与权重、列 `skipped`；快照不足 → 回撤 `skipped(INSUFFICIENT_DATA)`；`total_assets<=0` 不产生数值事件。
4. **扫描幂等**：同 `as_of` 两次 scan 事件数不增；冷却窗口内跨日再 scan 被抑制；冷却过期后可再生成。
5. **规则校验**：非法 `scope×rule_type`、`threshold` 越界、PATCH 改 `scope` 被拒；修改规则写 `audit_logs`。
6. **事件处理**：acknowledge/ignore 状态流转 + 审计 + 重复处理 409 + 事件不删除。
7. **Agent 权限**：无/无效/吊销 Token → 401；缺 scope → 403；`write:ledger` 等非法 scope 创建 → 422；明文不落库/不回显；`agent_operations` 记录成功与失败。
8. **Agent 不能写账本**：Agent 网关无 POST（除 proposals）；对 `/api/v1/transactions`/`/post` 等用户端点用 Agent Token 调用 → 401/403；审批端点不接受 Agent Token。
9. **提案安全**：创建时校验失败不落库；过期/重复审批 409；账户变更后审批拒绝；**审批只生成 `DRAFT`**（断言 `status=="DRAFT"`、无 `journal_entries`、无 `position_lots` 变动）；拒绝留痕。
10. **精度**：阈值/触发值/金额六位小数 `Decimal`，无 float。
11. **六类 + 回归**：`pytest -q` 全绿、`ruff check`/`ruff format --check`/`mypy app` 干净、真实 HTTP E2E。
