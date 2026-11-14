# 交接文档（HANDOFF）

> 最后更新：2026-11-14（含 §6.17 前端设计系统级精修）。给接手的开发者/Agent 看的工作状态说明。
> 开始任何代码修改前，先读 [`agent.md`](agent.md)（最高优先级约束），再读本文。

## 1. 一句话状态

**M0~M6 前后端整段完成并提交**；**界面审查（`impeccable`）已完成**；**M7 Agent 框架 Phase 1-4 已完成并提交**；**按 WeKnora 对齐的 Agent 架构重做（后端 Phase A 5304768 + 前端 Phase B 7cb3ed3）已完成并提交**；**用户二次反馈 Phase C（5291491：历史会话持久化 + 正经对话框 + 对话框内换模型 + 设置水平 Tabs + 技能管理页）已完成并提交**：后端 **154 passed**、ruff/mypy 干净（70 files）；前端 `tsc`/`vite build` 0（2144 modules）+ 真实 HTTP E2E 18 断言全绿。**前端设计系统级精修（`redesign-existing-projects`）已完成**（本次提交）：自托管 Geist 变量字体（此前 IBM Plex Sans 从未加载）+ 令牌重写 + 精修层 + 总览 hero 主卡 + meta/favicon；`tsc`/`vite build` 0（2146 modules）+ headless Chrome DOM 实测通过，详见 §6.17。Phase C 落地 0013 迁移（agent_conversations/agent_messages 两表，agent_id/model_id 故意用 TEXT 不加 FK，删 Agent/模型后历史仍可查）、`/api/v1/agent/conversations` CRUD、chat 每轮问答自动落库 + 最近 20 条历史注入、`ChatIn.model_id` 对话框临时覆盖（优先级 > Agent 绑定 > 默认 > 最新）、`PATCH /definitions/skills/{key}` 全局技能总开关（停用后对所有 Agent 不注入工具）；前端 `/agent` 重写为左历史会话 + 右正经对话框（顶部模型下拉）、`/settings` 三块改水平 Tabs、新增 `/skills` 技能管理页（按 4 分类卡片 + 启停）、菜单加「技能」。M7 早期含系统 skill 文档、对外 MCP 服务（只读资源 + 提案工具，X-Agent-Token 鉴权）、模型配置 CRUD、OpenAI 兼容分析会话（`/agent/chat`）、挂载外部 MCP（通用客户端）。当前 `git status` 干净。

## 1.1 最新修正：真实技能与会话归档（2026-11-14）

- 历史会话不再提供 DELETE，0014 增加 archived_at；POST archive/restore 幂等，归档消息保留，前端直接操作无确认框，支持查看归档与恢复。
- 技能纠偏：原16项其实是 function tools。新增独立 SKILL.md 指令包目录、导入/编辑/启停界面，内置 toupu-assistant 与 portfolio-review；初始目录+load_skill按需加载正文。现阶段只支持单文件，不执行上传脚本、不支持附件安装。旧工具权限配置保留兼容。
- 真实模型故障已复现：普通请求200，16工具请求502；原因为属性内 required 布尔值非法。修正 JSON Schema 后同一真实端点请求200。
- **本次回归事故**：旧 tests/test_agent_models.py 会 DELETE FROM agent_models；运行全套时删除了用户真实配置（原 GPT6.1-sol / 724ai.org / gpt-6.1-sol）。原密钥未输出且无法从现有审计恢复，需用户重新配置。破坏性测试已去除，conftest 现强制独立 toupu_test 数据库，禁止与开发库同名。不得把测试模型误称为真实联调成功。
- 规则详见 agent-skill-packages.md。本次不改任何账务语义。

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
  app/{accounts,instruments,transactions,executions,positions,funds,imports,opening_balances,market_data,performance,snapshots,ledger,audit,core,db}
  alembic/versions/   0001 基线(13表) … 0004 instrument_id … 0005 line_no … 0006 基金字段/lot_origin … 0007 导入表/期初明细 … 0008 行情/快照表
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
| `77db678` | **M3 前端闭环**：基金申请/确认录入页（守恒即时校验）、详情分录展示、`/funds` 路由与导航 |
| `5b80ace` | **M4 后端**：CSV/Excel 上传预览/校验/去重、人工确认单事务过账、OPENING_BALANCE 处理器与期初汇总批次、0007 迁移（含模板种子）、19 测试 |
| `3d56967` | 文档：同步 handoff —— M4 后端已完成，记录 §6.7 导入/期初口径与踩坑 |
| `0fa2a63` | **M4 前端闭环**：导入批次上传/预览/错误定位/人工确认/取消页 + `/imports` 路由 |
| `d93ce0c` | **M5 后端**：MANUAL 行情/净值录入、估值覆盖状态、双口径派生、XIRR/TWR/MDD（Decimal 实现）、快照幂等重建、0008 迁移、27 测试 |
| `67e7c5b` | 文档：同步 handoff —— M5 后端已完成，新增 §6.9 公式与口径 |
| `95d2984` | **M5 前端闭环**：行情与收益页（估值明细/行情净值录入/快照重建）+ XIRR/TWR/MDD 指标卡 + `/market` 路由 |
| `21efd98` | **M6 风险/Agent/计划**：确定性风险引擎与事件（冷却/幂等）+ 规则管理 + Agent Token(sha256)/只读网关/操作审计 + 提案审批只生成 DRAFT + 轻量计划 + 0009 迁移、32 测试；前端 `/risk` + `/plans` 与 E2E 修复 |
| `029a58a` | 界面审查（impeccable）收尾：补 `.btn--ghost` 样式、仪表盘真实数据、占位诚实化、货币符号按 currency |
| `3f8241e`、`6df6382` | M7 账本只读端点 + 前端账本页/设置页 + 端口改 5180 |
| `c21980e` | M7 Phase 1-2：系统 skill 文档 + 对外 MCP 服务（10 只读资源 + create_proposal 工具，X-Agent-Token 鉴权）+ 0010 迁移 + resources 重构 |
| `a75c89a` | M7 Phase 3：模型配置 CRUD + OpenAI 兼容分析会话（`/agent/chat`）+ 前端 `/agent` 页 + 中文别名 display_name（0011 迁移） |
| `eec8a5c` | M7 Phase 4：挂载外部 MCP（通用客户端 stdio/http）+ 前端 CRUD + chat 注入外部知识 + `/{id}/test` |
| `5e428ac` | Agent 分析页对话式重构（参考 WeKnora 对话范式：消息气泡 + 输入条 + 分析依据面板） |
| `5304768` | **WeKnora 对齐 Phase A（后端）**：完整技能运行时（16 技能 / `chat_with_tools` 工具循环）+ Agent 一等实体 CRUD + 内置「投谱助手」幂等种子 + 0012 迁移 + 148 测试 |
| `7cb3ed3` | **WeKnora 对齐 Phase B（前端）**：`/agent` 重写为 Agent 卡片列表 + 编辑器（技能按分类勾选）/ 分析会话去 as_of；`/settings` 收纳模型配置 / 对外 MCP 访问凭证（原 Agent Token 改名）/ 挂载外部 MCP、删知识库空态；助手置顶菜单；tsc/vite build 0 + 23 断言 E2E 全绿 |
| `5291491` | **用户二次反馈 Phase C**：0013 迁移（会话/消息持久化）+ `/agent/conversations` CRUD + chat 自动落库/历史注入/对话框内 model_id 覆盖 + `PATCH /definitions/skills/{key}` 全局技能总开关；前端 `/agent` 左历史+右正经对话框（顶部模型下拉）、`/settings` 水平 Tabs、新增 `/skills` 技能管理页；154 passed / ruff / mypy / tsc / build 全绿 + 18 断言 E2E |
| 本次提交 | **前端设计系统级精修（`redesign-existing-projects` 技能）**：自托管 Geist/Geist Mono 变量字体（此前 IBM Plex Sans 从未加载）、重写 tokens.css（单一强调色/暖中性表面层级/着色阴影/动效令牌，保留全部旧变量名）、global.css 追加精修层（display 字阶/负字距、侧栏 tint+指示条、顶栏毛玻璃、卡片深度、按钮 hover 位移+按压 scale、focus 环、平滑滚动、reduced-motion）、总览页 hero 主卡（深墨底+品牌光晕+资产构成条，打破 4 等分白卡）、index.html 补齐 description/theme-color/favicon/color-scheme；tsc/vite build 0（2146 modules，字体打包）+ headless Chrome DOM 实测 |
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
- 场外基金：`/api/v1/funds/orders` 两段式申购/赎回确认、现金分红、红利再投资、FUND/DIVIDEND_REINVEST 批次。
- 导入与期初资产：`/api/v1/imports`（模板/批次上传/预览/确认/取消），OPENING_BALANCE 期初现金与期初持仓（期初汇总批次，不伪造成交）。
- 行情与收益：`/api/v1/market`（行情/净值录入 + 估值覆盖状态）、`/api/v1/performance`（派生汇总 + XIRR/TWR/MDD 状态）、`/api/v1/snapshots`（幂等重建）；快照是可删除重建的派生结果。前端 `/market` 估值明细/录入/快照重建/收益指标卡。
- 风险与 Agent：`/api/v1/risk`（规则 CRUD、确定性扫描、事件确认/忽略）、`/api/v1/agent`（Token 管理与只读网关、提案创建）、`/api/v1/plans`（计划/行动项、提案审批/拒绝）；Agent 只读、提案审批只生成 DRAFT 不入账。
- 功能页（前端）：总览、助手、持仓、交易、基金、行情、导入、账本、风险、计划、账户、投资品种、设置（13 项导航；助手置顶，账本/设置均已实现，无占位）。
- 前端：Swiss 极简（Geist 自托管变量字体），信任蓝 `#2748c8`，红涨绿跌，tabular-nums；亮/暗主题跟随系统（详见 §6.17 设计系统精修）。

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

