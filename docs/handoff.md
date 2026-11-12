# 交接文档（HANDOFF）

> 最后更新：2026-11-12。给接手的开发者/Agent 看的工作状态说明。
> 开始任何代码修改前，先读 [`agent.md`](agent.md)（最高优先级约束），再读本文。

## 1. 一句话状态

**M0（骨架）、M1（基础账本）、M2（证券交易）、M3（场外基金：申购/赎回两段式确认 + 分红/红利再投资，前后端整段完成）已提交**：后端 43 passed（M1 19 + M2 7 + M3 17）、ruff/mypy 干净、E2E 实测通过；前端 `tsc`/`vite build` 通过、真实 HTTP 全链路 E2E 通过。之后按 §9 顺序继续 M4 → M5 → M6 + 界面审查。

## 2. 项目定位（摘要，详见 agent.md / README）

投谱 Toupu：个人投资资产管理系统的第一版，中国市场，支持场外公募基金、场内 ETF、A 股、券商/基金平台账户。

不可违反的核心约束：

- **账本是事实来源**；持仓/收益/快照都是可重建的派生结果。
- **已入账不可改/删**，只能冲正；草稿可改，确认后按状态机流转。
- **金融数值禁止 float**：Python `Decimal`、PostgreSQL `NUMERIC`、API 用十进制字符串。
- **借贷必须平衡**，过账前强制校验；过账幂等；重要操作留审计。
- **场外基金与场内证券使用不同业务处理器**，不得混用成交逻辑。
- **入账原子化**：交易状态、分录、持仓变动同一事务。

## 3. 仓库结构与运行方式

```
backend/          FastAPI + SQLAlchemy 2.x + Alembic + pytest
  app/{accounts,instruments,transactions,executions,positions,funds,ledger,audit,core,db}
  alembic/versions/   0001 基线(13表) … 0004 instrument_id … 0005 line_no … 0006 基金字段/lot_origin
  tests/
frontend/         React 19 + TS + Vite（视觉约束见根目录 frontend-design.md）
docs/             产品/领域/账务/数据库/实施计划/页面规格
agent.md          开发 Agent 强约束
docker-compose.yml  只起数据库；--profile full 才容器化 API
```

**开发模式**（当前采用，避免每次改镜像）：

```bash
docker compose up -d db          # postgres:18，宿主机端口 5433
cd backend && uv sync
cd backend && uv run alembic upgrade head      # 或直接启动 API，lifespan 自动迁移
cd backend && uv run uvicorn app.main:app --reload   # 8000
cd frontend && npm install && npm run dev            # 5173，/api 代理到 8000
```

**验证命令**（在 `backend/`）：

```bash
uv run pytest -q
uv run ruff check app tests && uv run ruff format --check app tests
uv run mypy app
```

注意：

- pytest 依赖真实数据库（读 `backend/.env`，指向 localhost:5433），conftest 会自动跑迁移。
- 本机 brew 的 postgres 已停用，别抢 5433。
- `npm run build` 用 `tc --noEmit && vite build`；**shell 管道会吞退出码**（zsh 无 pipefail），判断成败要用 `${pipestatus[1]}`。
- `ghcr.io` 拉镜像 TLS 超时（网络问题），完整容器化镜像重建暂不可用，本地进程开发不受影响。

## 4. 已完成（git 历史）

| 提交 | 内容 |
|---|---|
| `a2b0831` | M1 开工：Alembic 基线迁移（13 表）+ 启动自动迁移 + 账户/品种 API + 测试 |
| `03071d8` | **M2 证券交易**：成交明细、移动加权平均成本、持仓查询、已实现损益、买入冲正、0005 分录行序 + 26 测试 |
| `b6cccd2` | **M2 前端闭环**：交易页证券录入（证券买卖 + 成交明细 + 品种选择）+ 持仓页接 `/api/v1/positions` |
| `b4ebed5` | **M3 后端**：申购/赎回两段式确认（净值/份额/费用守恒）、现金分红、红利再投资、FUND/DIVIDEND_REINVEST 批次、0006 迁移、17 测试 |
| 本次提交 | **M3 前端闭环**：基金申请/确认录入页（守恒即时校验）、详情分录展示、`/funds` 路由与导航 |
| `272bab8` | 前端 v0.1：设计令牌（亮/暗）、应用壳导航、总览/账户/品种页（真实 API）、占位页、Toast/Dialog/徽标/骨架屏 |
| `480e547`、`12d73bc` | UI 文案去行话（「标的」→「投资品种」）；账户类型收紧为券商/基金平台（迁移 0002）；开发模式改本地进程 |
| `41f3e22` | 产品三件套（product/user-flow/page-spec）+ frontend-design.md |
| `ce8c7a8` | **M1 核心账本**：交易状态机 API + PostingService（借贷平衡/幂等/冲正/审计）+ 19 测试 |
| `230a9d7` | **交易页前端**：新建/确认/过账/冲正/取消 + 分录详情 + 总览近期交易与待办 |

