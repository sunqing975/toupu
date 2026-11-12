# 投谱 Toupu · Personal Investment System

**投谱**（Toupu）——个人投资资产管理与决策系统：记录、核算、决策与计划。第一版面向中国市场，支持场外公募基金、场内 ETF、A 股股票及现金账户；支持手动录入和 Excel/CSV 导入；提供完整投资账本、持仓核算、收益分析、风险提醒和 Agent 接口。

## 项目原则

1. 账本是事实来源，Agent 对话记忆不是账本。
2. 交易业务、实际成交、资金/资产分录分层建模。
3. 场外基金与交易所证券使用不同业务处理器，不强行统一交易细节。
4. 已入账记录不可直接修改或删除；更正通过冲正和重新入账完成。
5. 所有金融数值使用 `Decimal` 和 PostgreSQL `NUMERIC`，禁止使用二进制浮点数进行金额核算。
6. 风险判断由确定性代码完成，LLM 只负责解释、研究和提出待审批建议。
7. 第一版不接入自动下单，不允许 Agent 绕过用户确认写入正式账本。
8. 采用模块化单体，不为追求“微服务化”提前拆服务。

## 第一版范围

- 场外公募基金：申购、赎回、转换、分红、红利再投资、份额确认、净值历史。
- 场内 ETF：买入、卖出、成交、费用、行情、分红。
- A 股股票：买入、卖出、成交、费用、分红、送转股等公司行为。
- 账户：证券账户、基金平台账户、银行/现金账户、账户间转账。
- 账本：复式记账、初始资产导入、冲正、审计。
- 导入：手动录入、Excel/CSV 导入、字段映射、预览、去重、人工确认。
- 分析：持仓、成本、已实现/未实现盈亏、现金余额、资产快照、XIRR/TWR（分阶段实现）。
- 风险：资产级、账户级、组合级规则和通知。
- Agent：只读查询、自然语言录入草稿、待审批提案、定时复盘。

## 第一版明确不做

- 自动交易/自动下单。
- 港股、美股及多币种交易核算（数据模型可预留，不实现）。
- 复杂量化回测、策略自动执行。
- 多用户、多租户、券商账户实时同步。
- 依赖必须付费的中间商才能运行的 Agent 连接链路。

## 技术栈

- Backend: Python 3.12+、FastAPI、Pydantic、SQLAlchemy 2.x、Alembic
- Database: PostgreSQL
- Frontend: React、TypeScript、Vite
- Import: openpyxl、pandas（只用于文件解析，不用 float 做金融核算）
- Scheduler: 初期 APScheduler 或独立轻量 Worker
- Agent runtime: **octop-harness**（模型路由、工具、技能、对话检查点），通过 MCP/REST 适配层对接投谱 API
- Deployment: Docker Compose
- Tests: pytest

具体依赖版本在实施时锁定到兼容版本，并提交 lock 文件。

## 文档导航

- [`agent.md`](agent.md)：开发 Agent 的强约束，开始编码前必须阅读。
- [`docs/architecture.md`](docs/architecture.md)：系统架构和模块边界。
- [`docs/domain-model.md`](docs/domain-model.md)：领域模型、实体关系和状态流转。
- [`docs/ledger-rules.md`](docs/ledger-rules.md)：账本、成本、费用和收益核算规则。
- [`docs/database-design.md`](docs/database-design.md)：数据库设计约定和初始表清单。
- [`docs/implementation-plan.md`](docs/implementation-plan.md)：开发顺序、里程碑和验收标准。

## 开发启动建议

1. 先阅读 `agent.md` 和全部 `docs/` 文档。
2. 建立 FastAPI + SQLAlchemy + Alembic + PostgreSQL 最小工程。
3. 先实现账户、标的、交易草稿、交易确认、复式账本和冲正。
4. 先通过自动化测试，再增加前端、行情和 Agent。
5. 每次实现新业务前，先补充业务规则和测试案例，不允许直接凭猜测写计算逻辑。

## 重要声明

本项目是个人投资记录、核算、研究和风险提醒工具，不是证券投资建议服务，也不是自动交易系统。行情和估值数据可能延迟或存在错误；所有投资决策由用户自行作出。
