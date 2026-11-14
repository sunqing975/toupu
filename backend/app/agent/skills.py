# 技能运行时（M7 对齐 WeKnora 的 Skill 目录）：每个技能是可被模型在对话循环里
# 调用的可执行工具（对齐用户选择「完整技能运行时」而非仅提示词注入）。
# - 数据技能：委托 resources.py 只读拉取，金额一律字符串。
# - 分析技能：基于只读数据做真实聚合（集中度/归因/风险扫描/调仓草案骨架），由模型负责叙述。
# - 提案技能：只能建 PENDING 提案，绝不入账（与现有 Agent 提案口径一致）。
# - 外部知识技能：只读拉取已挂载的外部 MCP 资源。
# 每个技能暴露 OpenAI function-calling schema，交由 llm.chat_with_tools 的工具循环调度。
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.agent import resources
from app.agent.mcp_client import fetch_external_knowledge


def _fmt(obj: Any) -> str:
    """工具结果一律序列化为 JSON 字符串，保证模型可读、可解析。"""
    return json.dumps(obj, ensure_ascii=False, default=str)


# ---- 各技能执行器（db + 已解析的参数 -> 字符串结果） ----


def _read_accounts(db: Session, args: dict) -> str:
    data, meta = resources.accounts(db)
    return _fmt({"meta": _meta_out(meta), "accounts": data})


def _read_positions(db: Session, args: dict) -> str:
    data, meta = resources.positions(db)
    return _fmt({"meta": _meta_out(meta), "positions": data})


def _read_transactions(db: Session, args: dict) -> str:
    data, meta = resources.transactions(db)
    return _fmt({"meta": _meta_out(meta), "transactions": data})


def _read_quotes(db: Session, args: dict) -> str:
    data, meta = resources.quotes(db)
    return _fmt({"meta": _meta_out(meta), "quotes": data})


def _read_valuation(db: Session, args: dict) -> str:
    as_of = _parse_date(args.get("as_of"))
    data, meta = resources.valuation(db, as_of)
    return _fmt({"meta": _meta_out(meta), "valuation": data})


def _read_summary(db: Session, args: dict) -> str:
    as_of = _parse_date(args.get("as_of"))
    data, meta = resources.summary(db, as_of)
    return _fmt({"meta": _meta_out(meta), "summary": data})


def _read_returns(db: Session, args: dict) -> str:
    as_of = _parse_date(args.get("as_of"))
    data, meta = resources.returns(db, as_of)
    return _fmt({"meta": _meta_out(meta), "returns": data})


def _read_risk_events(db: Session, args: dict) -> str:
    data, meta = resources.risk_events(db)
    return _fmt({"meta": _meta_out(meta), "risk_events": data})


def _read_plans(db: Session, args: dict) -> str:
    data, meta = resources.plans(db)
    return _fmt({"meta": _meta_out(meta), "plans": data})


def _read_proposals(db: Session, args: dict) -> str:
    data, meta = resources.proposals(db)
    return _fmt({"meta": _meta_out(meta), "proposals": data})


def _read_external_knowledge(db: Session, args: dict) -> str:
    question = args.get("question")
    text = fetch_external_knowledge(db, question=question)
    if not text:
        return _fmt({"external_knowledge": None, "note": "未挂载任何外部知识库，或本次连接失败。"})
    return _fmt({"external_knowledge": text})


def _analyze_concentration(db: Session, args: dict) -> str:
    """持仓诊断：基于估值明细计算各持仓占比、Top 集中度（HHI）。"""
    as_of = _parse_date(args.get("as_of"))
    val, _ = resources.valuation(db, as_of)
    summ, _ = resources.summary(db, as_of)
    total = 0.0
    try:
        total = float(summ[0]["total_assets"])
    except (IndexError, KeyError, TypeError, ValueError):
        total = 0.0
    rows = []
    hhi = 0.0
    for p in val:
        mv = _to_float(p.get("market_value"))
        if total and mv is not None:
            w = mv / total
            hhi += w * w
            rows.append(
                {
                    "instrument_code": p.get("instrument_code"),
                    "instrument_name": p.get("instrument_name"),
                    "market_value": p.get("market_value"),
                    "weight": round(w, 6),
                }
            )
    rows.sort(key=lambda r: float(r["weight"] or 0.0), reverse=True)
    return _fmt(
        {
            "total_assets": summ[0]["total_assets"] if summ else None,
            "position_count": len(rows),
            "top_positions": rows[:10],
            "hhi_concentration": round(hhi, 6),
            "note": "HHI 越接近 1 越集中；>0.25 视为偏高集中。",
        }
    )


