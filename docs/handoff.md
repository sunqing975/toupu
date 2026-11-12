# 交接文档（HANDOFF）

> 最后更新：2026-11-12。给接手的开发者/Agent 看的工作状态说明。
> 开始任何代码修改前，先读 [`agent.md`](agent.md)（最高优先级约束），再读本文。

## 1. 一句话状态

**M0（骨架）、M1（基础账本）、交易页前端已完成并提交；M2（证券交易）后端已修复、测试全绿（M1 19 + M2 7 = 26 passed）、ruff/mypy 干净、curl 实测核对 §5 数值一致，并已提交；M2 前端闭环（证券录入 + 持仓页）待做**。

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
  app/{accounts,instruments,transactions,executions,positions,ledger,audit,core,db}
  alembic/versions/   0001 基线(13表) … 0004 instrument_id … 0005 journal_lines.line_no
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
| `272bab8` | 前端 v0.1：设计令牌（亮/暗）、应用壳导航、总览/账户/品种页（真实 API）、占位页、Toast/Dialog/徽标/骨架屏 |
| `480e547`、`12d73bc` | UI 文案去行话（「标的」→「投资品种」）；账户类型收紧为券商/基金平台（迁移 0002）；开发模式改本地进程 |
| `41f3e22` | 产品三件套（product/user-flow/page-spec）+ frontend-design.md |
| `ce8c7a8` | **M1 核心账本**：交易状态机 API + PostingService（借贷平衡/幂等/冲正/审计）+ 19 测试 |
| `230a9d7` | **交易页前端**：新建/确认/过账/冲正/取消 + 分录详情 + 总览近期交易与待办 |
| 本次提交 | **M2 证券交易**：成交明细、移动加权平均成本、持仓查询、已实现损益、买入冲正、0005 分录行序 + 26 测试 |

已实现的能力清单：

- 账户/品种 CRUD，market+code 唯一（重复 409）。
- 交易：`POST/GET /api/v1/transactions`，`/confirm` `/post` `/reverse` `/cancel`；DRAFT→CONFIRMED→POSTED，已入账只能冲正。
- PostingService：入金/出金/转账分录；借贷平衡强制校验；`journal_entries.transaction_id` 唯一保证过账幂等；冲正生成 REVERSAL 反向分录并保留原记录。
- 审计：confirm/post/reverse/cancel 写 `audit_logs`。
- 统一错误体 `{"error": {code, message}}`，`BusinessError` 全局 handler（默认 409）。
- 证券：股票/ETF 买入卖出（可多笔成交）、费用、持仓批次与移动加权平均成本、部分卖出、已实现盈亏、`GET /api/v1/positions`。
- 前端：账户、品种、交易三个功能页 + 总览，Swiss 极简，信任蓝 `#1E40AF`，红涨绿跌，tabular-nums。

## 5. M2（证券交易）后端 —— 已全绿，待提交

`git status`（提交前）：

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

## 7. 还没做

| 事项 | 说明 |
|---|---|
| 持仓页前端 | 后端 `/positions` 已就绪，页面未做 |
| 交易页支持证券录入 | 现有前端表单只有入金/出金/转账，买卖股票/ETF 的成交明细表单未做 |
| M3 场外基金 | 申购/赎回申请、确认净值与份额、费用、分红与红利再投资 |
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

1. 交易页增加证券录入（股票/ETF 买卖 + 成交明细表单），做持仓页接 `/api/v1/positions`，前端闭环后 M2 才算可见可用。
2. 按里程碑顺序推进 M3 → M4 → M5 → M6；或先插入界面审查阶段（`impeccable`）。
3. 每次改动后保持：`pytest` 全绿 → `ruff`/`mypy` 干净 → 实测 → 提交。
