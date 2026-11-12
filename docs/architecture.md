# 系统架构

## 1. 目标

构建本地优先、Agent 无关、数据可迁移的个人投资管理系统。第一版支持中国场外公募基金、场内 ETF、A 股股票和现金账户。系统负责记录、核算、分析和提醒，不负责自动交易。

## 2. 架构风格

采用模块化单体（Modular Monolith）：一个 FastAPI 应用、一个 PostgreSQL 数据库、一个前端应用；定时任务初期可与 API 进程分开运行，但共享同一业务代码和数据库。Agent 运行时复用 **octop-harness**（模型路由、工具、技能、对话检查点），经 MCP/REST 适配层对接投谱 API；MCP 是 API 的适配层，不是第二套业务逻辑，harness 不直接访问数据库。

```text
User / Web UI / Import Files / Agent
              |
       REST API / MCP Adapter
              |
       Application Services
              |
  -----------------------------------
  Accounts | Instruments | Transactions
  Ledger   | Positions   | Performance
  Market   | Risk        | Plans
  Imports  | Notifications | Audit
  -----------------------------------
              |
       PostgreSQL
              |
       Data Providers
  AKShare / Eastmoney / manual / CSV
```

数据源调用方向应由 `market_data` 模块管理，业务模块依赖标准化接口，不直接依赖第三方 SDK。

## 3. 分层职责

### API 层

负责 HTTP 路由、身份认证、输入输出 schema、错误码。不得包含复杂金融计算。

### Application Service 层

组织用例，例如 `CreateTradeDraft`、`ConfirmFundOrder`、`PostStockExecution`、`ReverseTransaction`、`ConfirmImportBatch`。负责事务边界、权限、幂等和模块协调。

### Domain 层

封装交易规则、状态机、成本计算、账务分录生成、风险规则等确定性业务逻辑。尽量不依赖 FastAPI、ORM 和外部数据源。

### Infrastructure 层

SQLAlchemy Repository、数据源 Provider、文件存储、通知渠道、定时任务等技术实现。

## 4. 模块依赖规则

- `transactions` 调用资产类型对应的业务处理器。
- `funds` 处理申购/赎回申请、确认份额和基金费率规则。
- `executions` 处理股票/ETF 成交和交易费用。
- `ledger` 负责分录生成、平衡检查、过账和冲正。
- `positions` 消费已过账事件/分录，维护可重建持仓和批次。
- `performance` 基于现金流、持仓和估值计算收益。
- `risk` 基于持仓、行情和用户规则生成风险事件。
- `agent` 只调用公开 Application Service/API，不直接访问 Repository 或数据库。

不得形成循环依赖。跨模块写操作必须通过 Service 接口。

## 5. 数据源架构

统一接口至少包括：

- `get_quote(instrument, as_of)`
- `get_daily_history(instrument, start, end)`
- `get_fund_nav(instrument, start, end)`
- `get_trading_calendar(market, start, end)`
- `get_corporate_actions(instrument, start, end)`

标准化数据需保留：供应商、供应商原始代码、采集时间、市场时间、数据类型、延迟/估值标记、复权类型、质量状态。行情数据不可覆盖交易事实。

## 6. 定时任务

第一版任务：

- 基金净值同步（按基金公布节奏）。
- 股票/ETF 日行情同步。
- 交易日历更新。
- 每日持仓和组合快照。
- 风险规则扫描。
- 通知发送和失败重试。

任务必须幂等、有运行日志、可重跑。不得假定每天都是交易日。盘中行情监控作为后续能力，第一版先支持行情源实际提供的频率。

## 7. 部署

Docker Compose 至少包含：

- `api`: FastAPI。
- `db`: PostgreSQL，持久化 volume。
- `worker`: 定时任务（可在第一阶段暂不独立部署）。
- `frontend`: React 静态资源服务（开发阶段可单独运行）。

数据库凭证通过环境变量注入，不提交真实 `.env`。提供 `.env.example`。备份策略至少包括 PostgreSQL 定期逻辑备份和恢复演练。

## 8. 非功能要求

- 单用户本地部署优先。
- 所有关键写操作事务化、幂等、可审计。
- 金融数值使用 Decimal/Numeric。
- 行情数据缺失时明确显示“未知/过期”，不能静默用旧值冒充实时数据。
- Agent/API 可单独禁用，不影响核心账本。
- 核心账本不依赖 LLM、外部 Agent 平台或商业 SaaS。