def _analyze_returns_attribution(db: Session, args: dict) -> str:
    """收益归因：列出收益指标 + 各持仓账面成本/未实现盈亏，供模型归因。"""
    as_of = _parse_date(args.get("as_of"))
    val, _ = resources.valuation(db, as_of)
    ret, _ = resources.returns(db, as_of)
    rows = [
        {
            "instrument_code": p.get("instrument_code"),
            "instrument_name": p.get("instrument_name"),
            "book_cost": p.get("book_cost"),
            "market_value": p.get("market_value"),
            "unrealized": p.get("unrealized"),
        }
        for p in val
    ]
    rows.sort(key=lambda r: float(_to_float(r.get("unrealized")) or 0.0), reverse=True)
    return _fmt({"returns": ret, "unrealized_by_position": rows})


def _scan_risk(db: Session, args: dict) -> str:
    """风险扫描：列出未处理风险事件，供模型评估。"""
    data, meta = resources.risk_events(db)
    open_events = [e for e in data if e.get("status") == "OPEN"]
    return _fmt(
        {
            "meta": _meta_out(meta),
            "open_risk_events": open_events,
            "open_count": len(open_events),
        }
    )


def _draft_rebalance_plan(db: Session, args: dict) -> str:
    """调仓建议草案：仅返回结构化骨架（不写账本、不建提案），由模型填充理由。"""
    target = args.get("objective") or "优化风险收益"
    return _fmt(
        {
            "draft_plan_skeleton": {
                "objective": target,
                "steps": [
                    "基于持仓诊断(analyze_portfolio_concentration)识别偏高集中度",
                    "基于收益归因(analyze_returns_attribution)定位拖累/贡献项",
                    "结合风险扫描(scan_risk_events)给出减仓/加仓方向",
                    "如涉及实际交易，使用 create_draft_proposal 生成待审批草稿",
                ],
            },
            "note": "此技能只产出计划框架，不执行任何改动账本的操作。",
        }
    )


def _create_draft_proposal(db: Session, args: dict) -> str:
    """创建待审批现金交易提案（只建 PENDING，绝不入账；审批在网页端人工确认）。"""

    from app.plans.proposal_service import validate_payload
    from app.risk.models import OperationProposal

    payload = args.get("payload") or {}
    try:
        validated = validate_payload(db, payload)
    except Exception as exc:  # noqa: BLE001 — 校验失败要明确回传给模型
        return _fmt({"ok": False, "error": f"提案数据校验失败：{exc}"})
    proposal = OperationProposal(
        proposal_type="DRAFT_CASH_TRANSACTION",
        status="PENDING",
        created_by="agent:skill",
        payload=payload,
        impact_preview=validated["impact"],
        validation_snapshot=validated["snapshot"],
        expires_at=UTC_and_hours(args.get("expires_hours", 48)),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return _fmt(
        {
            "ok": True,
            "proposal_id": str(proposal.id),
            "status": proposal.status,
            "impact": validated["impact"],
            "note": "已生成待审批草稿，需用户在网页端审批后才会建账本草稿。",
        }
    )


# ---- 工具 schema 注册表 ----


class _Skill:
    def __init__(
        self,
        key: str,
        name: str,
        description: str,
        category: str,
        params: dict,
        executor: Callable[[Session, dict], str],
    ) -> None:
        self.key = key
        self.name = name
        self.description = description
        self.category = category
        self.params = params
        self.executor = executor

    def tool_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.key,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.params,
                    "required": [k for k, v in self.params.items() if v.get("required")],
                },
            },
        }


_DATE_PARAM = {
    "as_of": {
        "type": "string",
        "description": "数据截止日期 YYYY-MM-DD；留空表示今天。",
        "required": False,
    }
}