## 6.7 M4 导入与期初资产实现口径（5b80ace）—— 详见 docs/ledger-rules.md §16

账务语义先落文档（agent.md §10）：`docs/ledger-rules.md` 追加 §16，再写代码。

**状态机**（agent.md §7）：上传 → 原始行保存 → 解析/标准化 → 校验 → 重复检测 → 预览 → 人工确认 → 正式入账。上传只写 `import_batches`/`import_records`（`raw`/`raw_headers` JSONB 原样保留），**绝不直接写正式账本**；只有 `/confirm` 才建 `OPENING_BALANCE` 并过账，整批单事务原子化（任一行失败整批回滚、`db.rollback()`）。批次 `DRAFT → CONFIRMED|CANCELLED`，`CONFIRMED` 后重复确认幂等直接返回。

**去重**：文件级 SHA-256（同模板同 hash 且非 CANCELLED → 409「该文件已导入过」）；业务级 `dedup_key`（`external_id` 优先，否则 `OB|CASH|…` / `OB|POS|…`，金额数量先 `quantize(0.000001)` 再拼）；三路查重（批次内 + 已确认批次 IMPORTED 行 + `investment_transactions.idempotency_key`）标 `DUPLICATE`，确认只过账 `VALID`；`idempotency_key="import:"+sha256(dedup_key)` 兜底（列 VARCHAR(100)）。

**期初分录**（`app/opening_balances/handlers.py`，与证券/基金处理器分离，复用 `get_or_create_external` 的 OPENING_BALANCE 平衡科目）：期初不是历史买入、不产生现金流出、不伪造成交日期、不记为 DEPOSIT。

| 行类型 | 借方 | 贷方 | 持仓批次 | `total_amount` |
|---|---|---|---|---|
| `CASH` | 现金 = 金额 | 外部资金平衡（OPENING_BALANCE 科目） | 无 | 金额 |
| `POSITION` | 证券 = 账面成本 | 外部资金平衡 | `lot_origin=OPENING_BALANCE`，`open_date=business_date`，`unit_cost=total_cost/quantity` 服务端推导 | 账面成本 |

`cost_source`/`valuation_date`/`row_kind`/`quantity`/`total_cost` 存 `opening_balance_details`。冲正：方向翻转；POSITION 行校验批次未被消耗后删批次，CASH 行无批次直接冲正（`_needs_lot_check` 按明细 `row_kind` 判断，不能盲并 `LOT_OPENING_TYPES`）。

**错误定位**：每条 `{row_no, field, message}`（表头第 1 行、首数据第 2 行）；必填列缺失/行类型非法/金额非正/日期错误/账户不存在/品种(market+code)不存在均给中文原因。有 `ERROR` 行整批拒绝确认（409）；`DUPLICATE` 跳过不阻止；至少 1 条 `VALID`。支持 CSV（utf-8-sig/gbk）与 Excel(.xlsx/.xlsm，openpyxl)，本版仅 OPENING_BALANCE 模板。

**API**：`GET /api/v1/imports/template`、`POST/GET /api/v1/imports/batches`（multipart `file`）、`GET /api/v1/imports/batches/{id}`、`POST /api/v1/imports/batches/{id}/confirm|cancel`。模板/13 字段映射由 0007 迁移种子写入，空库可直接导入。通用交易端点拒绝 `OPENING_BALANCE`（`TxnType` 仅 7 种 → 422）。

**迁移 0007**：`import_templates`、`import_field_mappings`、`import_batches`（部分唯一索引 `uq_import_batches_file`）、`import_records`、`opening_balance_details`。

**验收**：`tests/test_imports.py` 19 个测试（预览不写账本/期初分录与批次/六位精度/中文别名/Excel/错误定位/修正重传/缺列/空文件与非法扩展名/通用端点护栏/业务键去重/文件哈希去重/跨批次去重/确认幂等/整批回滚/取消重传/现金与持仓冲正/已消耗批次拒绝/列表详情 404），全量 **62 passed**；ruff check/format、mypy（openpyxl 用 `[[tool.mypy.overrides]] ignore_missing_imports`）干净；`/tmp/m4_e2e.py` 真实 HTTP 全链路通过（含六位精度 `24.988256`、重复确认幂等、同文件 409）。

**踩坑**：① 0007 用 `op.execute` 原生 DDL，`ImportFieldMapping` ORM 多写了 `created_at` 导致 `UndefinedColumn` 500 → ORM 必须逐列对齐 DDL；② `autoflush=False` 下 `OpeningBalanceDetail` 必须先 `db.flush()` 再 `post_transaction`，否则处理器查不到明细报「期初交易缺少明细」。

## 6.8 M4 前端形状（0fa2a63）

- `frontend/src/api/imports.ts`：`ImportTemplate`/`ImportBatch`/`RowError`/`ImportRecord`/`BatchDetail`；状态标签 `BATCH_STATUS_LABELS`/`RECORD_STATUS_LABELS`；13 列 `TEMPLATE_COLUMNS`/`COLUMN_LABELS` 与 `sampleCsv()`（可下载示例）；`importsApi.template/list/get/confirm/cancel` 走 `api<T>`，**`upload` 用原生 `fetch` + `FormData`**（不能走 `api()`，它会强制 `Content-Type: application/json` 覆盖浏览器 multipart boundary），错误体仍按 `{error:{code,message}}` 解析成 `ApiError`。
- `frontend/src/pages/Imports.tsx`（`/imports`，导航「导入」已存在，原来接 Placeholder）：顶部 banner 明确「上传不会立即记账」+ 可展开模板 13 列说明/下载示例 CSV；批次列表（状态筛选、行/错误/重复计数、确认/取消/详情按钮）；上传 Dialog（文件 + 备注）；确认入账 / 取消 Dialog；详情预览 Dialog（批次状态徽标、`raw_headers`、逐行状态 `RecordBadge`、`rowSummary` 摘要、错误定位「第 N 行 · 字段：原因」、`dedup_key`、可导入时显示「确认入账」）。行状态用现有 `badge--*` 语义色，不新增 CSS。
- `frontend/src/App.tsx`：`/imports` 从 `Placeholder` 换成 `<Imports />`。
- 验收：`npx tsc --noEmit` = 0，`npx vite build` = 0（2129 modules）；`/tmp/m4_fe_e2e.py` 按前端真实请求形状（multipart `file`+`memo`、`?status=` 过滤、`FormData` 上传、错误行定位、取消、同文件 409）真实 HTTP 11 项全通过。

