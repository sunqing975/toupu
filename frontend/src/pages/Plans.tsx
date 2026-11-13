import { useEffect, useState } from "react"
import { CheckCircle2, ClipboardList, Plus, Target, XCircle } from "lucide-react"
import {
  PROPOSAL_STATUS_LABELS,
  TXN_LABELS,
  plansApi,
  type Plan,
  type PlanDetail,
  type Proposal,
} from "../api/risk"
import { fmtAmount } from "../api/transactions"
import { Dialog } from "../components/Dialog"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"
import { StatusBadge } from "../components/StatusBadge"
import { useToast } from "../components/Toast"

const fmtTime = (iso: string) => new Date(iso).toLocaleString("zh-CN", { hour12: false })

type ProposalView = {
  transaction_type?: string
  account_id?: string
  amount?: string
}

type ImpactView = {
  asset?: string
  amount?: string
  currency?: string
  impact?: string
}

const CURRENCY_SYMBOL: Record<string, string> = { CNY: "¥" }

function currencySymbol(currency?: string): string {
  return (currency && CURRENCY_SYMBOL[currency]) || currency || "¥"
}

function proposalTitle(p: Proposal): string {
  const payload = p.payload as ProposalView
  const impact = p.impact_preview as ImpactView
  const label = TXN_LABELS[payload.transaction_type ?? ""] ?? payload.transaction_type ?? "交易"
  const amount = impact.amount ?? payload.amount
  return `${impact.asset ?? ""} · ${label}${amount ? ` ${currencySymbol(impact.currency)} ${fmtAmount(amount)}` : ""}`
}

