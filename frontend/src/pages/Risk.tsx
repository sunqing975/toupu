import { useEffect, useState } from "react"
import { AlertTriangle, Play, Plus, SlidersHorizontal } from "lucide-react"
import {
  EVENT_STATUS_LABELS,
  RULE_TYPE_LABELS,
  SCOPE_LABELS,
  SCOPE_RULE_TYPES,
  SEVERITY_LABELS,
  riskApi,
  type RiskEvent,
  type RiskRule,
  type ScanResult,
} from "../api/risk"
import { EmptyState } from "../components/EmptyState"
import { Dialog } from "../components/Dialog"
import { Skeleton } from "../components/Skeleton"
import { StatusBadge } from "../components/StatusBadge"
import { useToast } from "../components/Toast"

const today = () => new Date().toISOString().slice(0, 10)

const pct = (v: string | null) => (v === null ? "—" : `${(Number(v) * 100).toFixed(2)}%`)

type RuleForm = {
  scope: string
  rule_type: string
  threshold_percent: string
  severity: string
  cooldown_minutes: string
  memo: string
}

const EMPTY_RULE: RuleForm = {
  scope: "INSTRUMENT",
  rule_type: "POSITION_WEIGHT",
  threshold_percent: "20",
  severity: "WARNING",
  cooldown_minutes: "1440",
  memo: "",
}