## 6.9 M5 行情与收益实现口径（d93ce0c）—— 详见 docs/ledger-rules.md §17

账务/公式语义先落文档（agent.md §10/§12）：`docs/ledger-rules.md` 追加 §17（含 XIRR/TWR/MDD 公式、正负号约定、人工基准、缺失行情处理），再写代码。

**范围与边界**（§17.1/§17.2）：第一版只实现 `MANUAL` Provider（显式录入，保留 `provider/collected_at/market_time/data_type/quality_status/adjust_type`），`MarketDataProvider(ABC)` 预留可替换接口；行情是估值输入，不覆盖账本成交价；正式净值 `OFFICIAL` 与盘中估值 `ESTIMATED` 分开，ESTIMATED 不用于核算；报价超 `stale_days`(默认 7) 标 `STALE`、无报价 `UNKNOWN`，**缺失或过期绝不静默显示为实时或用 0 冒充**；收益指标估值覆盖不全返回 `INSUFFICIENT_DATA` 而非看似合理的数字。

**派生口径**（`app/performance/service.py`）：方向 `DEBIT=+ / CREDIT=−`；`cash` = Σ CASH 科目分录行、`realized` = Σ REALIZED_GAIN CREDIT − Σ REALIZED_LOSS DEBIT、`dividend_income` = Σ DIVIDEND_INCOME CREDIT（冲正分录方向翻转故自动抵消）；`quantity` = Σ `position_lots.remaining_quantity>0`、`book_cost` = Σ 同源批次 `total_cost`，**双口径交叉校验**：另算 SECURITY 科目 DEBIT−CREDIT，不一致抛 `ValueError` 拒绝生成快照；`market_value` 仅对有效报价（FRESH/STALE）持仓计入并给 `coverage`；`total_assets = Σcash + Σmarket_value`。

**关键取舍**（§17.2）：因 `reduce_position` 部分卖出删批次、清仓不写 disposal，`rebuild` 第一版只按当前实时余额生成快照，`snapshot_date` 是保存标签而非历史回放参数；明确不支持任意历史日账面余额精确回溯、不伪造。XIRR 现金流取不可变 `investment_transactions`（status=POSTED 且非冲正交易，含 business_date），期末估值取当前总资产；TWR/MDD 取已保存 `portfolio_snapshots` 序列。

**外部现金流边界**（§17.3）：DEPOSIT 是（投入为负）、WITHDRAW 是（收回为正）、OPENING_BALANCE 期初资本基数（负）；ACCOUNT_TRANSFER 否（内部转账）、证券买卖/基金申赎/分红/再投资/费用 否；现金分红已含期末估值不再单列。

**公式**（`app/performance/formulas.py`，纯函数、无 DB/HTTP、Decimal 分数指数无 float）：
- XIRR：`NPV(r)=Σ CF_i/(1+r)^((d_i−d_0)/365)=0`，`r∈(−0.9999,10]` 二分 200 次、`|NPV|<1e-10`，同号无解返回 `None`（`NO_SOLUTION`）。人工基准 A `−100000@2026-01-01 / +110000@2027-01-01 → 0.100000`，B `…+50000@2027-01-01/+66000@2028-01-01 → 0.100000`（`−100000+50000/1.1+66000/1.21=0`）。
- TWR：`r_i=V_i^-/V_{i-1}−1`、`V_i=V_i^-+F_i`、`TWR=Π(1+r_i)−1`；输入 = `portfolio_snapshots` 序列 + 外部现金流，每个现金流日期取 `snapshot_date<=d_i` 最近快照作 `V_i^-`，`as_of` 当天须有快照作 `V_T^-`，缺估值或 `V_{i-1}<=0` → `INSUFFICIENT_DATA`（列缺失日期、不插值）。人工基准 `100000→110000→143000` + `20000@06-30` → `0.210000`；无现金流 `100000→115000` → `0.150000`。
- MDD：`MDD=min_t(V_t/max_{s<=t}V_s − 1)`；基准 `[100,120,90,150,120] → −0.250000`。

**API**：`POST/GET /api/v1/market/quotes`（股票/ETF 日行情，OFFICIAL 只接受 `adjust_type=NONE`，重复 409）、`POST/GET /api/v1/market/navs`（仅 FUND 品种）、`GET /api/v1/market/valuation`（逐持仓 quote_status + market_value + unrealized）、`GET /api/v1/performance/summary`、`GET /api/v1/performance/returns`（XIRR/TWR/MDD 带 `status/value/missing/reason`）、`POST /api/v1/snapshots/rebuild`（同日先删后建幂等）、`GET /api/v1/snapshots`、`GET /api/v1/snapshots/{date}/positions`。

**迁移 0008**：`market_quotes`、`fund_nav_history`、`position_snapshots`、`portfolio_snapshots` 四表（逐列列清单见 `0008_market_snapshots.py`）；ORM 逐列对齐原生 DDL（沿用 0007 踩坑：不能凭习惯多写 `created_at`）。

**验收**：`tests/test_performance.py` 15 个纯函数测试（XIRR A/B/C 基准、NPV 零点、同号无解、现金流同日合并、TWR 两基准 + 三种缺失、MDD 两基准 + 无回撤、六位精度）；`tests/test_market_snapshots.py` 12 个 HTTP 测试（行情/净值录入边界、FRESH/STALE/UNKNOWN/ESTIMATED 四态、缺失报价不静默为 0、快照幂等重建、不改动账本、收益指标结构、XIRR 覆盖不全返回状态、转账不计外部现金流）。全量 **89 passed**；`ruff check/format`、`mypy`（47 source files）干净；`/tmp/m5_e2e.py` 真实 HTTP 76 断言通过。

**测试注意**：测试与 dev 共用 `toupu` 库，`derive()` 是全库派生（全局 200+ 持仓），故 M5 HTTP 测试只断言自己创建的行/效应，绝不断言全局总金额；覆盖率必然 <1 → `/returns` 的 XIRR 恒为 `INSUFFICIENT_DATA`。

## 6.10 M5 前端形状（95d2984）

- `frontend/src/api/market.ts`：行情/收益/快照三套 API 的类型与封装。`QuoteOut/QuoteIn/NavOut/NavIn/QuoteView/ValuationRow/ValuationOut/SummaryOut/MetricOut/ReturnsOut/PositionSnapshot/PortfolioSnapshot/RebuildOut`；常量 `QUOTE_STATUS_LABELS`（FRESH 有效报价 / STALE 已过期 / UNKNOWN 无报价 / ESTIMATED 盘中估值）、`QUOTE_STATUS_TONE`、`DATA_TYPE_LABELS`、`DATA_QUALITY_LABELS`、`METRIC_STATUS_LABELS`；`marketApi.quotes/createQuote/navs/createNav/valuation/summary/returns/snapshots/snapshotPositions/rebuild`，`?as_of=&stale_days=` 统一查询参数。
- `frontend/src/pages/Market.tsx`（`/market`，导航「行情」）：顶部日期 + `staleDays`(7/3/30) + 刷新；`loadDerived()` 用 `Promise.all([valuation, summary, returns])` 随日期/阈值重算。8 个 `StatCard`（现金/市值/总资产/账面成本 + 已实现/未实现/分红/报价覆盖）、3 个 `MetricCard`（XIRR/TWR/MDD，OK 时 `×100` 显示 %，否则显示 `METRIC_STATUS_LABELS` + `reason`/`missing`/`peak→trough`，绝不显示看似合理的假数字）。三个 Tab：估值明细表（逐持仓报价状态徽标 + 数量/成本/报价/市值/浮盈 + 合计）、行情录入（「录入行情」「录入净值」两个 Dialog，`NAV` 仅列 FUND、`QUOTE` 仅列非 FUND，`data_type` 可选 OFFICIAL/ESTIMATED，顶部 banner 强调「仅作为估值输入」）、组合快照（重建快照 Dialog + 快照列表 + 快照明细 Dialog）。
- `frontend/src/App.tsx`：lucide 加 `LineChart`、`NAV` 加「行情」项、`/market` 路由接 `<Market />`（原 9 项导航扩为 10 项）。
- 验收：`npx tsc --noEmit` = 0，`npx vite build` = 0（2131 modules，366.08 kB）；`/tmp/m5_fe_e2e.py` 按前端真实请求形状（字符串金额、`data_type` 显式、`provider_code`、重复 409、FUND nav 限制、rebuild 幂等、staleDays 变体）真实 HTTP **50 断言全通过**。