export function Plans() {
  const toast = useToast()
  const [tab, setTab] = useState<"proposals" | "plans">("proposals")
  const [proposals, setProposals] = useState<Proposal[] | null>(null)
  const [statusFilter, setStatusFilter] = useState("")
  const [plans, setPlans] = useState<Plan[] | null>(null)
  const [detail, setDetail] = useState<Proposal | null>(null)
  const [approving, setApproving] = useState<Proposal | null>(null)
  const [rejecting, setRejecting] = useState<Proposal | null>(null)
  const [note, setNote] = useState("")
  const [busy, setBusy] = useState(false)

  const [planDialog, setPlanDialog] = useState(false)
  const [planForm, setPlanForm] = useState({ name: "", description: "", target_amount: "" })
  const [planDetail, setPlanDetail] = useState<PlanDetail | null>(null)
  const [archiving, setArchiving] = useState<Plan | null>(null)
  const [actionForm, setActionForm] = useState({ title: "", note: "", target_amount: "", sort_no: "0" })

  const loadProposals = () => {
    setProposals(null)
    plansApi
      .proposals(statusFilter || undefined)
      .then(setProposals)
      .catch(() => setProposals([]))
  }

  const loadPlans = () => {
    setPlans(null)
    plansApi.plans().then(setPlans).catch(() => setPlans([]))
  }

  useEffect(() => {
    loadProposals()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter])

  useEffect(() => {
    loadPlans()
  }, [])

  const approve = async () => {
    if (!approving) return
    setBusy(true)
    try {
      await plansApi.approveProposal(approving.id, note || null)
      toast("success", "已批准：只生成交易草稿，请到交易页确认并过账")
      setApproving(null)
      setNote("")
      loadProposals()
    } catch (e) {
      toast("error", (e as Error).message)
      loadProposals()
    } finally {
      setBusy(false)
    }
  }

  const reject = async () => {
    if (!rejecting) return
    setBusy(true)
    try {
      await plansApi.rejectProposal(rejecting.id, note || null)
      toast("success", "提案已拒绝")
      setRejecting(null)
      setNote("")
      loadProposals()
    } catch (e) {
      toast("error", (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const createPlan = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      await plansApi.createPlan({
        name: planForm.name,
        description: planForm.description || null,
        target_amount: planForm.target_amount || null,
      })
      toast("success", "投资计划已创建")
      setPlanDialog(false)
      setPlanForm({ name: "", description: "", target_amount: "" })
      loadPlans()
    } catch (err) {
      toast("error", (err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const openPlan = async (id: string) => {
    try {
      setPlanDetail(await plansApi.plan(id))
    } catch (e) {
      toast("error", (e as Error).message)
    }
  }

  const addAction = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!planDetail) return
    setBusy(true)
    try {
      await plansApi.addAction(planDetail.id, {
        title: actionForm.title,
        note: actionForm.note || null,
        target_amount: actionForm.target_amount || null,
        sort_no: Number(actionForm.sort_no),
      })
      toast("success", "计划条目已添加")
      setActionForm({ title: "", note: "", target_amount: "", sort_no: "0" })
      setPlanDetail(await plansApi.plan(planDetail.id))
    } catch (err) {
      toast("error", (err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const archive = async () => {
    if (!archiving) return
    setBusy(true)
    try {
      await plansApi.archivePlan(archiving.id)
      toast("success", "投资计划已归档")
      setArchiving(null)
      if (planDetail?.id === archiving.id) setPlanDetail(null)
      loadPlans()
    } catch (e) {
      toast("error", (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <div className="page__head">
        <p className="page__sub">
          Agent 只能提交提案；批准只生成交易草稿（DRAFT），绝不自动入账。计划是决策记录，不触发账务。
        </p>
      </div>

      <div style={{ display: "flex", gap: "var(--space-2)", borderBottom: "1px solid var(--color-border)", marginBottom: "var(--space-4)" }}>
        <button className={`btn ${tab === "proposals" ? "btn--primary" : "btn--ghost"}`} onClick={() => setTab("proposals")}>
          <ClipboardList size={14} aria-hidden /> 待审批提案
        </button>
        <button className={`btn ${tab === "plans" ? "btn--primary" : "btn--ghost"}`} onClick={() => setTab("plans")}>
          <Target size={14} aria-hidden /> 投资计划
        </button>
      </div>

      {tab === "proposals" && (
        <div className="card table-scroll">
          <div style={{ display: "flex", gap: "var(--space-2)", padding: "var(--space-2) var(--space-3)", borderBottom: "1px solid var(--color-border)" }}>
            <select className="select" aria-label="按状态筛选" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">全部状态</option>
              {Object.entries(PROPOSAL_STATUS_LABELS).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </div>
          {proposals === null ? (
            <div style={{ padding: "var(--space-4)", display: "grid", gap: "var(--space-3)" }}>
              <Skeleton />
              <Skeleton />
            </div>
          ) : proposals.length === 0 ? (
            <EmptyState
              icon={<ClipboardList size={40} aria-hidden />}
              title="没有提案"
              description="Agent 通过 API 提交的现金类草稿提案会出现在这里，等待你审批。"
            />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>创建时间</th>
                  <th>摘要</th>
                  <th>到期</th>
                  <th>状态</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {proposals.map((p) => (
                  <tr key={p.id}>
                    <td className="num">{fmtTime(p.created_at)}</td>
                    <td>{proposalTitle(p)}</td>
                    <td className="num">{fmtTime(p.expires_at)}</td>
                    <td>
                      {p.is_expired && p.status === "PENDING" ? (
                        <span className="badge badge--gray">已过期</span>
                      ) : (
                        <StatusBadge status={p.status} />
                      )}
                    </td>
                    <td className="cell--actions">
                      <span style={{ display: "inline-flex", gap: 6 }}>
                        <button className="btn btn--secondary" onClick={() => setDetail(p)}>查看</button>
                        {p.status === "PENDING" && !p.is_expired && (
                          <>
                            <button className="btn btn--primary" onClick={() => { setApproving(p); setNote("") }}>
                              <CheckCircle2 size={14} aria-hidden /> 批准
                            </button>
                            <button className="btn btn--ghost" onClick={() => { setRejecting(p); setNote("") }}>
                              <XCircle size={14} aria-hidden /> 拒绝
                            </button>
                          </>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "plans" && (
        <div className="card table-scroll">
          <div style={{ display: "flex", justifyContent: "flex-end", padding: "var(--space-2) var(--space-3)", borderBottom: "1px solid var(--color-border)" }}>
            <button className="btn btn--primary" onClick={() => setPlanDialog(true)}>
              <Plus size={16} aria-hidden /> 新建计划
            </button>
          </div>
          {plans === null ? (
            <div style={{ padding: "var(--space-4)", display: "grid", gap: "var(--space-3)" }}>
              <Skeleton />
              <Skeleton />
            </div>
          ) : plans.length === 0 ? (
            <EmptyState
              icon={<Target size={40} aria-hidden />}
              title="还没有投资计划"
              description="记录目标金额与执行条目，作为决策依据；计划不会生成任何交易。"
              action={<button className="btn btn--primary" onClick={() => setPlanDialog(true)}>新建计划</button>}
            />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>名称</th>
                  <th>说明</th>
                  <th className="cell--num">目标金额</th>
                  <th>状态</th>
                  <th>创建时间</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {plans.map((p) => (
                  <tr key={p.id}>
                    <td>{p.name}</td>
                    <td style={{ color: "var(--color-muted-foreground)" }}>{p.description ?? "—"}</td>
                    <td className="cell--num num">{fmtAmount(p.target_amount)}</td>
                    <td>
                      {p.status === "ACTIVE" ? (
                        <span className="badge badge--green">进行中</span>
                      ) : (
                        <StatusBadge status={p.status} />
                      )}
                    </td>
                    <td className="num">{fmtTime(p.created_at)}</td>
                    <td className="cell--actions">
                      <span style={{ display: "inline-flex", gap: 6 }}>
                        <button className="btn btn--secondary" onClick={() => openPlan(p.id)}>查看</button>
                        {p.status === "ACTIVE" && (
                          <button className="btn btn--ghost" onClick={() => setArchiving(p)}>归档</button>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* 提案详情 */}
      <Dialog open={detail !== null} title="提案详情" onClose={() => setDetail(null)}>
        {detail && (
          <>
            <table className="table">
              <tbody>
                <tr><td style={{ color: "var(--color-muted-foreground)" }}>类型</td><td>{detail.proposal_type}</td></tr>
                <tr><td style={{ color: "var(--color-muted-foreground)" }}>提交方</td><td>{detail.created_by}</td></tr>
                <tr><td style={{ color: "var(--color-muted-foreground)" }}>状态</td><td><StatusBadge status={detail.status} /></td></tr>
                <tr><td style={{ color: "var(--color-muted-foreground)" }}>资产</td><td>{(detail.impact_preview as ImpactView).asset ?? "—"}</td></tr>
                <tr><td style={{ color: "var(--color-muted-foreground)" }}>金额</td><td className="num">{fmtAmount((detail.impact_preview as ImpactView).amount ?? null)}</td></tr>
                <tr><td style={{ color: "var(--color-muted-foreground)" }}>影响</td><td>{(detail.impact_preview as ImpactView).impact ?? "—"}</td></tr>
                <tr><td style={{ color: "var(--color-muted-foreground)" }}>创建 / 到期</td><td className="num">{fmtTime(detail.created_at)} → {fmtTime(detail.expires_at)}</td></tr>
                {detail.resulting_transaction_id && (
                  <tr><td style={{ color: "var(--color-muted-foreground)" }}>生成的草稿</td><td className="num">{detail.resulting_transaction_id}</td></tr>
                )}
                {detail.resolution_note && (
                  <tr><td style={{ color: "var(--color-muted-foreground)" }}>处理备注</td><td>{detail.resolution_note}</td></tr>
                )}
              </tbody>
            </table>
            <details style={{ marginTop: "var(--space-3)" }}>
              <summary style={{ cursor: "pointer", color: "var(--color-muted-foreground)" }}>原始载荷与校验快照</summary>
              <pre style={{ fontSize: 12, overflowX: "auto", background: "var(--color-muted)", padding: "var(--space-2)" }}>
                {JSON.stringify({ payload: detail.payload, validation_snapshot: detail.validation_snapshot }, null, 2)}
              </pre>
            </details>
          </>
        )}
      </Dialog>

      {/* 批准 */}
      <Dialog open={approving !== null} title="批准提案" onClose={() => setApproving(null)}>
        {approving && (
          <form onSubmit={(e) => { e.preventDefault(); approve() }}>
            <p>{proposalTitle(approving)}</p>
            <p style={{ marginTop: "var(--space-2)", color: "var(--color-muted-foreground)" }}>
              {(approving.impact_preview as ImpactView).impact ?? "仅生成草稿，不入账"}
            </p>
            <div className="banner banner--warning" style={{ marginTop: "var(--space-3)" }}>
              批准后只会生成一笔交易草稿（DRAFT），不会改变余额或持仓；请在交易页确认并过账。
            </div>
            <div className="field" style={{ marginTop: "var(--space-3)" }}>
              <label className="field__label" htmlFor="approve-note">备注（可选）</label>
              <input id="approve-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            <div className="dialog__foot">
              <button type="button" className="btn btn--secondary" onClick={() => setApproving(null)}>取消</button>
              <button type="submit" className="btn btn--primary" disabled={busy}>确认批准</button>
            </div>
          </form>
        )}
      </Dialog>

      {/* 拒绝 */}
      <Dialog open={rejecting !== null} title="拒绝提案" onClose={() => setRejecting(null)}>
        {rejecting && (
          <form onSubmit={(e) => { e.preventDefault(); reject() }}>
            <p>{proposalTitle(rejecting)}</p>
            <div className="field" style={{ marginTop: "var(--space-3)" }}>
              <label className="field__label" htmlFor="reject-note">拒绝原因（可选）</label>
              <input id="reject-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            <div className="dialog__foot">
              <button type="button" className="btn btn--secondary" onClick={() => setRejecting(null)}>取消</button>
              <button type="submit" className="btn btn--destructive" disabled={busy}>确认拒绝</button>
            </div>
          </form>
        )}
      </Dialog>

      {/* 新建计划 */}
      <Dialog open={planDialog} title="新建投资计划" onClose={() => setPlanDialog(false)}>
        <form onSubmit={createPlan}>
          <div className="field">
            <label className="field__label" htmlFor="plan-name" aria-required="true">名称</label>
            <input
              id="plan-name"
              className="input"
              required
              value={planForm.name}
              onChange={(e) => setPlanForm({ ...planForm, name: e.target.value })}
              placeholder="例如：2027 年指数基金定投"
            />
          </div>
          <div className="field">
            <label className="field__label" htmlFor="plan-desc">说明</label>
            <input
              id="plan-desc"
              className="input"
              value={planForm.description}
              onChange={(e) => setPlanForm({ ...planForm, description: e.target.value })}
            />
          </div>
          <div className="field">
            <label className="field__label" htmlFor="plan-target">目标金额</label>
            <input
              id="plan-target"
              className="input num"
              type="number"
              step="0.000001"
              min="0.000001"
              value={planForm.target_amount}
              onChange={(e) => setPlanForm({ ...planForm, target_amount: e.target.value })}
            />
          </div>
          <div className="dialog__foot">
            <button type="button" className="btn btn--secondary" onClick={() => setPlanDialog(false)}>取消</button>
            <button type="submit" className="btn btn--primary" disabled={busy || !planForm.name}>保存</button>
          </div>
        </form>
      </Dialog>

      {/* 计划详情 */}
      <Dialog open={planDetail !== null} title="投资计划" onClose={() => setPlanDetail(null)}>
        {planDetail && (
          <>
            <table className="table">
              <tbody>
                <tr><td style={{ color: "var(--color-muted-foreground)" }}>名称</td><td>{planDetail.name}</td></tr>
                <tr><td style={{ color: "var(--color-muted-foreground)" }}>说明</td><td>{planDetail.description ?? "—"}</td></tr>
                <tr><td style={{ color: "var(--color-muted-foreground)" }}>目标金额</td><td className="num">{fmtAmount(planDetail.target_amount)}</td></tr>
                <tr><td style={{ color: "var(--color-muted-foreground)" }}>状态</td><td>{planDetail.status === "ACTIVE" ? "进行中" : <StatusBadge status={planDetail.status} />}</td></tr>
              </tbody>
            </table>

            <div className="card__title" style={{ margin: "var(--space-4) 0 var(--space-2)" }}>执行条目</div>
            {planDetail.actions.length === 0 ? (
              <p style={{ color: "var(--color-muted-foreground)" }}>还没有条目。</p>
            ) : (
              <table className="table">
                <thead>
                  <tr><th className="cell--num">序号</th><th>事项</th><th className="cell--num">目标金额</th></tr>
                </thead>
                <tbody>
                  {planDetail.actions.map((a) => (
                    <tr key={a.id}>
                      <td className="cell--num num">{a.sort_no}</td>
                      <td>
                        {a.title}
                        {a.note && <div style={{ color: "var(--color-muted-foreground)", fontSize: 12 }}>{a.note}</div>}
                      </td>
                      <td className="cell--num num">{fmtAmount(a.target_amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {planDetail.status === "ACTIVE" && (
              <form onSubmit={addAction} style={{ marginTop: "var(--space-3)" }}>
                <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: "var(--space-2)" }}>
                  <div className="field">
                    <label className="field__label" htmlFor="action-title" aria-required="true">新增条目</label>
                    <input
                      id="action-title"
                      className="input"
                      required
                      value={actionForm.title}
                      onChange={(e) => setActionForm({ ...actionForm, title: e.target.value })}
                      placeholder="例如：每月定投 2000"
                    />
                  </div>
                  <div className="field">
                    <label className="field__label" htmlFor="action-amount">目标金额</label>
                    <input
                      id="action-amount"
                      className="input num"
                      type="number"
                      step="0.000001"
                      min="0.000001"
                      value={actionForm.target_amount}
                      onChange={(e) => setActionForm({ ...actionForm, target_amount: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label className="field__label" htmlFor="action-sort">序号</label>
                    <input
                      id="action-sort"
                      className="input num"
                      type="number"
                      step="1"
                      value={actionForm.sort_no}
                      onChange={(e) => setActionForm({ ...actionForm, sort_no: e.target.value })}
                    />
                  </div>
                </div>
                <div className="field">
                  <label className="field__label" htmlFor="action-note">备注</label>
                  <input
                    id="action-note"
                    className="input"
                    value={actionForm.note}
                    onChange={(e) => setActionForm({ ...actionForm, note: e.target.value })}
                  />
                </div>
                <button type="submit" className="btn btn--secondary" disabled={busy || !actionForm.title}>
                  <Plus size={14} aria-hidden /> 添加条目
                </button>
              </form>
            )}
          </>
        )}
      </Dialog>

      {/* 归档确认 */}
      <Dialog open={archiving !== null} title="归档投资计划" onClose={() => setArchiving(null)}>
        {archiving && (
          <>
            <p>确定归档「{archiving.name}」？归档后不再出现在进行中的计划里，记录保留。</p>
            <div className="dialog__foot">
              <button className="btn btn--secondary" onClick={() => setArchiving(null)}>取消</button>
              <button className="btn btn--destructive" disabled={busy} onClick={archive}>确认归档</button>
            </div>
          </>
        )}
      </Dialog>
    </div>
  )
}