已实现的能力清单：

- 账户/品种 CRUD，market+code 唯一（重复 409）。
- 交易：`POST/GET /api/v1/transactions`，`/confirm` `/post` `/reverse` `/cancel`；DRAFT→CONFIRMED→POSTED，已入账只能冲正。
- PostingService：入金/出金/转账分录；借贷平衡强制校验；`journal_entries.transaction_id` 唯一保证过账幂等；冲正生成 REVERSAL 反向分录并保留原记录。
- 审计：confirm/post/reverse/cancel 写 `audit_logs`。
- 统一错误体 `{"error": {code, message}}`，`BusinessError` 全局 handler（默认 409）。
- 证券：股票/ETF 买入卖出（可多笔成交）、费用、持仓批次与移动加权平均成本、部分卖出、已实现盈亏、`GET /api/v1/positions`。
- 前端：账户、品种、交易三个功能页 + 总览，Swiss 极简，信任蓝 `#1E40AF`，红涨绿跌，tabular-nums。

## 5. M2（证券交易）后端 —— 已全绿，已提交（03071d8）

`git status`（提交前留档）：

```
M  backend/app/ledger/models.py
M  backend/app/ledger/service.py
M  backend/app/main.py
M  backend/app/transactions/models.py
M  backend/app/transactions/router.py
?? backend/alembic/versions/0004_transaction_instrument.py
?? backend/alembic/versions/0005_journal_line_order.py
?? backend/app/executions/
?? backend/app/positions/
?? backend/tests/test_securities.py
?? docs/handoff.md
```

各文件职责：

| 文件 | 内容 |
|---|---|
| `alembic/versions/0004_transaction_instrument.py` | `investment_transactions.instrument_id` |
| `alembic/versions/0005_journal_line_order.py` | `journal_lines.line_no`，保证分录行按过账顺序确定性返回 |
| `app/executions/models.py` | `TradeExecution`：序号/数量/价格/毛额/费用/净额 |
| `app/positions/service.py` | `PositionLot`、`PositionLotDisposal` 模型 + `apply_buy`/`apply_sell`：移动加权平均成本，FIFO 消耗批次，出库成本 = 单位成本 × 卖出量（清仓时取剩余总成本，尾差归零），剩余批次按新单位成本重算 |
| `app/positions/router.py` | `GET /api/v1/positions`：按账户×品种聚合持仓（quantity/total_cost/unit_cost + 品种代码名称） |
| `app/ledger/service.py` | 证券科目 `get_or_create_security`、`get_or_create_income`；`_security_buy_lines`（借证券/贷现金，费用入成本）、`_security_sell_lines`（借现金净额/贷证券出库成本/差额记已实现损益）；买入冲正删除未消耗批次；卖出冲正暂不开放；分录行写 `line_no` |
| `app/transactions/router.py` | 7 种交易类型；`ExecutionIn` 成交入参；服务端算 gross/net/total（买入 net=gross+费，卖出 net=gross−费）；detail 输出 executions；按 `line_no` 返回分录行 |
| `app/main.py` | 挂载 positions router |
| `tests/test_securities.py` | 7 个验收测试（见下「测试覆盖」） |

测试覆盖（全部通过；后端全量 26 个测试 = M1 19 + M2 7）：

- 买入 2 笔成交（100@10 费 5 + 100@12）→ 总成本 2205、200 股、单位成本 11.025；
- 卖 50@11 费 5 → 净额 545、出库成本 551.25、已实现亏损 6.25；
- 清仓 150@11.5 → 出库成本 = 剩余总成本 1653.75（尾差归零）、已实现收益 71.25；
- 超卖 → 409「持仓不足」；卖出冲正 → 409「暂不开放」；未被消耗的买入可冲正并清空持仓；
- 证券交易缺 `instrument_id`/成交明细、品种不存在、现金业务带成交 → 422/404。