## 6.11 M6 风险/Agent/计划实现口径（本次提交）—— 详见 docs/risk-agent-rules.md

- 迁移 `0009`：`risk_rules`、`risk_events`（`dedup_key` UNIQUE）、`investment_plans` / `investment_plan_actions`、`agent_tokens`（只存 sha256）、`agent_operations`（只追加审计，失败也留痕）、`operation_proposals`。`gen_random_uuid()`（PG13+ 内置）。
- 风险引擎 `app/risk/engine.py`：**纯函数**，无 DB/HTTP/随机/LLM，`now` 可注入。合法组合仅 `INSTRUMENT×POSITION_WEIGHT`、`ACCOUNT×ACCOUNT_WEIGHT`、`PORTFOLIO×PORTFOLIO_DRAWDOWN`、`PORTFOLIO×QUOTE_COVERAGE`；阈值 `0<threshold<=1`。无有效报价的持仓**跳过并给出原因**，不当 0 计；总资产非正、无持仓、快照不足均跳过而非硬算。同一 `rule_id|subject|as_of` 幂等（同日重复扫描不重建），冷却时间内的触发跳过。金额/权重六位量化。
- 风险 API：`POST/GET /api/v1/risk/rules`、`PATCH /rules/{id}`（只能改阈值/级别/开关/冷却/备注，**不能改 scope/rule_type**）、`POST /scan`、`GET /events`、`POST /events/{id}/acknowledge|ignore`。事件只改状态不删除。
- Agent：`/api/v1/agent/tokens`（创建只返回一次明文、列表/吊销）、只读网关 `/accounts /positions /transactions /quotes /valuation /summary /returns /risk-events /plans /proposals`，统一 `X-Agent-Token` + scope 白名单（9 个 `read:*` / `write:proposals`）。每次调用（含 401/403）写 `agent_operations`；成功更新 `last_used_at`。Agent 对用户写接口（confirm/post 等）无权限，审批接口忽略 Agent Token。
- 提案：Agent 只能 `POST /agent/proposals` 建 PENDING（只支持现金类 DEPOSIT/WITHDRAW/ACCOUNT_TRANSFER），创建时校验并冻结 `validation_snapshot`/`impact_preview`；过期时间为创建 +24h。用户 `POST /plans/proposals/{id}/approve` 前**重新校验**账户仍存在且名称/类型未变、金额仍 >0；通过后只调用既有 `create_transaction` 生成 **DRAFT**，绝不 confirm/post、不写分录；`reject` 记录原因；重复审批 409，过期置 EXPIRED。
- 计划：`/api/v1/plans` 轻量决策记录（计划 + 有序行动项），明确不触发任何账务动作。
- 测试：`tests/test_risk_agent.py` 23 个测试函数 / 31 个用例，覆盖四类规则触发与跳过、无报价不按 0 计、扫描幂等、规则组合与不可变字段、事件确认/重复拒绝、Token 缺失/无效/缺 scope/明文不落库、网关审计、Agent 无法过账、审批只生成 DRAFT、非法载荷不落库、过期/重复审批/拒绝、全部 scope 可读与提案可写。
- 全量验证：`pytest` **121 passed**（M6 32 个）、`ruff check/format` 干净、`mypy app` 58 文件无问题。

## 6.12 M6 前端形状（本次提交）

- `frontend/src/api/risk.ts`：风险/提案/计划三套 API 类型与封装。常量 `SCOPE_LABELS`、`RULE_TYPE_LABELS`、`SEVERITY_LABELS`、`EVENT_STATUS_LABELS`、`PROPOSAL_STATUS_LABELS`、`TXN_LABELS`、`SCOPE_RULE_TYPES`（与后端合法组合一致）；`riskApi.rules/createRule/updateRule/scan/events/acknowledge/ignore`、`plansApi.proposals/approveProposal/rejectProposal/plans/plan/createPlan/addAction/archivePlan`。
- `frontend/src/pages/Risk.tsx`（`/risk`，导航「风险」）：顶部扫描日期 + 「立即扫描」，展示上次扫描的新增事件与**跳过原因明细**（缺失数据不伪装）；Tab 1 事件表（状态/级别筛选、触发值/阈值按百分比、确认/忽略 Dialog 带备注、已处理显示备注）；Tab 2 规则表（范围/类型/阈值/级别/冷却/启用开关/编辑）。规则新建时按 scope 过滤可选 rule_type；编辑时 scope/rule_type 只读（后端也不可改）。阈值 UI 按 % 输入，提交转六位小数字符串。
- `frontend/src/pages/Plans.tsx`（`/plans`，导航「计划」）：Tab 1 提案表（状态筛选、摘要、到期时间、已过期标记、查看/批准/拒绝）。批准 Dialog 明确提示「只生成交易草稿（DRAFT），不入账，请到交易页确认并过账」，可填备注；详情展示 impact_preview 与原始 payload/validation_snapshot。Tab 2 计划表（名称/说明/目标金额/状态/创建时间），新建计划 Dialog、详情 Dialog（执行条目列表 + 新增条目表单 + 归档按钮）。
- 组件：`StatusBadge` 增加风险事件状态（OPEN/ACKNOWLEDGED/IGNORED）、级别（INFO/WARNING/CRITICAL）、提案（PENDING/APPROVED/REJECTED/EXPIRED）、计划 ARCHIVED；`global.css` 增加 `.banner--warning`（复用 `--color-warning`）。
- **E2E 抓到的真实 bug（已修）**：`PATCH /risk/rules/{id}` 把 `Decimal` 阈值原样写进审计 JSONB → 500。修复为审计用 `model_dump(mode="json")`，规则赋值仍用原始 Decimal；新增回归测试 `test_rule_patch_valid_fields_and_audit`（121 个测试的来源）。
- **E2E 抓到的测试脆弱点（已修）**：`test_reverse_flow` 依赖「最近 100 条已入账交易」找冲正单，数据积累后被截断；改为按 `account_id` 过滤。
- 验收：真实 HTTP 脚本 `.../m6_fe_e2e.py` **36 断言**：规则创建/组合校验/不可改字段/有效 PATCH、扫描触发与同日幂等、事件确认与重复 409、Token 明文不回显/无 Token 401/缺 scope 403、只读网关、提案非法类型 422、审批只生成 DRAFT（`entry is null`）且重复审批 409、拒绝留痕、计划条目与归档 409、吊销后 401。

## 6.13 界面审查（`impeccable`，本次提交）

