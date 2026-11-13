# 确定性风险引擎（M6）：纯函数，无 DB / HTTP / 随机 / LLM，now 可注入便于测试。
# 口径来自 docs/risk-agent-rules.md §4：同一输入必得同一输出；缺失不伪装；六位量化。
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.performance.formulas import Valuation, max_drawdown

Q6 = Decimal("0.000001")

# scope × rule_type 合法组合（服务端强校验，docs/risk-agent-rules.md §3）
VALID_COMBINATIONS = {
    ("INSTRUMENT", "POSITION_WEIGHT"),
    ("ACCOUNT", "ACCOUNT_WEIGHT"),
    ("PORTFOLIO", "PORTFOLIO_DRAWDOWN"),
    ("PORTFOLIO", "QUOTE_COVERAGE"),
}


@dataclass(frozen=True)
class RuleSpec:
    id: uuid.UUID
    scope: str
    rule_type: str
    threshold: Decimal
    severity: str
    cooldown_minutes: int
    name: str


@dataclass(frozen=True)
class PositionData:
    account_id: str
    account_name: str
    instrument_id: str
    instrument_name: str
    valued: bool
    market_value: Decimal | None


@dataclass(frozen=True)
class DerivedData:
    total_assets: Decimal
    coverage: Decimal
    total_positions: int
    positions: list[PositionData]


@dataclass(frozen=True)
class EventSpec:
    rule_id: uuid.UUID
    as_of: date
    scope: str
    subject: str
    rule_type: str
    severity: str
    trigger_value: Decimal
    threshold: Decimal
    message: str
    dedup_key: str


@dataclass(frozen=True)
class SkipSpec:
    rule_id: uuid.UUID
    rule_type: str
    subject: str
    reason: str


@dataclass(frozen=True)
class ScanResult:
    created: list[EventSpec] = field(default_factory=list)
    skipped: list[SkipSpec] = field(default_factory=list)
    evaluated_rules: int = 0


def dedup_key_for(rule_id: uuid.UUID, subject: str, as_of: date) -> str:
    return f"{rule_id}|{subject}|{as_of.isoformat()}"


def evaluate(
    rules: list[RuleSpec],
    derived: DerivedData,
    points: list[Valuation],
    as_of: date,
    now: datetime,
    existing_dedup_keys: set[str],
    last_event_times: dict[tuple[uuid.UUID, str], datetime],
) -> ScanResult:
    """确定性扫描：返回待创建事件与跳过原因，不写任何表。"""
    result = ScanResult()

    def maybe_create(rule: RuleSpec, subject: str, trigger_value: Decimal, message: str) -> None:
        dedup_key = dedup_key_for(rule.id, subject, as_of)
        if dedup_key in existing_dedup_keys:
            result.skipped.append(SkipSpec(rule.id, rule.rule_type, subject, "同日已存在相同事件"))
            return
        last = last_event_times.get((rule.id, subject))
        within_cooldown = (
            last is not None
            and rule.cooldown_minutes > 0
            and now - last < timedelta(minutes=rule.cooldown_minutes)
        )
        if within_cooldown:
            result.skipped.append(SkipSpec(rule.id, rule.rule_type, subject, "冷却时间内"))
            return
        result.created.append(
            EventSpec(
                rule_id=rule.id,
                as_of=as_of,
                scope=rule.scope,
                subject=subject,
                rule_type=rule.rule_type,
                severity=rule.severity,
                trigger_value=trigger_value.quantize(Q6),
                threshold=rule.threshold,
                message=message,
                dedup_key=dedup_key,
            )
        )

    for rule in rules:
        if (rule.scope, rule.rule_type) not in VALID_COMBINATIONS:
            result.skipped.append(SkipSpec(rule.id, rule.rule_type, "-", "规则范围与类型不匹配"))
            continue

        if rule.rule_type in ("POSITION_WEIGHT", "ACCOUNT_WEIGHT"):
            if derived.total_assets <= 0:
                result.skipped.append(
                    SkipSpec(rule.id, rule.rule_type, "-", "总资产非正，权重无意义")
                )
                continue
            aggregated: dict[str, Decimal] = {}
            labels: dict[str, str] = {}
            for position in derived.positions:
                if rule.rule_type == "POSITION_WEIGHT":
                    subject = position.instrument_id
                    label = position.instrument_name
                else:
                    subject = position.account_id
                    label = position.account_name
                if not position.valued or position.market_value is None:
                    result.skipped.append(SkipSpec(rule.id, rule.rule_type, subject, "无有效报价"))
                    continue
                aggregated[subject] = aggregated.get(subject, Decimal(0)) + (position.market_value)
                labels[subject] = label
            for subject in sorted(aggregated):
                weight = (aggregated[subject] / derived.total_assets).quantize(Q6)
                if weight > rule.threshold:
                    kind = "单品种" if rule.rule_type == "POSITION_WEIGHT" else "单账户"
                    message = (
                        f"{kind}集中度超限：{labels[subject]} 权重 {weight} "
                        f"超过阈值 {rule.threshold}"
                    )
                    maybe_create(rule, subject, weight, message)

        elif rule.rule_type == "PORTFOLIO_DRAWDOWN":
            mdd = max_drawdown(points)
            if mdd.status != "OK" or mdd.value is None:
                result.skipped.append(
                    SkipSpec(
                        rule.id,
                        rule.rule_type,
                        "PORTFOLIO",
                        "组合快照不足，无法计算回撤",
                    )
                )
                continue
            if mdd.value < -rule.threshold:
                message = f"组合回撤超限：最大回撤 {mdd.value} 低于 -{rule.threshold}"
                maybe_create(rule, "PORTFOLIO", mdd.value, message)

        elif rule.rule_type == "QUOTE_COVERAGE":
            if derived.total_positions == 0:
                result.skipped.append(
                    SkipSpec(rule.id, rule.rule_type, "PORTFOLIO", "无持仓，跳过覆盖率检查")
                )
                continue
            coverage = derived.coverage.quantize(Q6)
            if coverage < rule.threshold:
                message = f"行情覆盖率不足：{coverage} 低于阈值 {rule.threshold}"
                maybe_create(rule, "PORTFOLIO", coverage, message)

    return ScanResult(
        created=result.created,
        skipped=result.skipped,
        evaluated_rules=len(rules),
    )