## 6. M2 设计决策与已知取舍

- 成本口径：**移动加权平均**（买入按笔形成批次，卖出 FIFO 消耗批次数量，出库成本 = 单位成本 × 卖出量；清仓时出库成本 = 剩余总成本，尾差归零，剩余批次按新单位成本重算成本，Σ 精确）。
- 卖出损益：`realized = net_amount − cost_out`；盈利贷记「已实现收益」，亏损借记「已实现损失」。
- 卖出净额可能小于出库成本 → 已实现损失，分录仍平衡（借现金 + 借损失 = 贷证券）。
- **买入冲正**：仅当批次未被消耗时允许，冲正时删除批次（`shortcut` 注释在 `ledger/service.py`）。
- **卖出冲正暂不开放**：需还原批次消耗轨迹，代码里有 `shortcut:` 注释，出现真实需求再升级。
- 转账、入金等现金业务不允许携带成交明细（422）；证券交易必须带 `instrument_id` 且至少一笔成交（422）。
- 金额一律服务端计算，不信任前端传入的净额。
- 回填 `instrument_id` 到冲正交易，保证追溯。
- 分录行加 `line_no`，冲正时按原行序镜像，接口返回顺序确定（前端/测试可稳定断言）。

## 6.5 M3（场外基金）实现口径 —— 详见 docs/ledger-rules.md §15

账务语义先落文档（agent.md §10）：`docs/ledger-rules.md` 追加 §15，再写代码。

**生命周期**：申购/赎回/红利再投资两段式 `DRAFT(PENDING) → CONFIRMED(confirmation_status=CONFIRMED，写 fund_confirmations) → POSTED`；确认数据到达前 `post_transaction` 强制拦截「基金交易未完成确认，不能过账」。通用 `/confirm` 护栏挡住基金申请（必须走基金确认接口录净值/份额）。现金分红 `CASH_DIVIDEND` 创建即 `CONFIRMED`，无需确认；`FUND_CONVERT` 第一版不开放；失败可 `POST /orders/{id}/fail` 置 `FAILED/CANCELLED`，无账务影响。

**字段语义**：申购 `apply_amount` = 实际扣款总额（含申购费），确认时守恒 `apply_amount == confirmed_amount + fee_amount`；赎回 `apply_shares` = 申请份额、`apply_amount` 可空（确认前无实际金额，不猜测）；现金分红 `apply_amount` = 现金到账金额。

**分录模板**（基金处理器在 `app/funds/handlers.py`，与证券处理器完全分离，复用 ledger 科目 + positions 成本底层）：

| 类型 | 借方 | 贷方 | 持仓批次 |
|---|---|---|---|
| 申购 | 证券 = `apply_amount` | 现金 = 同额 | `lot_origin=FUND`，成本含申购费 |
| 赎回 | 现金 = `confirmed_amount − fee_amount`（净到账） | 证券 = 移动加权平均出库成本，差额 `REALIZED_GAIN/LOSS` | 减仓，清仓尾差归零 |
| 现金分红 | 现金 = `apply_amount` | `DIVIDEND_INCOME`「现金分红收入」 | 不增份额 |
| 红利再投资 | 证券 = `confirmed_amount` | `DIVIDEND_INCOME`（不重复现金） | `lot_origin=DIVIDEND_REINVEST`，按确认净值增份额 |

**API**：`POST/GET /api/v1/funds/orders`、`GET /api/v1/funds/orders/{id}`、`POST /api/v1/funds/orders/{id}/confirm|fail`；过账/冲正/取消复用 `/api/v1/transactions/{id}/post|reverse|cancel`。申购/红利再投资冲正删除未消耗批次；赎回冲正暂不开放；现金分红无批次可直接冲正。

**迁移 0006**：`fund_order_details` 加 `apply_shares NUMERIC(20,6)`、`apply_amount` 放宽为可空；`position_lots.lot_origin` CHECK 扩为 `('TRADE','OPENING_BALANCE','CORPORATE_ACTION','FUND','DIVIDEND_REINVEST')`。