- 用 `impeccable` 技能对 `frontend/src` 做 Operate 模式审查（单上下文降级：本会话无 spawn_agent、二进制下载挂起、无浏览器截图工具）。设计健康初评 Acceptable（24/40）。修复项：
  - **P0 `.btn--ghost` 缺失样式**：原 `global.css` 未定义该类，但 Risk/Plans/Market/Dialog 共 9 处引用（标签切换、弹窗关闭 X、忽略/拒绝/归档按钮）→ 渲染成无边框纯文本，与 bordered 按钮不一致、点击可发现性差。已补 `.btn--ghost`（透明边框 + 静音色，hover 反白底色）。
  - **P1 仪表盘真实数据**：`Dashboard.tsx` 四个 stat-grid 卡片原硬编码 `—` + 「随 M1/M2 上线」提示，但 M1/M2/M5 早已完成。改为调 `marketApi.summary(as_of=今天)` 取真实「总资产/现金合计/持仓市值/累计盈亏（已实现+未实现，红绿着色）」；缺报价时显示「市值为估值」提示；账户/品种卡改为展示「持仓 X/Y 已估值」。
  - **P1 占位诚实化**：`/ledger`、`/settings` 原 `Placeholder milestone="M1"/"M6"` 显示「随 X 里程碑上线」，但后端 M1/M6 已完成、只是前端页面未做 → 误导。改为传 `title`/`description`，文案改为「此前端页面尚未实现，相关功能可从其它入口或 API 访问」（不伪装里程碑状态）。
  - **P3 货币符号**：`Plans.tsx` 提案标题硬编码 `¥${amount}`，但 impact_preview 含 `currency` 字段。改为按 `impact.currency` 取符号（CNY→¥），未带则回退 ¥。Funds/Transactions 的 CNY 特定展示保留（场外基金/证券交易均为人民币域）。
  - **P2 帮助引导**：Risk/Plans 已有页面级微文案（确定性规则/缺失不伪装、Agent 只建提案不入账、计划不触发账务）；EmptyState 已覆盖首次使用引导，无需新增 tooltip 组件。
- 验收：`npx tsc --noEmit` 退出 0；`npx vite build` 退出 0（2134 modules，dist 397.97 kB）。

## 6.14 M7 Agent 框架 Phase 1-4（本次提交）

用户自定义目标（m03572/m03707）：理想 Agent 不是单页聊天，而是一套框架 —— ① 系统 skill 让 agent 知道怎么用 ② 本系统对外提供 MCP（其他 agent 可查询/生成投资计划）③ 系统内可配置模型 ④ 专门会话拿当前数据分析 ⑤ 用 MCP 对接外部知识库（如 weknora），需支持 mcp 挂载 + 对外提供 mcp 服务。

- **Phase 1（skill 文档）**：`docs/agent-skill.md`（§1-§8：系统说明/接入/鉴权/scope 白名单/只读资源 meta/提案工作流/安全红线/MCP 工具资源清单）。
- **Phase 2（对外 MCP 服务）**：`app/agent/resources.py`（10 个只读资源函数，各返回 `(data, Meta)` + `RESOURCE_CATALOG`）；`app/agent/mcp_server.py`（`build_mcp_server` + `mount_mcp` + `AgentTokenMiddleware` + `current_agent_token` ContextVar；10 个只读 `@mcp.resource` 委托 resources，1 个 `@mcp.tool create_proposal`（write:proposals + validate_payload，只建 PENDING））；主 app 在 lifespan 显式 `mcp_server._session_manager.run()`（FastAPI `Mount` 不触子应用 lifespan）。挂载到 `/mcp/`。MCP SDK 锁 `mcp==1.30`（v2 重命名 FastMCP→MCPServer 且不兼容）。真实 HTTP E2E 已验证鉴权与工具调用。
- **Phase 3（模型配置 + 分析会话 + 前端 Agent 页）**：
  - 迁移 `0010`：`agent_models`（`display_name` Text 可空，`0011` 增补）、`agent_mcp_servers`（Phase 4 用）。
  - `app/agent/models_router.py`：`/api/v1/agent/models` CRUD（密钥只写不读、默认模型互斥、部分更新保留密钥）。
  - `app/agent/llm.py`：`chat(db, messages, model_id, temperature)` 调 OpenAI 兼容 `/chat/completions`（httpx）；无配置→`RuntimeError("尚未配置可用的模型")`。
  - `app/agent/chat_router.py`：`POST /api/v1/agent/chat`（拼只读快照 summary/valuation/returns/positions/risk_events/proposals + 用户问题 + 系统提示，模型只能看到只读数据、不直接写账本；`model_name` 优先 `display_name`）。
  - 前端：`/agent` 页（对话区：选模型/as_of/提问；模型配置区：表格/新建编辑/删除，密钥 password 不回显、留空不修改）；`api/models.ts`、`api/chat.ts`；`App.tsx` 加 NAV 与路由；`Settings.tsx` 收敛为「知识库/外部 MCP」诚实空态。
- **Phase 4（挂载外部 MCP）**：
  - `app/agent/mcp_client.py`：`fetch_external_knowledge(db)` 连接所有 enabled 的 `agent_mcp_servers`（stdio/http 通用客户端），只读取资源 + 列出工具名，**只读、不调用会修改外部系统的工具**；单个服务失败被吞掉并标注，绝不中断会话；`test_connection` 供前端「测试连接」。
  - `app/agent/chat_router.py`：`_snapshot` 之后把外部知识拼进提示词第二段（标注「管理员已挂载的外部知识库」），并保留原生 snapshot 解析。
  - `app/agent/mcp_router.py`：`/api/v1/agent/mcp-servers` CRUD（transport 仅 stdio/http；stdio 需 command、http 需 url；密钥无字段）+ `POST /{id}/test`（超时 20s）。
  - 前端：`api/mcpServers.ts` + `Settings.tsx` 新增「外部 MCP 服务」区块（列表/添加/编辑/删除/测试连接），替代原「知识库/外部 MCP」空态；知识库单独诚实空态。
- 验收：`uv run ruff check/fmt` 全绿、`uv run mypy app` Success 67 files、`uv run pytest -q` 138 passed（含 `test_agent_mcp.py` 5 用例：CRUD/transport 校验/test 连接容错/chat 注入外部知识/fetch 无服务返回空）；前端 `tsc`/`vite build` 均 0（2141 modules）。

## 6.15 按 WeKnora 对齐的 Agent 架构重做（5304768 + 本次提交）

用户 m04757 反馈：① 应有两个 Agent（「投谱助手」默认挂载本系统技能 + 通用 Agent 挂不同投资分析技能），要有**技能管理**；② Agent 分析页不是一个对话框；③ 外部 MCP 不该在 Agent Token 下面；④ Agent Token 应是「别人连本系统 MCP 时的 key，用来限制工具使用」（对外 MCP 客户端凭据，语义本就如此，需改名归类）；⑤ 知识库说了不做，页面不体现；⑥ agent 分析页置顶菜单；⑦ 去掉年月日（as_of）输入框；⑧ 管理模型放设置。用户 m04819 确认「技能=完整运行时、Agent=内置+自定义 CRUD、开始落地」。参考 WeKnora 源码 `frontend/src`：`views/agent/AgentList.vue`（Agent 卡片）+ `AgentEditorModal.vue`（model_id/system_prompt/allowed_tools/mcp_services/skills_selection）、`components/skill` + `api/skill`（技能目录 catalog 注册/安装）、MCP 在 integrations/settings、`apiKeyScope.ts` 表明 API Key 是对外访问凭据（scope 限资源范围）、无 as_of 控件。

