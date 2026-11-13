# Toupu Agent Skill

> 让外部 Agent（或 MCP 客户端）知道如何安全、正确地使用投谱 Toupu 的后端 API。
> 适用范围：本系统的只读查询网关、Agent Token 鉴权、待审批提案工作流。
> 权威来源：`docs/risk-agent-rules.md`、`backend/app/agent/router.py`、`backend/app/plans/router.py`。

---

## 1. 这是什么系统

投谱 Toupu 是个人投资资产记账与决策系统。账本是**唯一事实来源**（ledger is source of truth）：所有金额用定点小数（NUMERIC，六位），借贷必须平衡，已过账数据不可修改，只能冲正。

- 普通交易（存取款、证券买卖、基金申赎、分红）由用户在 UI/API 中录入 → 确认 → 过账。
- **Agent 不能直接写入正式账本**。Agent 只能：① 只读查询已派生的数据；② 创建"待审批提案"，由用户明确审批后才生成草稿交易。

## 2. 接入方式

两种等价的接入面（底层同一个鉴权与只读网关）：

| 接入面 | 用途 |
|---|---|
| REST API `/api/v1/agent/*`（Bearer/Header `X-Agent-Token`） | 直接 HTTP 调用 |
| MCP server（stdio/http，由本系统启动时暴露） | 其他 Agent 以 MCP tools/resources 调用 |

两者都通过 **Agent Token** 鉴权，按 **scope 白名单** 授权。

## 3. 鉴权

```
Authorization: Bearer <token>    # 或
X-Agent-Token: <token>
```

- Token 由用户在「设置 → Agent Token」页创建；**明文仅在创建时返回一次**，库里只存 sha256。
- Token 可随时吊销；吊销或失效的 Token 返回 `401`。
- **每次调用（成功或失败）都会写入 `agent_operations` 审计表**，含 token、资源、scope、HTTP 状态、时间。

## 4. Scope 白名单

Token 只能被授予以下 scope 的子集：

| scope | 允许访问 |
|---|---|
| `read:accounts` | 投资账户列表 |
| `read:positions` | 持仓（账户×品种聚合） |
| `read:transactions` | 交易流水（最近 100 条） |
| `read:market` | 行情/基金净值、估值明细 |
| `read:performance` | 收益汇总、XIRR/TWR/最大回撤 |
| `read:risk` | 风险事件 |
| `read:plans` | 投资计划 |
| `read:proposals` | 待审批提案 |
| `write:proposals` | 创建提案（**唯一写端点**） |

> 不在白名单内的 scope（如 `write:ledger`、`post:*`）一律 `422` 拒绝。Agent **永远没有** `post / confirm / reverse` 任何账本操作的权限。

## 5. 只读资源（GET）

所有只读端点返回统一结构：

```json
{
  "data": [ { ...record }, ... ],
  "meta": {
    "as_of": "2026-11-13",
    "source": "ledger | valuation | snapshots | manual-quotes | risk-rules | proposals",
    "is_estimate": false,
    "is_delayed": false,
    "missing": [],
    "queried_at": "2026-11-13T16:00:00+00:00"
  }
}
```

`meta` 字段是 **安全边界的一部分**：调用方必须展示数据时间（`as_of`/`queried_at`）、来源、是否估值（`is_estimate`）、是否延迟（`is_delayed`）、缺失字段（`missing`）。**缺失数据不伪装**——未估值持仓不会被当作 0。

| 端点 | scope | 说明 |
|---|---|---|
| `GET /api/v1/agent/accounts` | `read:accounts` | 账户列表 |
| `GET /api/v1/agent/positions` | `read:positions` | 持仓聚合 |
| `GET /api/v1/agent/transactions` | `read:transactions` | 交易流水（限 100） |
| `GET /api/v1/agent/quotes` | `read:market` | 行情+基金净值 |
| `GET /api/v1/agent/valuation?as_of=` | `read:market` | 逐持仓估值（含 ESTIMATED/UNKNOWN） |
| `GET /api/v1/agent/summary?as_of=` | `read:performance` | 总资产/现金/市值/累计盈亏/覆盖率 |
| `GET /api/v1/agent/returns?as_of=` | `read:performance` | XIRR / TWR / 最大回撤 |
| `GET /api/v1/agent/risk-events` | `read:risk` | 未处理/历史事件 |
| `GET /api/v1/agent/plans` | `read:plans` | 投资计划 |
| `GET /api/v1/agent/proposals` | `read:proposals` | 提案列表 |

## 6. 提案工作流（唯一的写操作）

`POST /api/v1/agent/proposals`（需 `write:proposals`）：

```json
{
  "proposal_type": "DRAFT_CASH_TRANSACTION",
  "payload": {
    "transaction_type": "DEPOSIT" | "WITHDRAW" | "ACCOUNT_TRANSFER",
    "account_id": "<uuid>",
    "counter_account_id": "<uuid>",   // 仅转账
    "business_date": "2026-11-13",
    "amount": "100.000000",
    "memo": "optional"
  },
  "expires_hours": 48
}
```

- **只能生成现金类草稿提案**。证券/基金/成交明细不在 v1 支持范围。
- 创建时即冻结 `validation_snapshot`（账户存在、转账对手存在且不同、金额 > 0、账户名/类型快照），并返回 `impact_preview`（资产/数量/价格/费用/金额/币种 + "仅生成草稿，不入账"）。
- 提案 `PENDING` 状态，过期（默认 48h）自动 `EXPIRED`。
- **审批不在 Agent 命名空间**：`POST /api/v1/plans/proposals/{id}/approve` 不读取 `X-Agent-Token`，因此 Agent 无法调用。审批通过后只生成 `DRAFT` 交易，绝不 `confirm`/`post`。

## 7. 安全红线（Agent 必须遵守）

1. 不持有、不猜测账本写权限；任何 `/post` `/confirm` `/reverse` 都不对 Agent 开放。
2. 提交提案前，先读相关只读资源，用真实数字填充 `payload`，不要把未估值持仓当 0。
3. 展示给用户的数据必须带 `meta`（时间/来源/估算/延迟/缺失）。
4. 提案只是建议；是否入账由用户明确审批决定。
5. Token 明文仅首次可见，落库即哈希；不要在日志/对话里回显明文。

## 8. MCP server 工具/资源清单（对外提供时）

- **resources（只读）**：`toupu://accounts`、`toupu://positions`、`toupu://transactions`、`toupu://quotes`、`toupu://valuation`、`toupu://summary`、`toupu://returns`、`toupu://risk-events`、`toupu://plans`、`toupu://proposals`（每个带 `meta` 元数据）。
- **tools（受限）**：`create_cash_proposal`（唯一写工具，等价于 `POST /proposals`）。
- 每个 tool/resource 调用都按调用方 Token 的 scope 鉴权；缺 scope 返回 403。