export function Risk() {
  const toast = useToast()
  const [tab, setTab] = useState<"events" | "rules">("events")
  const [events, setEvents] = useState<RiskEvent[] | null>(null)
  const [rules, setRules] = useState<RiskRule[] | null>(null)
  const [statusFilter, setStatusFilter] = useState("")
  const [severityFilter, setSeverityFilter] = useState("")
  const [scanDate, setScanDate] = useState(today())
  const [scanning, setScanning] = useState(false)
  const [scanResult, setScanResult] = useState<ScanResult | null>(null)
  const [resolving, setResolving] = useState<{ event: RiskEvent; action: "acknowledge" | "ignore" } | null>(null)
  const [note, setNote] = useState("")
  const [ruleDialog, setRuleDialog] = useState<{ mode: "create" } | { mode: "edit"; rule: RiskRule } | null>(null)
  const [ruleForm, setRuleForm] = useState<RuleForm>(EMPTY_RULE)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadEvents = () => {
    setEvents(null)
    riskApi
      .events({ status: statusFilter || undefined, severity: severityFilter || undefined })
      .then(setEvents)
      .catch((e: unknown) => {
        setEvents([])
        setError(String((e as Error).message))
      })
  }

  const loadRules = () => {
    setRules(null)
    riskApi
      .rules()
      .then(setRules)
      .catch((e: unknown) => {
        setRules([])
        setError(String((e as Error).message))
      })
  }

  useEffect(() => {
    loadEvents()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, severityFilter])

  useEffect(() => {
    loadRules()
  }, [])

  const scan = async () => {
    setScanning(true)
    try {
      const res = await riskApi.scan(scanDate)
      setScanResult(res)
      toast(
        "success",
        res.created.length > 0
          ? `扫描完成：新增 ${res.created.length} 条事件，跳过 ${res.skipped.length} 项`
          : `扫描完成：未触发新事件（跳过 ${res.skipped.length} 项）`,
      )
      loadEvents()
    } catch (e) {
      toast("error", (e as Error).message)
    } finally {
      setScanning(false)
    }
  }

  const resolve = async () => {
    if (!resolving) return
    setBusy(true)
    try {
      await riskApi[resolving.action](resolving.event.id, note || null)
      toast("success", resolving.action === "acknowledge" ? "事件已确认" : "事件已忽略")
      setResolving(null)
      setNote("")
      loadEvents()
    } catch (e) {
      toast("error", (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const openCreateRule = () => {
    setRuleForm(EMPTY_RULE)
    setRuleDialog({ mode: "create" })
  }

  const openEditRule = (rule: RiskRule) => {
    setRuleForm({
      scope: rule.scope,
      rule_type: rule.rule_type,
      threshold_percent: String(Number(rule.threshold) * 100),
      severity: rule.severity,
      cooldown_minutes: String(rule.cooldown_minutes),
      memo: rule.memo ?? "",
    })
    setRuleDialog({ mode: "edit", rule })
  }

  const saveRule = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!ruleDialog) return
    setBusy(true)
    const body: Record<string, unknown> = {
      threshold: (Number(ruleForm.threshold_percent) / 100).toFixed(6),
      severity: ruleForm.severity,
      cooldown_minutes: Number(ruleForm.cooldown_minutes),
      memo: ruleForm.memo || null,
    }
    try {
      if (ruleDialog.mode === "create") {
        await riskApi.createRule({
          ...body,
          scope: ruleForm.scope,
          rule_type: ruleForm.rule_type,
          enabled: true,
        })
        toast("success", "风险规则已创建")
      } else {
        await riskApi.updateRule(ruleDialog.rule.id, body)
        toast("success", "风险规则已更新")
      }
      setRuleDialog(null)
      loadRules()
    } catch (err) {
      toast("error", (err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const toggleRule = async (rule: RiskRule) => {
    try {
      await riskApi.updateRule(rule.id, { enabled: !rule.enabled })
      loadRules()
    } catch (e) {
      toast("error", (e as Error).message)
    }
  }

  const ruleTypes = SCOPE_RULE_TYPES[ruleForm.scope] ?? []

  return (
    <div className="page">
      <div className="page__head">
        <p className="page__sub">
          风险由确定性规则计算，不依赖模型推断；未估值持仓会跳过并给出原因，不按 0 计
        </p>
        <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
          <input
            className="input num"
            type="date"
            aria-label="扫描日期"
            value={scanDate}
            onChange={(e) => setScanDate(e.target.value)}
          />
          <button className="btn btn--primary" disabled={scanning} onClick={scan}>
            <Play size={16} aria-hidden /> {scanning ? "扫描中…" : "立即扫描"}
          </button>
        </div>
      </div>

      {error && <div className="banner banner--error">{error}</div>}

      {scanResult && (
        <div className="card" style={{ padding: "var(--space-3)" }}>
          <div className="card__title" style={{ marginBottom: "var(--space-2)" }}>
            上次扫描（{scanResult.as_of}，评估 {scanResult.evaluated_rules} 条规则）
          </div>
          {scanResult.created.length === 0 ? (
            <p style={{ color: "var(--color-muted-foreground)" }}>未触发新事件。</p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {scanResult.created.map((ev) => (
                <li key={ev.id}>{ev.message}</li>
              ))}
            </ul>
          )}
          {scanResult.skipped.length > 0 && (
            <details style={{ marginTop: "var(--space-2)" }}>
              <summary style={{ cursor: "pointer", color: "var(--color-muted-foreground)" }}>
                跳过 {scanResult.skipped.length} 项（缺失数据不伪装）
              </summary>
              <ul style={{ margin: "var(--space-2) 0 0", paddingLeft: 18, color: "var(--color-muted-foreground)" }}>
                {scanResult.skipped.map((s, i) => (
                  <li key={`${s.rule_id}-${s.subject}-${i}`}>
                    {RULE_TYPE_LABELS[s.rule_type] ?? s.rule_type} · {s.subject}：{s.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      <div style={{ display: "flex", gap: "var(--space-2)", borderBottom: "1px solid var(--color-border)", marginBottom: "var(--space-4)" }}>
        <button className={`btn ${tab === "events" ? "btn--primary" : "btn--ghost"}`} onClick={() => setTab("events")}>
          <AlertTriangle size={14} aria-hidden /> 风险事件
        </button>
        <button className={`btn ${tab === "rules" ? "btn--primary" : "btn--ghost"}`} onClick={() => setTab("rules")}>
          <SlidersHorizontal size={14} aria-hidden /> 规则管理
        </button>
      </div>

      {tab === "events" && (
        <div className="card table-scroll">
          <div style={{ display: "flex", gap: "var(--space-2)", padding: "var(--space-2) var(--space-3)", borderBottom: "1px solid var(--color-border)" }}>
            <select className="select" aria-label="按状态筛选" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">全部状态</option>
              {Object.entries(EVENT_STATUS_LABELS).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
            <select className="select" aria-label="按级别筛选" value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
              <option value="">全部级别</option>
              {Object.entries(SEVERITY_LABELS).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </div>
          {events === null ? (
            <div style={{ padding: "var(--space-4)", display: "grid", gap: "var(--space-3)" }}>
              <Skeleton />
              <Skeleton />
            </div>
          ) : events.length === 0 ? (
            <EmptyState
              icon={<AlertTriangle size={40} aria-hidden />}
              title="没有风险事件"
              description="先创建规则再扫描；缺失报价的持仓会被跳过并说明原因。"
              action={<button className="btn btn--secondary" onClick={() => setTab("rules")}>去创建规则</button>}
            />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>级别</th>
                  <th>规则</th>
                  <th>说明</th>
                  <th className="cell--num">触发值 / 阈值</th>
                  <th>状态</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {events.map((ev) => (
                  <tr key={ev.id}>
                    <td className="num">{ev.as_of}</td>
                    <td><StatusBadge status={ev.severity} /></td>
                    <td>{RULE_TYPE_LABELS[ev.rule_type] ?? ev.rule_type}</td>
                    <td>{ev.message}</td>
                    <td className="cell--num num">
                      {pct(ev.trigger_value)} / {pct(ev.threshold)}
                    </td>
                    <td><StatusBadge status={ev.status} /></td>
                    <td className="cell--actions">
                      {ev.status === "OPEN" ? (
                        <span style={{ display: "inline-flex", gap: 6 }}>
                          <button className="btn btn--secondary" onClick={() => { setResolving({ event: ev, action: "acknowledge" }); setNote("") }}>
                            确认
                          </button>
                          <button className="btn btn--ghost" onClick={() => { setResolving({ event: ev, action: "ignore" }); setNote("") }}>
                            忽略
                          </button>
                        </span>
                      ) : (
                        <span style={{ color: "var(--color-muted-foreground)", fontSize: 12 }}>
                          {ev.resolution_note ?? "—"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "rules" && (
        <div className="card table-scroll">
          <div style={{ display: "flex", justifyContent: "flex-end", padding: "var(--space-2) var(--space-3)", borderBottom: "1px solid var(--color-border)" }}>
            <button className="btn btn--primary" onClick={openCreateRule}>
              <Plus size={16} aria-hidden /> 新建规则
            </button>
          </div>
          {rules === null ? (
            <div style={{ padding: "var(--space-4)", display: "grid", gap: "var(--space-3)" }}>
              <Skeleton />
              <Skeleton />
            </div>
          ) : rules.length === 0 ? (
            <EmptyState
              icon={<SlidersHorizontal size={40} aria-hidden />}
              title="还没有风险规则"
              description="例如：单品种权重超过 20%、组合回撤超过 10%、行情覆盖率低于 80%。"
              action={<button className="btn btn--primary" onClick={openCreateRule}>新建规则</button>}
            />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>范围</th>
                  <th>规则</th>
                  <th className="cell--num">阈值</th>
                  <th>级别</th>
                  <th className="cell--num">冷却（分钟）</th>
                  <th>启用</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id}>
                    <td>{SCOPE_LABELS[r.scope] ?? r.scope}</td>
                    <td>
                      {RULE_TYPE_LABELS[r.rule_type] ?? r.rule_type}
                      {r.memo && (
                        <div style={{ color: "var(--color-muted-foreground)", fontSize: 12 }}>{r.memo}</div>
                      )}
                    </td>
                    <td className="cell--num num">{pct(r.threshold)}</td>
                    <td><StatusBadge status={r.severity} /></td>
                    <td className="cell--num num">{r.cooldown_minutes}</td>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${r.enabled ? "停用" : "启用"}规则`}
                        checked={r.enabled}
                        onChange={() => toggleRule(r)}
                      />
                    </td>
                    <td className="cell--actions">
                      <button className="btn btn--secondary" onClick={() => openEditRule(r)}>编辑</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* 处理事件 */}
      <Dialog
        open={resolving !== null}
        title={resolving?.action === "ignore" ? "忽略风险事件" : "确认风险事件"}
        onClose={() => setResolving(null)}
      >
        {resolving && (
          <form onSubmit={(e) => { e.preventDefault(); resolve() }}>
            <p>{resolving.event.message}</p>
            <div className="field" style={{ marginTop: "var(--space-3)" }}>
              <label className="field__label" htmlFor="resolve-note">备注（可选）</label>
              <input
                id="resolve-note"
                className="input"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="记录处理方式或忽略原因"
              />
            </div>
            <div className="dialog__foot">
              <button type="button" className="btn btn--secondary" onClick={() => setResolving(null)}>取消</button>
              <button type="submit" className="btn btn--primary" disabled={busy}>提交</button>
            </div>
          </form>
        )}
      </Dialog>

      {/* 新建/编辑规则 */}
      <Dialog
        open={ruleDialog !== null}
        title={ruleDialog?.mode === "edit" ? "编辑风险规则" : "新建风险规则"}
        onClose={() => setRuleDialog(null)}
      >
        <form onSubmit={saveRule}>
          {ruleDialog?.mode === "create" ? (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
              <div className="field">
                <label className="field__label" htmlFor="rule-scope" aria-required="true">范围</label>
                <select
                  id="rule-scope"
                  className="select"
                  value={ruleForm.scope}
                  onChange={(e) => {
                    const scope = e.target.value
                    setRuleForm({
                      ...ruleForm,
                      scope,
                      rule_type: SCOPE_RULE_TYPES[scope]?.[0] ?? ruleForm.rule_type,
                    })
                  }}
                >
                  {Object.entries(SCOPE_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field__label" htmlFor="rule-type" aria-required="true">规则</label>
                <select
                  id="rule-type"
                  className="select"
                  value={ruleForm.rule_type}
                  onChange={(e) => setRuleForm({ ...ruleForm, rule_type: e.target.value })}
                >
                  {ruleTypes.map((t) => (
                    <option key={t} value={t}>{RULE_TYPE_LABELS[t] ?? t}</option>
                  ))}
                </select>
              </div>
            </div>
          ) : (
            <p style={{ color: "var(--color-muted-foreground)" }}>
              {SCOPE_LABELS[ruleForm.scope]} · {RULE_TYPE_LABELS[ruleForm.rule_type]}
              （范围与类型不可修改）
            </p>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
            <div className="field">
              <label className="field__label" htmlFor="rule-threshold" aria-required="true">阈值（%）</label>
              <input
                id="rule-threshold"
                className="input num"
                type="number"
                step="0.01"
                min="0.01"
                max="100"
                required
                value={ruleForm.threshold_percent}
                onChange={(e) => setRuleForm({ ...ruleForm, threshold_percent: e.target.value })}
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="rule-severity">级别</label>
              <select
                id="rule-severity"
                className="select"
                value={ruleForm.severity}
                onChange={(e) => setRuleForm({ ...ruleForm, severity: e.target.value })}
              >
                {Object.entries(SEVERITY_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="rule-cooldown">冷却时间（分钟）</label>
            <input
              id="rule-cooldown"
              className="input num"
              type="number"
              min="0"
              step="1"
              value={ruleForm.cooldown_minutes}
              onChange={(e) => setRuleForm({ ...ruleForm, cooldown_minutes: e.target.value })}
            />
          </div>
          <div className="field">
            <label className="field__label" htmlFor="rule-memo">备注</label>
            <input
              id="rule-memo"
              className="input"
              value={ruleForm.memo}
              onChange={(e) => setRuleForm({ ...ruleForm, memo: e.target.value })}
            />
          </div>
          <div className="dialog__foot">
            <button type="button" className="btn btn--secondary" onClick={() => setRuleDialog(null)}>取消</button>
            <button type="submit" className="btn btn--primary" disabled={busy}>保存</button>
          </div>
        </form>
      </Dialog>
    </div>
  )
}