- **后端 Phase A（5304768）**：
  - 迁移 `0012`：`agent_skills`（key/name/description/icon/category/builtin/enabled/config JSONB）、`agent_definitions`（key/name/description/icon/is_builtin/avatar_color/system_prompt/model_id/enabled_skill_keys JSONB/mcp_server_ids JSONB + 时间戳）；`app/agent/models.py` 加 `AgentSkill`/`AgentDefinition` ORM（逐列对齐 DDL）。
  - `app/agent/skills.py`（完整技能运行时）：**16 个技能** = 数据 10（`read_accounts/positions/transactions/quotes/valuation/summary/returns/risk_events/plans/proposals`，委托 `resources.py`）+ 分析 4（`analyze_portfolio_concentration` 算占比/HHI、`analyze_returns_attribution`、`scan_risk_events`、`draft_rebalance_plan` 只返回骨架不建提案）+ 外部知识 1（`read_external_knowledge` 调 `mcp_client.fetch_external_knowledge`）+ 写入受控 1（`create_draft_proposal`：validate_payload → 建 OperationProposal status=PENDING，**绝不入账**）。每个 `_Skill.tool_schema()` 产出 OpenAI function-calling schema；`execute_skill(db, key, arguments)` 返回 JSON 串，未知技能/异常结构化返回不抛。
  - `app/agent/definitions_router.py`（`/api/v1/agent/definitions`）：`ensure_builtin` 幂等种子内置 `toupu-assistant`（`enabled_skill_keys`=全部 16、`system_prompt` 含「投谱」）；CRUD（POST 重复 key 409「Agent key 已存在」、DELETE 内置 409「内置 Agent 不可删除」）；`GET /skills` 静态路由**必须排在 `/{agent_id}` 前**；`_valid_skill_keys` 用 `skills_mod.SKILLS` 过滤非法技能 key；`model_id` 非法 422。
  - `app/agent/llm.py` 加 `chat_with_tools(db, messages, tool_schemas, tool_executor, *, model_id, temperature, max_rounds)`（function-calling 工具循环：tool_calls 逐个回填 role:"tool" 消息，直至无 tool_calls 返回 content）。
  - `app/agent/chat_router.py` 重写：`ChatIn{question, agent_id}`（**去掉 as_of/model_id/预拼快照**）；`_resolve_agent`（缺省 toupu-assistant、未知 404「Agent 不存在」）→ `_resolve_model`（agent.model_id → is_default → 最新）→ `_tool_schemas/_tool_executor`（闭包调 `skills.execute_skill`）→ `llm.chat_with_tools`；无模型 400「尚未配置可用的模型（设置 → Agent 模型配置）」。`ChatOut{answer, agent_id, agent_name, model_id, model_name}`。
  - 验收：`uv run pytest -q` 148 passed / `ruff check` + `format` 全绿 / `mypy app` Success 69 files；修 4 个旧 chat 契约 stale 测试（fake_chat 新签名、断言工具循环注入、去掉 as_of）。
- **前端 Phase B（本次提交）**：
  - 新增 `api/agents.ts`：`AgentSkill`/`AgentDefinition`/`In`/`Patch` + `SKILL_CATEGORY_LABELS`（data 数据查询 / analysis 分析诊断 / knowledge 外部知识 / action 写入受控）+ `agentsApi(list/get/skills/create/update/remove)`；改 `api/chat.ts` 的 `ChatRequest{question, agent_id?}` / `ChatResponse{answer, agent_id, agent_name, model_id, model_name}`。
  - 重写 `pages/Agent.tsx`（~600 行）：**Agent 一等实体卡片列表**（对齐 AgentList，avatar 6 色、内置 tag、技能数、编辑/删除、选中态）+ 选中 Agent 的「已启用技能」摘要 + 分析会话（消息气泡/typing/建议 chips/分析依据面板，**无 as_of、无模型选择**）+ Agent 编辑器 Dialog（name/key/description/system_prompt/model_id 下拉/avatar 颜色/技能按分类分组勾选）。模型管理迁入设置；切换 Agent 清空会话；`models.length===0` 提示「设置 → 模型配置」。
  - 重写 `pages/Settings.tsx`（~540 行）：① 模型配置（从 Agent 页迁入，display_name 别名、密钥 password 留空不修改、默认互斥）；② **对外 MCP 访问凭证**（原「Agent Token」改名，文案明确 `/mcp/` + `X-Agent-Token` + scope 决定可调用工具、明文仅一次、库只存哈希）；③ 挂载外部 MCP 服务（Plug 图标，测试/编辑/删除）；**删掉知识库诚实空态卡片**，全文不再出现「Agent Token」措辞。
  - `App.tsx`：NAV 首行加「助手」置顶、删底部「Agent」；`styles/global.css` 补 `.agent-grid/.agent-card*/__*`、`.skill-pills`、`.skill-picker/skill-group/skill-item`、`.color-row/.color-dot`、`.code-inline`、`.alert--info`、`h3.card__title`（用 h3 选择器而非改 `.card__title`，避免破坏 Dashboard/Market 用 div 的统计小标签）。
  - 验收：`npx tsc --noEmit` 0、`npx vite build` 0（2142 modules，`index-DVu8nHYy.js 433.14 kB`）；`/tmp/m7_phaseB_e2e.py` 真实 HTTP 23 断言全绿（definitions/skills 形状、16 技能 4 分类、create_draft_proposal、模型密钥不回显、Agent CRUD/内置不可删/技能过滤/model_id 绑定、chat 未知 agent 404、vite 服务 /agent 与 /settings）。

## 6.16 用户二次反馈 Phase C（本次提交）—— 历史会话 / 正经对话框 / Tabs / 技能管理

用户 m05823 反馈：① 历史会话也要存；② 会话这里为啥不是一个正经的对话框，模型最好在对话框可换；③ 设置里模型/token/mcp 是垂直的，token 内容太多就拉很长；④ 还需要一个技能的管理界面。四条全部落地。

- **后端 0013（会话持久化 + 技能总开关）**：
  - 迁移 `0013_agent_conversations.py`（revision=0013, down_revision=0012）：`agent_conversations`(id UUID, title TEXT, agent_id TEXT, model_id TEXT, created_at/updated_at TIMESTAMPTZ) + `agent_messages`(id, conversation_id UUID FK ON DELETE CASCADE, role TEXT, content TEXT, agent_name/model_name/model_id TEXT, created_at) + 2 索引。`agent_id/model_id` **故意用 TEXT 不加 FK**，删 Agent / 模型后历史仍可查。
  - `app/agent/models.py` 追加 `AgentConversation`/`AgentMessage` ORM（逐列对齐 DDL）。
  - `app/agent/conversations.py`：`HISTORY_LIMIT=20`；`create_conversation` / `append_message` / `history_for_llm`（最近 20 条倒序取再 reverse，仅 user/assistant）；`ConversationOut` 含 `message_count`、`ConversationDetailOut` 含 `messages`；路由 `/api/v1/agent/conversations` 的 GET "" / POST ""(201) / GET|PATCH|DELETE "/{conversation_id}"（404「会话不存在」、DELETE 204）。
  - `app/agent/definitions_router.py` 加 `SkillPatch{enabled}`、`globally_enabled_keys(db)->set[str]`、`PATCH /skills/{skill_key}`（未知 404「技能不存在」，静态路由排在 `/{agent_id}` 前）。**全局停用后对所有 Agent 都不注入该工具**。
  - `app/agent/chat_router.py` 重写：`ChatIn{question, agent_id, conversation_id, model_id}`；`_resolve_model(db, agent, override)` 优先级 = 对话框临时覆盖 > Agent 绑定 > 默认 > 最新；`_tool_schemas` 用 `globally_enabled_keys` 过滤；每轮 `messages = system + history_for_llm + 本次 user`，工具循环后 `append_message` 两条（user+assistant）并 `db.commit()`；新建会话 `title=首问[:60]`；`ChatOut` 加 `conversation_id/title`。无模型 400「尚未配置可用的模型（设置 → Agent 模型配置）」。
  - `app/main.py` 注册 `agent_conversations_router`。`backend/tests/test_agent_conversations.py` 6 用例：会话 CRUD/404、chat 落库两轮 + 续聊注入历史（message_count=4）、model_id 覆盖优先、技能停用后不注入工具再恢复、未知技能 404。