**验收**：`tests/test_funds.py` 17 个测试（正常/守恒/护栏/过账前拦截/部分赎回亏损/两批次清仓尾差归零/现金分红/红利再投资/超赎/冲正/幂等/fail/校验/列表详情/六位精度），全量 43 passed；ruff/mypy 干净；`/tmp/m3_e2e.py` 真实 HTTP 全链路 30 断言通过。

## 6.6 M3 前端形状（本次提交）

- `frontend/src/api/funds.ts`：`FundTxnType`/`FUND_TYPES`/`FUND_TYPE_LABELS`/`TWO_STAGE_TYPES`/`isTwoStageType`；`FundOrder`、`FundConfirmation`、`FundEntryLine`、`FundOrderDetail`（含 `confirmation` + `entry`）、`FundOrderCreate`、`FundConfirmationIn`；`fundsApi.list/get/create/confirm/fail`，BASE `/api/v1/funds/orders`。
- `frontend/src/pages/Funds.tsx`（`/funds`，导航「基金」）：列表（账户/类型/状态三筛选）；新建申请 Dialog 按类型动态显示 `apply_amount`/`apply_shares`/`expected_fee`/`platform`/`memo`；录入确认 Dialog（日期/净值/份额/金额/费用）对申购做 `apply_amount == confirmed_amount + fee_amount` 即时校验 banner；标记失败、冲正（赎回不给冲正按钮）、详情（申请 + 确认 + 分录三个表）。过账/冲正/取消复用 `transactionsApi`；品种下拉用 `instrumentsApi.list("FUND")`。
- `frontend/src/App.tsx`：加 `Landmark` 图标 + NAV「基金」项 + `/funds` 路由。
- 验收：`npx tsc --noEmit` = 0，`npx vite build` = 0（2127 modules）；`/tmp/m3_fe_e2e.py` 按前端真实请求形状（含 `memo:null`、`platform`、通用 `/post`/`/reverse`、现金分红不确认）真实 HTTP 全链路通过。

## 7. 还没做

| 事项 | 说明 |
|---|---|
| ~~持仓页前端~~ | 已完成（b6cccd2） |
| ~~交易页支持证券录入~~ | 已完成（b6cccd2）：证券买卖 + 成交明细 + 品种选择 |
| ~~M3 场外基金（后端）~~ | 已完成（b4ebed5）：两段式申购/赎回 + 确认守恒 + 现金分红 + 红利再投资 + 17 测试 |
| ~~M3 场外基金（前端）~~ | 已完成（本次提交）：`/funds` 申请/确认页 + 守恒校验 + 分录详情 |
| M4 导入 | CSV/Excel、字段映射、去重、预览确认、期初资产 |
| M5 行情与收益 | Provider/Adapter、净值行情、快照、已实现/未实现盈亏、XIRR/TWR、回撤 |
| M6 风险与 Agent | 风险规则、确定性提醒、Agent 只读查询与草稿提案 |
| 界面审查 | 用户定的流程：产品→UI/UX→前端实现→`impeccable` 审查；审查阶段尚未开始 |

## 8. 环境与工具坑（踩过的）

- **shell 管道吞退出码**：`npm run build | tail` 失败也会"成功"，用 `${pipestatus[1]}` 判断。
- Playwright 工具只能在 `execute` 内用 `tools.playwright.*` 调用；`browser_take_screenshot` 必须传 `scale`。
- 截图/快照落在仓库 `.playwright-mcp/` 与根目录 `accounts.png`（已提交，无害）。
- 测试与 dev 共用同一个库（`toupu`），测试会留下数据（账户名带随机后缀区分）。
- ruff 配置忽略 `B008`（FastAPI `Depends` 模式）。
- 金额序列化走 `Decimal` → JSON 字符串，测试断言要按 `"2205.000000"` 六位小数写。

## 9. 建议的接手顺序

1. ~~M2 前端闭环~~（已完成 b6cccd2）、~~M3 场外基金后端~~（已完成 b4ebed5）、~~M3 前端闭环~~（已完成本次提交）。
2. 下一步：按里程碑 M4 导入 → M5 行情/收益 → M6 风险/Agent；或先插入界面审查阶段（`impeccable`）。
3. 每次改动后保持：`pytest` 全绿 → `ruff`/`mypy` 干净 → 实测 → 提交。