SKILLS: dict[str, _Skill] = {
    # —— 数据技能（只读）——
    "read_accounts": _Skill(
        "read_accounts", "查询账户", "读取全部投资账户列表。", "data", {}, _read_accounts
    ),
    "read_positions": _Skill(
        "read_positions",
        "查询持仓",
        "读取当前全部持仓（账户×品种聚合）。",
        "data",
        {},
        _read_positions,
    ),
    "read_transactions": _Skill(
        "read_transactions", "查询交易", "读取最近交易流水。", "data", {}, _read_transactions
    ),
    "read_quotes": _Skill(
        "read_quotes", "查询行情", "读取行情与基金净值（含报价状态）。", "data", {}, _read_quotes
    ),
    "read_valuation": _Skill(
        "read_valuation",
        "查询估值明细",
        "读取各持仓估值明细（数量/成本/市值/未实现）。",
        "data",
        dict(_DATE_PARAM),
        _read_valuation,
    ),
    "read_summary": _Skill(
        "read_summary",
        "查询组合概览",
        "读取组合概览（现金/市值/总资产/收益）。",
        "data",
        dict(_DATE_PARAM),
        _read_summary,
    ),
    "read_returns": _Skill(
        "read_returns",
        "查询收益指标",
        "读取收益指标（XIRR/TWR/最大回撤）。",
        "data",
        dict(_DATE_PARAM),
        _read_returns,
    ),
    "read_risk_events": _Skill(
        "read_risk_events", "查询风险事件", "读取风险事件列表。", "data", {}, _read_risk_events
    ),
    "read_plans": _Skill(
        "read_plans", "查询投资计划", "读取投资计划与行动项。", "data", {}, _read_plans
    ),
    "read_proposals": _Skill(
        "read_proposals", "查询待审批提案", "读取待审批/历史提案。", "data", {}, _read_proposals
    ),
    # —— 投资分析技能（真实聚合）——
    "analyze_portfolio_concentration": _Skill(
        "analyze_portfolio_concentration",
        "持仓诊断",
        "计算各持仓占比、Top 集中度（HHI）。",
        "analysis",
        dict(_DATE_PARAM),
        _analyze_concentration,
    ),
    "analyze_returns_attribution": _Skill(
        "analyze_returns_attribution",
        "收益归因",
        "按持仓列账面成本/市值/未实现盈亏，供归因。",
        "analysis",
        dict(_DATE_PARAM),
        _analyze_returns_attribution,
    ),
    "scan_risk_events": _Skill(
        "scan_risk_events", "风险扫描", "列出未处理风险事件。", "analysis", {}, _scan_risk
    ),
    "draft_rebalance_plan": _Skill(
        "draft_rebalance_plan",
        "调仓建议草案",
        "仅返回调仓计划框架（不写账本、不建提案）。",
        "analysis",
        {"objective": {"type": "string", "description": "调仓目标", "required": False}},
        _draft_rebalance_plan,
    ),
    # —— 外部知识 + 提案 ——
    "read_external_knowledge": _Skill(
        "read_external_knowledge",
        "查询外部知识库",
        "只读拉取已挂载的外部 MCP 知识（如 weknora）。",
        "knowledge",
        {"question": {"type": "string", "description": "检索问题", "required": False}},
        _read_external_knowledge,
    ),
    "create_draft_proposal": _Skill(
        "create_draft_proposal",
        "创建待审批提案",
        "生成现金交易待审批草稿（PENDING，不入账）。",
        "action",
        {
            "payload": {
                "type": "object",
                "description": (
                    "交易载荷：transaction_type(DEPOSIT/WITHDRAW/ACCOUNT_TRANSFER), "
                    "account_id, counter_account_id?, amount(string), business_date"
                ),
                "required": True,
            },
            "expires_hours": {
                "type": "integer",
                "description": "过期小时数（默认48）",
                "required": False,
            },
        },
        _create_draft_proposal,
    ),
}


def get_skill(key: str) -> _Skill | None:
    return SKILLS.get(key)


def execute_skill(db: Session, key: str, arguments: str | dict) -> str:
    skill = SKILLS.get(key)
    if skill is None:
        return _fmt({"ok": False, "error": f"未知技能：{key}"})
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
    except json.JSONDecodeError:
        args = {}
    try:
        return skill.executor(db, args)
    except Exception as exc:  # noqa: BLE001
        return _fmt({"ok": False, "error": f"技能执行失败：{exc}"})


# ---- 内部工具 ----


def _meta_out(meta) -> dict:
    return {
        "as_of": meta.as_of,
        "source": meta.source,
        "is_estimate": meta.is_estimate,
        "is_delayed": meta.is_delayed,
        "missing": meta.missing,
        "queried_at": meta.queried_at,
    }


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def UTC_and_hours(hours: int):
    from datetime import timedelta

    return datetime_now_utc() + timedelta(hours=max(1, min(720, int(hours))))


def datetime_now_utc():
    from datetime import UTC, datetime

    return datetime.now(UTC)