- **前端（4 文件重写 + 2 文件接线）**：
  - 新建 `api/conversations.ts`（`Conversation`/`ConversationDetail` + `conversationsApi(list/get/create/rename/remove)`）；改 `api/chat.ts`（`ChatRequest` 加 `conversation_id/model_id`、`ChatResponse` 加 `conversation_id/title`）；`api/agents.ts` 加 `agentsApi.toggleSkill`。
  - 重写 `pages/Agent.tsx`（~631 行）：紧凑 `agent-strip/agent-chip` 选择器（卡片不再是主视觉）+ **正经对话框** `.chat-workspace`（左 `.chat-sidebar` 历史会话列表：新建/点击 `openConversation` 拉详情映射消息/删除；右 `.chat-panel`：`.chat-panel__head` 显示 Agent 名 + 技能数 + **模型下拉 select**（`modelId` state，值 "" = 跟随助手/默认）、`.chat-panel__body` 消息气泡、`.chat__composer` 底部输入）；`ask()` 传 `{question, agent_id, conversation_id: activeConvId, model_id: modelId || null}`，成功后 `setActiveConvId` + `loadConversations`；typing / 分析依据 / 建议 chips 保留；Agent 编辑器 Dialog 保留。
  - 重写 `pages/Settings.tsx`：三块垂直 card 改 `SettingsTab = "models"|"tokens"|"mcp"` 水平 `.tabs`（Cpu/KeyRound/Plug 图标），每块用 `{tab === "..." && (...)}` 条件渲染，解决「token 内容多就拉很长」。
  - 新建 `pages/Skills.tsx`：`agentsApi.skills()` 拉 16 技能按 `CATEGORY_ORDER=["data","analysis","knowledge","action"]` 分组；`skills-summary` 计总/启用/停用；每组 `skill-card`（`.code-inline` key、描述、内置 tag、状态、停用/启用按钮）调 `agentsApi.toggleSkill` 局部更新 + toast；`skill-card--off` 虚线淡化；`alert--info` 说明「写入（受控）只生成待审批草稿绝不直接入账」。
  - `App.tsx` NAV 第二行插「技能」（Blocks 图标，助手仍置顶），Routes 加 `/skills`；`styles/global.css` 末尾追加 `.tabs/.tabs__tab`、`.agent-strip/.agent-chip`、`.chat-workspace`(grid 240px+1fr, min 480px)/`.chat-sidebar`/`.chat-session`/`.chat-panel`/`.btn--icon`、`.skills-summary/.skills-group/.skill-cards/.skill-card`（+ @media 900/768px 单列）。决策：复用既有 `.chat__*/.msg__*/.chips/.chip/.evidence/.typing` 全套不重写；Tabs 用独立类避免影响 Risk.tsx 的 `btn--ghost` 切页。
  - `AgentModelPatch` 强类型化后未用 → 删掉该 type import（TS6133 教训）。
- **验收**：`uv run pytest -q` **154 passed, 19 warnings**；`ruff check` / `ruff format --check` 85 files / `mypy app` Success 70 files；`npx tsc --noEmit` 0、`npx vite build` 0（2144 modules，`index-D-NO5b1S.js 438.51 kB` / gzip 124.40、`index-Be58xV5C.css 23.72 kB`）；`/tmp/m7_phaseC_e2e.py` 真实 HTTP **18 断言全绿**（会话 CRUD 8、技能管理 5、chat 安全路径 2、vite /agent /skills /settings 3）。完整 chat 落库由单测 mock llm 覆盖（E2E 不触发真实 LLM，避免 api.openai.com 无密钥）。

## 6.17 前端设计系统级精修（`redesign-existing-projects`，本次提交）

用户 m06213 反馈：「感觉前端设计缺少大厂那种设计感。没有用技能优化一下吗。」此前 §6.13 的 `impeccable` 只做了 bug 级修补（补 `.btn--ghost`、仪表盘真实数据、占位诚实化），并非系统性视觉重设计。本次加载 `redesign-existing-projects` 技能，按 **Scan → Diagnose → Fix** 与 Fix Priority（字体 → 配色 → 交互 → 布局 → 组件 → 状态 → 字阶）落地，**不重写组件、不换框架、不改动任何业务类名**。

**诊断出的六条根因**：
1. **字体根本没加载**：`tokens.css` 声明 `"IBM Plex Sans"`，但全仓库无 `@font-face` / Google Fonts link / `@fontsource` 依赖 → 实际一直 fallback 到 `system-ui`。`--font-mono` 被 global.css 引用却从未定义。这是最刺眼的模板指纹。
2. **纯平面无层次**：卡片一律 `#fff` + 1px 灰边框，阴影是中性黑 `rgba(15,23,42,.12)`，无环境光/材质/深度。
3. **总览页四张等分白卡**：旗舰页无主次（总资产与次要指标同权），典型「等分卡片」模板感。
4. **侧栏激活态整块饱和蓝**：大厂做法是低饱和 tint + 左侧细指示条。
5. **字阶扁平**：正文 14 / 标题 20 / 数值 20，只有 500/600 两档，无 display 级排版与负字距。
6. **交互缺物理反馈**：hover 只换色，无位移/按压；`scroll-behavior`、`prefers-reduced-motion`、favicon/meta 全缺。

**落地（7 文件）**：
- `frontend/package.json` + `package-lock.json`：`npm install @fontsource-variable/geist @fontsource-variable/geist-mono`（均 5.3.0）。**自托管而非 CDN**（离线可靠、无 FOUT、无外部请求）；`@fontsource-variable/geist/wght.css` 与 `geist-mono/wght.css` 在 `main.tsx` 导入，Vite 把 11 个 woff2 子集打进 `dist/assets`。字族 = `"Geist Variable"` 负责西文/数字，中文回退 PingFang SC / Noto Sans SC；`"Geist Mono Variable"` 补齐 `--font-mono`。
- `frontend/src/styles/tokens.css`（重写，**保留全部旧变量名**以兼容既有类名）：单一强调色 `--color-primary: #2748c8` + hover/soft/softer/ring 四级派生；暖中性表面层级（background `#faf9f7` / surface `#f3f2ef` / card `#fff` / sunken）；**带品牌色相的着色阴影** `--shadow-card/-hover/-pop/-hero`（弃用纯黑）；圆角分级（card 14 / lg 18 / control 9 / pill）；新增 `--space-7/8`、`--ease-out/--ease-spring`、`--dur-fast/--dur/--dur-slow`；深色模式全量对应覆盖（含 `color-scheme`）。
- `frontend/src/styles/global.css`（末尾追加「精修层」，靠层叠覆盖基础规则）：`html{scroll-behavior:smooth}`；标题 650 字重 + `-0.02em` 负字距；`.page__title` 28px/700、`OVERVIEW` eyebrow；侧栏 `background: var(--color-surface)` + 激活态 `primary-soft` tint + `::before` 3px 指示条 + svg 加粗；顶栏半透明 + `backdrop-filter: blur(14px) saturate(1.4)`；卡片 `var(--shadow-card)` + hover 上浮阴影；按钮 hover `translateY(-1px)` + `:active scale(0.97)`；输入 focus 3px `primary-ring` 环；`.tag/.badge` 边框改 `currentColor 22%`（避免灰框破坏状态色）；`@media (prefers-reduced-motion: reduce)` 统一压平动效。
- `frontend/src/pages/Dashboard.tsx`（重写视觉结构）：四等分 `.stat-grid` → `.overview` 非对称栅格（`1.55fr : 1fr`）。左侧 **hero 主卡**（深墨 `#141826` 底 + 单点品牌径向光晕 + 顶部 1px 高光，**刻意不用紫蓝 AI 渐变**）：eyebrow「净资产 · NET ASSET VALUE」、`clamp(34px,4vw,48px)` 大数值、现金/持仓占比条与图例、账本口径脚注；右侧 3 张 `.metric-card` 纵向堆叠（现金合计 / 持仓市值 / 累计盈亏），hover 上浮。`page__head` 补「总览」display 标题。业务数据获取与 `noAccounts` 空态完全不变。
- `frontend/index.html`：补 `description`、`color-scheme`、双 `theme-color`（亮 `#2748c8` / 暗 `#0e1014`）、内联 SVG favicon（品牌蓝方块 + 「投」字笔画）、title 改「投谱 Toupu · 投资账本」。
- **决策**：`.page__title` 用 `<h2>`（Dashboard 原 `<h1>` 会造成页内多 h1）；`--color-primary` 从 `#1e40af` 调为 `#2748c8`（更饱和、在 tint 上更清晰）；hero 从初版「蓝色渐变」改为「深墨底 + 光晕」，因为技能明确禁紫蓝 AI 渐变，深墨更符合 Linear/Vercel 系 fintech 质感。

**验收**：`npx tsc --noEmit` 0；`npx vite build` 0（**2146 modules**，11 个 woff2 字体子集打包，`index-*.css 35.03 kB` / gzip 6.73、`index-*.js 440.17 kB` / gzip 124.85）；14 条前端路由全部 200；headless Chrome `--dump-dom` 实测 React 真实挂载 hero（渲染出真实净资产 `58,325,421.670058`、`NET ASSET VALUE`、`OVERVIEW`、全部 `hero-card__*` 节点、26 个侧栏链接），字体 woff2 经 vite 返回 `200 font/woff2`，构建 CSS 含 `Geist Variable`/`Geist Mono Variable`。注：本模型不支持读图，故改用 DOM 断言而非截图判读（截图 `/tmp/toupu-dashboard.png` 已生成可供人工查看）。后端未改动。

## 7. 还没做

| 事项 | 说明 |
|---|---|
| ~~持仓页前端~~ | 已完成（b6cccd2） |
| ~~交易页支持证券录入~~ | 已完成（b6cccd2）：证券买卖 + 成交明细 + 品种选择 |
| ~~M3 场外基金（后端）~~ | 已完成（b4ebed5）：两段式申购/赎回 + 确认守恒 + 现金分红 + 红利再投资 + 17 测试 |
| ~~M3 场外基金（前端）~~ | 已完成（77db678）：`/funds` 申请/确认页 + 守恒校验 + 分录详情 |
| ~~M4 导入（后端）~~ | 已完成（5b80ace）：CSV/Excel、字段映射、去重、预览确认、期初资产 + 19 测试 |
| ~~M4 导入（前端）~~ | 已完成（0fa2a63）：上传/预览/错误定位/确认/取消页面与 `/imports` 路由 |
| ~~M5 行情与收益（后端）~~ | 已完成（d93ce0c）：MANUAL 行情/净值、双口径派生、XIRR/TWR/MDD、快照幂等重建 + 27 测试 |
| ~~M5 行情与收益（前端）~~ | 已完成（95d2984）：`/market` 估值明细/行情净值录入/快照重建/收益指标卡 |
| ~~M6 风险与 Agent（后端）~~ | 已完成（21efd98）：风险规则/扫描/事件、Agent Token/只读网关、提案审批只生成 DRAFT、轻量计划 + 32 测试 |
| ~~M6 前端~~ | 已完成（4e8b431）：`/risk` 事件与规则管理、`/plans` 提案审批与投资计划 |
| ~~界面审查~~ | 已完成（029a58a）：impeccable Operate 审查 + P0/P1/P3 修复 + tsc/build 通过 |
| ~~M7 账本页/设置页脚手架~~ | 已完成（3f8241e/6df6382）：账本只读接口 + 前端账本页/设置页 + 端口改 5180 |
| ~~M7 Phase 1-2（skill + 对外 MCP）~~ | 已完成（c21980e）：系统 skill 文档 + 对外 MCP 服务 + 00010 迁移 + resources 重构 |
| ~~M7 Phase 3（模型配置 + 分析会话 + 前端 Agent 页）~~ | 已完成（a75c89a）：模型 CRUD + OpenAI 兼容客户端 + `/agent/chat` + 前端 `/agent` 页 + display_name 别名 |
| ~~M7 Phase 4（挂载外部 MCP）~~ | 已完成（eec8a5c）：`agent_mcp_servers` 前端 CRUD + 通用 MCP 客户端（stdio/http），chat 快照注入外部知识 + `/{id}/test` |
| ~~WeKnora 对齐 Phase A（后端）~~ | 已完成（5304768）：16 技能运行时 + 工具循环 + Agent 一等实体 CRUD + 内置投谱助手 + 0012 迁移 + 148 测试 |
| ~~WeKnora 对齐 Phase B（前端）~~ | 已完成（7cb3ed3）：Agent 卡片列表/编辑器 + 设置重组 + 助手置顶 + 去 as_of + 凭证改名 + tsc/build/E2E 全绿 |
| ~~用户二次反馈 Phase C~~ | 已完成（5291491）：0013 会话持久化 + 正经对话框（左历史/右对话/顶部换模型）+ 设置水平 Tabs + `/skills` 技能管理页 + 全局技能总开关；154 passed / tsc/build / 18 断言 E2E 全绿 |
| ~~前端设计感重设计~~ | 已完成（本次提交）：Geist 字体/令牌/精修层/hero 主卡/meta 全落地，tsc/build 0 + DOM 实测。详见 §6.17 |
| M7 收尾 | 已完成：全量 E2E（23 + 18 断言）与提交；当前 `git status` 干净 |

## 8. 环境与工具坑（踩过的）

- **shell 管道吞退出码**：`npm run build | tail` 失败也会"成功"，用 `${pipestatus[1]}` 判断。
- Playwright 工具只能在 `execute` 内用 `tools.playwright.*` 调用；`browser_take_screenshot` 必须传 `scale`。
- 截图/快照落在仓库 `.playwright-mcp/` 与根目录 `accounts.png`（已提交，无害）。
- 测试与 dev 共用同一个库（`toupu`），测试会留下数据（账户名带随机后缀区分）。
- **断言不要依赖全表窗口**（如「最近 100 条交易」）：数据会持续累积导致偶发失败，按 `account_id`/`rule_id` 等过滤；`test_reverse_flow` 已因此修过一次。
- ruff 配置忽略 `B008`（FastAPI `Depends` 模式）。
- 金额序列化走 `Decimal` → JSON 字符串，测试断言要按 `"2205.000000"` 六位小数写。
- **impeccable 二进制首次运行会后台下载**：`impeccable context` 在本机会挂起（下载未完成），按技能回退条款直接读项目上下文即可，无需阻塞。
- **本模型不支持读图**：`read_image` 会报 `model "hy4free" does not declare image input`。需要验证前端视觉时，用本机 Chrome 无头模式替代：`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu --no-sandbox --virtual-time-budget=6000 --dump-dom URL`，再对 DOM 做文本断言（本次据此确认 hero 真实挂载）；`--screenshot=xxx.png` 可落图供人工查看。
- **前端视觉验证顺序**：`npx tsc --noEmit` → `npx vite build` → vite dev 逐路由 200 → headless DOM 断言 → 构建产物 grep 确认字体/类名。注意 vite `/src/*.tsx` 返回的是转译后的 JS 模块，grep 类名要按字符串匹配。

## 9. 建议的接手顺序

1. ~~M2 前端闭环~~（b6cccd2）、~~M3 场外基金后端~~（b4ebed5）、~~M3 前端闭环~~（77db678）、~~M4 导入后端~~（5b80ace）、~~M4 导入前端~~（0fa2a63）、~~M5 行情与收益后端~~（d93ce0c）、~~M5 前端闭环~~（95d2984）、~~M6 风险/Agent 后端~~（21efd98）、~~M6 前端~~（4e8b431）、~~界面审查~~（029a58a）、~~M7 Phase 1-4（skill + 对外 MCP + 模型配置 + 分析会话 + 前端 Agent 页 + 挂载外部 MCP）~~（c21980e/a75c89a/eec8a5c）、~~WeKnora 对齐 Phase A 后端~~（5304768）、~~WeKnora 对齐 Phase B 前端~~（7cb3ed3）、~~用户二次反馈 Phase C（会话/对话框/Tabs/技能页）~~（5291491）、~~前端设计系统级精修~~（本次提交，§6.17）。
2. 当前状态：M0~M7 整段完成、按 WeKnora 对齐的 Agent 架构重做（后端 + 前端）+ 用户二次反馈 Phase C + 前端设计系统级精修均已验收并提交，`git status` 干净。无待办里程碑；后续可选方向（非承诺）：真实 LLM 模型联调、MCP 凭证按工具粒度授权、外部知识库深度检索（weknora 挂载）、会话跨设备同步/分享。
3. 每次改动后保持：`pytest` 全绿 → `ruff`/`mypy` 干净 → 实测 → 提交。
