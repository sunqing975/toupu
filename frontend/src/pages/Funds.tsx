import { useEffect, useState } from "react"
import {
  BadgeCheck,
  Ban,
  Check,
  Eye,
  Landmark,
  Plus,
  Send,
  Undo2,
  XCircle,
} from "lucide-react"
import { accountsApi } from "../api/accounts"
import { instrumentsApi } from "../api/instruments"
import { transactionsApi, fmtAmount } from "../api/transactions"
import {
  fundsApi,
  FUND_TYPES,
  FUND_TYPE_LABELS,
  isTwoStageType,
  type FundOrder,
  type FundOrderDetail,
  type FundOrderCreate,
  type FundTxnType,
  type FundConfirmationIn,
} from "../api/funds"
import type { InvestmentAccount, Instrument } from "../api/types"
import { Dialog } from "../components/Dialog"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"
import { StatusBadge } from "../components/StatusBadge"
import { useToast } from "../components/Toast"

const STATUS_OPTIONS = ["", "DRAFT", "CONFIRMED", "POSTED", "REVERSED", "CANCELLED"] as const
const STATUS_LABELS: Record<string, string> = {
  DRAFT: "草稿",
  CONFIRMED: "已确认",
  POSTED: "已入账",
  REVERSED: "已冲正",
  CANCELLED: "已取消",
}

const today = () => new Date().toISOString().slice(0, 10)

type FormState = {
  transaction_type: FundTxnType
  account_id: string
  instrument_id: string
  business_date: string
  platform: string
  apply_amount: string
  apply_shares: string
  expected_fee: string
  memo: string
}

const EMPTY_FORM: FormState = {
  transaction_type: "FUND_SUBSCRIBE",
  account_id: "",
  instrument_id: "",
  business_date: today(),
  platform: "default",
  apply_amount: "",
  apply_shares: "",
  expected_fee: "",
  memo: "",
}

type ConfirmState = FundConfirmationIn

const emptyConfirm = (): ConfirmState => ({
  confirmation_date: today(),
  nav: "",
  confirmed_shares: "",
  confirmed_amount: "",
  fee_amount: "0",
})

// 各类型在申请阶段需要录入的字段说明（对齐后端 FundOrderIn.check_shape）。
const TYPE_HINTS: Record<FundTxnType, string> = {
  FUND_SUBSCRIBE: "申购：填写实际扣款总额（含申购费）。确认时需录入确认净值、份额与净申购金额，申购费 = 扣款 − 净申购金额。",
  FUND_REDEEM: "赎回：填写申请赎回份额。确认后按确认净值/份额减少持仓，记录净到账、出库成本与已实现损益。",
  CASH_DIVIDEND: "现金分红：填写现金到账金额。创建即确认，可直接入账，不增加份额。",
  DIVIDEND_REINVEST: "红利再投资：确认时按确认净值与份额增加持仓，不重复记现金。申请阶段无需填金额。",
}

export function Funds() {
  const toast = useToast()
  const [orders, setOrders] = useState<FundOrder[] | null>(null)
  const [accounts, setAccounts] = useState<InvestmentAccount[]>([])
  const [instruments, setInstruments] = useState<Instrument[]>([])
  const [accountFilter, setAccountFilter] = useState("")
  const [typeFilter, setTypeFilter] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [formOpen, setFormOpen] = useState(false)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [confirmTarget, setConfirmTarget] = useState<FundOrder | null>(null)
  const [confirmForm, setConfirmForm] = useState<ConfirmState>(emptyConfirm)
  const [failTarget, setFailTarget] = useState<FundOrder | null>(null)
  const [reversing, setReversing] = useState<FundOrder | null>(null)
  const [detail, setDetail] = useState<FundOrderDetail | null>(null)

  const accountName = (id: string) =>
    accounts.find((a) => a.id === id)?.name ?? id.slice(0, 8)
  const instrumentName = (id: string) =>
    instruments.find((i) => i.id === id)?.name ?? id.slice(0, 8)

  useEffect(() => {
    accountsApi.list().then(setAccounts).catch(() => setAccounts([]))
    instrumentsApi.list("FUND").then(setInstruments).catch(() => setInstruments([]))
  }, [])

  const load = () => {
    fundsApi
      .list({
        account_id: accountFilter || undefined,
        transaction_type: typeFilter || undefined,
        status_filter: statusFilter || undefined,
      })
      .then(setOrders)
      .catch((e: unknown) => setError(String((e as Error).message)))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountFilter, typeFilter, statusFilter])

  const openForm = () => {
    setForm({ ...EMPTY_FORM, business_date: today() })
    setFormOpen(true)
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      const t = form.transaction_type
      const payload: FundOrderCreate = {
        transaction_type: t,
        account_id: form.account_id,
        instrument_id: form.instrument_id,
        business_date: form.business_date,
        platform: form.platform || "default",
        memo: form.memo || null,
      }
      if (t === "FUND_SUBSCRIBE" || t === "CASH_DIVIDEND") {
        payload.apply_amount = form.apply_amount
      }
      if (t === "FUND_REDEEM") {
        payload.apply_shares = form.apply_shares
      }
      if (form.expected_fee) {
        payload.expected_fee = form.expected_fee
      }
      await fundsApi.create(payload)
      toast(
        "success",
        t === "CASH_DIVIDEND" ? "现金分红已记录，可直接入账" : "基金申请草稿已保存，请录入确认信息",
      )
      setFormOpen(false)
      load()
    } catch (err) {
      toast("error", (err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const openConfirm = (o: FundOrder) => {
    setConfirmForm({
      ...emptyConfirm(),
      confirmed_shares: o.apply_shares ?? "",
    })
    setConfirmTarget(o)
  }

  const submitConfirm = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!confirmTarget) return
    setBusy(true)
    try {
      await fundsApi.confirm(confirmTarget.id, confirmForm)
      toast("success", "确认信息已录入，可入账")
      setConfirmTarget(null)
      load()
    } catch (err) {
      toast("error", (err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // 申购金额守恒（§15.2）：实际扣款 = 净申购金额 + 申购费。展示层即时校验。
  const conservation =
    confirmTarget?.transaction_type === "FUND_SUBSCRIBE"
      ? {
          apply: Number(confirmTarget.apply_amount ?? 0),
          sum: Number(confirmForm.confirmed_amount || 0) + Number(confirmForm.fee_amount || 0),
          valid:
            confirmForm.confirmed_amount !== "" &&
            Number(confirmTarget.apply_amount ?? 0) ===
              Number(confirmForm.confirmed_amount || 0) + Number(confirmForm.fee_amount || 0),
        }
      : null

  const act = async (o: FundOrder, action: "post" | "cancel") => {
    setBusy(true)
    try {
      await transactionsApi[action](o.id)
      toast("success", action === "post" ? "已入账" : "申请已取消")
      load()
    } catch (err) {
      toast("error", (err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const confirmFail = async () => {
    if (!failTarget) return
    setBusy(true)
    try {
      await fundsApi.fail(failTarget.id)
      toast("success", "申请已标记失败")
      setFailTarget(null)
      load()
    } catch (err) {
      toast("error", (err as Error).message)
      setFailTarget(null)
    } finally {
      setBusy(false)
    }
  }

  const reverse = async () => {
    if (!reversing) return
    setBusy(true)
    try {
      await transactionsApi.reverse(reversing.id)
      toast("success", "已冲正，原记录保留")
      setReversing(null)
      load()
    } catch (err) {
      toast("error", (err as Error).message)
      setReversing(null)
    } finally {
      setBusy(false)
    }
  }

  const showDetail = async (id: string) => {
    try {
      setDetail(await fundsApi.get(id))
    } catch (err) {
      toast("error", (err as Error).message)
    }
  }

  const actions = (o: FundOrder) => {
    const twoStage = isTwoStageType(o.transaction_type)
    const needsConfirm = twoStage && o.status === "DRAFT" && o.confirmation_status === "PENDING"
    return (
      <span className="cell--actions" style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
        {needsConfirm && (
          <button className="btn btn--primary" disabled={busy} onClick={() => openConfirm(o)}>
            <BadgeCheck size={14} aria-hidden /> 录入确认
          </button>
        )}
        {o.status === "CONFIRMED" && (
          <button className="btn btn--primary" disabled={busy} onClick={() => act(o, "post")}>
            <Send size={14} aria-hidden /> 过账
          </button>
        )}
        {o.status === "POSTED" && o.transaction_type !== "FUND_REDEEM" && (
          <button className="btn btn--destructive" disabled={busy} onClick={() => setReversing(o)}>
            <Undo2 size={14} aria-hidden /> 冲正
          </button>
        )}
        {needsConfirm && (
          <button className="btn btn--secondary" disabled={busy} onClick={() => setFailTarget(o)}>
            <XCircle size={14} aria-hidden /> 标记失败
          </button>
        )}
        {(o.status === "DRAFT" || o.status === "CONFIRMED") && (
          <button className="btn btn--secondary" disabled={busy} onClick={() => act(o, "cancel")}>
            <Ban size={14} aria-hidden /> 取消
          </button>
        )}
        <button className="btn btn--secondary" onClick={() => showDetail(o.id)} aria-label={`查看申请 ${o.id}`}>
          <Eye size={14} aria-hidden />
        </button>
      </span>
    )
  }

  const confirmable = confirmForm.confirmation_date && confirmForm.nav && confirmForm.confirmed_shares && confirmForm.confirmed_amount
  const confirmDisabled = busy || !confirmable || (conservation !== null && !conservation.valid)

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <p className="page__sub">
            场外基金：申购 / 赎回需先申请、再录入确认净值与份额；现金分红与红利再投资见各处说明
          </p>
        </div>
        <button className="btn btn--primary" onClick={openForm}>
          <Plus size={16} aria-hidden />
          新建基金申请
        </button>
      </div>

      {error && <div className="banner banner--error">{error}</div>}

      <div className="card table-scroll">
        <div
          style={{
            display: "flex",
            gap: "var(--space-2)",
            padding: "var(--space-2) var(--space-3)",
            borderBottom: "1px solid var(--color-border)",
            flexWrap: "wrap",
          }}
        >
          <select className="select" aria-label="按账户筛选" value={accountFilter} onChange={(e) => setAccountFilter(e.target.value)}>
            <option value="">全部账户</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          <select className="select" aria-label="按类型筛选" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
            <option value="">全部类型</option>
            {FUND_TYPES.map((t) => (
              <option key={t} value={t}>
                {FUND_TYPE_LABELS[t]}
              </option>
            ))}
          </select>
          <select className="select" aria-label="按状态筛选" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s ? STATUS_LABELS[s] : "全部状态"}
              </option>
            ))}
          </select>
        </div>

        {orders === null ? (
          <div style={{ padding: "var(--space-4)", display: "grid", gap: "var(--space-3)" }}>
            <Skeleton />
            <Skeleton />
          </div>
        ) : orders.length === 0 ? (
          <EmptyState
            icon={<Landmark size={40} aria-hidden />}
            title="还没有基金申请"
            description="从一笔申购开始：填写扣款金额，确认净值份额后即可入账。"
            action={
              <button className="btn btn--primary" onClick={openForm}>
                新建基金申请
              </button>
            }
          />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>日期</th>
                <th>类型</th>
                <th>账户 / 品种</th>
                <th>渠道</th>
                <th className="cell--num">申请</th>
                <th>状态</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td className="num">{o.business_date}</td>
                  <td>{FUND_TYPE_LABELS[o.transaction_type] ?? o.transaction_type}</td>
                  <td>
                    {accountName(o.account_id)}
                    <div style={{ color: "var(--color-muted-foreground)", fontSize: 12 }}>
                      {instrumentName(o.instrument_id)}
                    </div>
                  </td>
                  <td>{o.platform}</td>
                  <td className="cell--num num">
                    {o.apply_amount !== null ? `¥${fmtAmount(o.apply_amount)}` : ""}
                    {o.apply_shares !== null && (
                      <div style={{ color: "var(--color-muted-foreground)", fontSize: 12 }}>
                        {fmtAmount(o.apply_shares)} 份
                      </div>
                    )}
                    {o.apply_amount === null && o.apply_shares === null && "—"}
                  </td>
                  <td>
                    <StatusBadge status={o.status} />
                    {o.confirmation_status === "PENDING" && (
                      <div style={{ color: "var(--color-muted-foreground)", fontSize: 12, marginTop: 2 }}>
                        待确认
                      </div>
                    )}
                    {o.confirmation_status === "FAILED" && (
                      <div style={{ color: "var(--color-muted-foreground)", fontSize: 12, marginTop: 2 }}>
                        确认失败
                      </div>
                    )}
                  </td>
                  <td className="cell--actions">{actions(o)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 新建申请 */}
      <Dialog open={formOpen} title="新建基金申请" onClose={() => setFormOpen(false)}>
        <form onSubmit={submit}>
          <div className="field">
            <label className="field__label" htmlFor="fund-type" aria-required="true">
              类型
            </label>
            <select
              id="fund-type"
              className="select"
              value={form.transaction_type}
              onChange={(e) => setForm({ ...form, transaction_type: e.target.value as FundTxnType })}
            >
              {FUND_TYPES.map((t) => (
                <option key={t} value={t}>
                  {FUND_TYPE_LABELS[t]}
                </option>
              ))}
            </select>
            <p style={{ color: "var(--color-muted-foreground)", fontSize: 12, marginTop: "var(--space-1)" }}>
              {TYPE_HINTS[form.transaction_type]}
            </p>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
            <div className="field">
              <label className="field__label" htmlFor="fund-account" aria-required="true">
                账户
              </label>
              <select
                id="fund-account"
                className="select"
                required
                value={form.account_id}
                onChange={(e) => setForm({ ...form, account_id: e.target.value })}
              >
                <option value="">选择账户</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label className="field__label" htmlFor="fund-instrument" aria-required="true">
                基金品种
              </label>
              <select
                id="fund-instrument"
                className="select"
                required
                value={form.instrument_id}
                onChange={(e) => setForm({ ...form, instrument_id: e.target.value })}
              >
                <option value="">选择基金</option>
                {instruments.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name}（{i.code}）
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
            <div className="field">
              <label className="field__label" htmlFor="fund-date" aria-required="true">
                申请日期
              </label>
              <input
                id="fund-date"
                className="input num"
                type="date"
                required
                value={form.business_date}
                onChange={(e) => setForm({ ...form, business_date: e.target.value })}
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="fund-platform">
                渠道 / 平台
              </label>
              <input
                id="fund-platform"
                className="input"
                value={form.platform}
                onChange={(e) => setForm({ ...form, platform: e.target.value })}
                placeholder="默认 default"
              />
            </div>
          </div>
          {(form.transaction_type === "FUND_SUBSCRIBE" || form.transaction_type === "CASH_DIVIDEND") && (
            <div className="field">
              <label className="field__label" htmlFor="fund-amount" aria-required="true">
                {form.transaction_type === "FUND_SUBSCRIBE" ? "实际扣款总额（含申购费）" : "现金到账金额"}
              </label>
              <input
                id="fund-amount"
                className="input num"
                type="number"
                step="0.000001"
                min="0.000001"
                required
                value={form.apply_amount}
                onChange={(e) => setForm({ ...form, apply_amount: e.target.value })}
                placeholder="0.00"
              />
            </div>
          )}
          {form.transaction_type === "FUND_REDEEM" && (
            <div className="field">
              <label className="field__label" htmlFor="fund-shares" aria-required="true">
                申请赎回份额
              </label>
              <input
                id="fund-shares"
                className="input num"
                type="number"
                step="0.000001"
                min="0.000001"
                required
                value={form.apply_shares}
                onChange={(e) => setForm({ ...form, apply_shares: e.target.value })}
                placeholder="0.00"
              />
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
            <div className="field">
              <label className="field__label" htmlFor="fund-fee">
                预计费用（选填）
              </label>
              <input
                id="fund-fee"
                className="input num"
                type="number"
                step="0.000001"
                min="0"
                value={form.expected_fee}
                onChange={(e) => setForm({ ...form, expected_fee: e.target.value })}
                placeholder="0.00"
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="fund-memo">
                备注
              </label>
              <input
                id="fund-memo"
                className="input"
                value={form.memo}
                onChange={(e) => setForm({ ...form, memo: e.target.value })}
              />
            </div>
          </div>
          <div
            className="dialog__foot"
            style={{ margin: "0 calc(-1 * var(--space-5))", marginBottom: "calc(-1 * var(--space-5))" }}
          >
            <button type="button" className="btn btn--secondary" onClick={() => setFormOpen(false)}>
              取消
            </button>
            <button
              type="submit"
              className="btn btn--primary"
              disabled={
                busy ||
                !form.account_id ||
                !form.instrument_id ||
                (form.transaction_type === "FUND_REDEEM" ? !form.apply_shares : false) ||
                (form.transaction_type === "FUND_SUBSCRIBE" || form.transaction_type === "CASH_DIVIDEND"
                  ? !form.apply_amount
                  : false)
              }
            >
              保存申请
            </button>
          </div>
        </form>
      </Dialog>

      {/* 录入确认 */}
      <Dialog open={confirmTarget !== null} title="录入确认信息" onClose={() => setConfirmTarget(null)}>
        <form onSubmit={submitConfirm}>
          {confirmTarget && (
            <p style={{ color: "var(--color-muted-foreground)", marginBottom: "var(--space-3)" }}>
              {FUND_TYPE_LABELS[confirmTarget.transaction_type]} · {instrumentName(confirmTarget.instrument_id)}
              {confirmTarget.apply_amount !== null && ` · 申请金额 ¥${fmtAmount(confirmTarget.apply_amount)}`}
              {confirmTarget.apply_shares !== null && ` · 申请份额 ${fmtAmount(confirmTarget.apply_shares)}`}
            </p>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
            <div className="field">
              <label className="field__label" htmlFor="conf-date" aria-required="true">
                确认日期
              </label>
              <input
                id="conf-date"
                className="input num"
                type="date"
                required
                value={confirmForm.confirmation_date}
                onChange={(e) => setConfirmForm({ ...confirmForm, confirmation_date: e.target.value })}
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="conf-nav" aria-required="true">
                确认净值
              </label>
              <input
                id="conf-nav"
                className="input num"
                type="number"
                step="0.000001"
                min="0.000001"
                required
                value={confirmForm.nav}
                onChange={(e) => setConfirmForm({ ...confirmForm, nav: e.target.value })}
                placeholder="2.000000"
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="conf-shares" aria-required="true">
                确认份额
              </label>
              <input
                id="conf-shares"
                className="input num"
                type="number"
                step="0.000001"
                min="0.000001"
                required
                value={confirmForm.confirmed_shares}
                onChange={(e) => setConfirmForm({ ...confirmForm, confirmed_shares: e.target.value })}
                placeholder="0.00"
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="conf-amount" aria-required="true">
                {confirmTarget?.transaction_type === "FUND_REDEEM" ? "赎回确认金额" : "净申购 / 再投资金额"}
              </label>
              <input
                id="conf-amount"
                className="input num"
                type="number"
                step="0.000001"
                min="0.000001"
                required
                value={confirmForm.confirmed_amount}
                onChange={(e) => setConfirmForm({ ...confirmForm, confirmed_amount: e.target.value })}
                placeholder="0.00"
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="conf-fee">
                {confirmTarget?.transaction_type === "FUND_SUBSCRIBE" ? "申购费" : "费用"}
              </label>
              <input
                id="conf-fee"
                className="input num"
                type="number"
                step="0.000001"
                min="0"
                value={confirmForm.fee_amount}
                onChange={(e) => setConfirmForm({ ...confirmForm, fee_amount: e.target.value })}
                placeholder="0.00"
              />
            </div>
          </div>
          {conservation && (
            <div
              className={conservation.valid ? "banner" : "banner banner--error"}
              style={{ marginTop: "var(--space-2)" }}
            >
              申购金额守恒：实际扣款 ¥{fmtAmount(String(conservation.apply))} = 净申购金额 ¥
              {fmtAmount(confirmForm.confirmed_amount || "0")} + 申购费 ¥
              {fmtAmount(confirmForm.fee_amount || "0")}（合计 ¥{fmtAmount(String(conservation.sum))}）
              {conservation.valid ? " ✓" : " —— 不相等，无法确认"}
            </div>
          )}
          {confirmTarget?.transaction_type !== "FUND_SUBSCRIBE" && (
            <p style={{ color: "var(--color-muted-foreground)", fontSize: 12, marginTop: "var(--space-2)" }}>
              确认数据到达后才会增减持仓份额；确认前不可入账。
            </p>
          )}
          <div
            className="dialog__foot"
            style={{ margin: "var(--space-4) calc(-1 * var(--space-5)) calc(-1 * var(--space-5))" }}
          >
            <button type="button" className="btn btn--secondary" onClick={() => setConfirmTarget(null)}>
              取消
            </button>
            <button type="submit" className="btn btn--primary" disabled={confirmDisabled}>
              <Check size={14} aria-hidden /> 确认
            </button>
          </div>
        </form>
      </Dialog>

      {/* 标记失败 */}
      <Dialog open={failTarget !== null} title="标记申请失败" onClose={() => setFailTarget(null)}>
        <p>
          确定将这笔 {failTarget ? FUND_TYPE_LABELS[failTarget.transaction_type] : ""} 申请标记为失败？
        </p>
        <p style={{ color: "var(--color-muted-foreground)", marginTop: "var(--space-2)" }}>
          状态置为已取消，不产生任何账务与持仓影响，记录保留可追溯。
        </p>
        <div
          className="dialog__foot"
          style={{ margin: "var(--space-4) calc(-1 * var(--space-5)) calc(-1 * var(--space-5))" }}
        >
          <button className="btn btn--secondary" onClick={() => setFailTarget(null)}>
            返回
          </button>
          <button className="btn btn--destructive" disabled={busy} onClick={confirmFail}>
            确认标记失败
          </button>
        </div>
      </Dialog>

      {/* 冲正确认 */}
      <Dialog open={reversing !== null} title="冲正基金交易" onClose={() => setReversing(null)}>
        <p>确定冲正这笔 {reversing ? FUND_TYPE_LABELS[reversing.transaction_type] : ""}？</p>
        <p style={{ color: "var(--color-muted-foreground)", marginTop: "var(--space-2)" }}>
          将生成反向分录，原记录标记为已冲正；现金分红无持仓批次，可直接冲正。
        </p>
        <div
          className="dialog__foot"
          style={{ margin: "var(--space-4) calc(-1 * var(--space-5)) calc(-1 * var(--space-5))" }}
        >
          <button className="btn btn--secondary" onClick={() => setReversing(null)}>
            取消
          </button>
          <button className="btn btn--destructive" disabled={busy} onClick={reverse}>
            确认冲正
          </button>
        </div>
      </Dialog>

      {/* 详情：申请 + 确认 + 分录 */}
      <Dialog open={detail !== null} title="基金申请详情" onClose={() => setDetail(null)}>
        {detail && (
          <>
            <table className="table">
              <tbody>
                <tr>
                  <td style={{ color: "var(--color-muted-foreground)" }}>类型</td>
                  <td>{FUND_TYPE_LABELS[detail.transaction_type] ?? detail.transaction_type}</td>
                </tr>
                <tr>
                  <td style={{ color: "var(--color-muted-foreground)" }}>账户 / 品种</td>
                  <td>
                    {accountName(detail.account_id)} · {instrumentName(detail.instrument_id)}
                  </td>
                </tr>
                <tr>
                  <td style={{ color: "var(--color-muted-foreground)" }}>渠道</td>
                  <td>{detail.platform}</td>
                </tr>
                <tr>
                  <td style={{ color: "var(--color-muted-foreground)" }}>状态</td>
                  <td>
                    <StatusBadge status={detail.status} />
                  </td>
                </tr>
                <tr>
                  <td style={{ color: "var(--color-muted-foreground)" }}>申请金额 / 份额</td>
                  <td className="num">
                    {detail.apply_amount !== null ? `¥${fmtAmount(detail.apply_amount)}` : "—"} /{" "}
                    {detail.apply_shares !== null ? `${fmtAmount(detail.apply_shares)} 份` : "—"}
                  </td>
                </tr>
              </tbody>
            </table>
            {detail.confirmation && (
              <>
                <div className="card__title" style={{ margin: "var(--space-4) 0 var(--space-2)" }}>
                  确认信息
                </div>
                <table className="table">
                  <tbody>
                    <tr>
                      <td style={{ color: "var(--color-muted-foreground)" }}>确认日期</td>
                      <td className="num">{detail.confirmation.confirmation_date}</td>
                    </tr>
                    <tr>
                      <td style={{ color: "var(--color-muted-foreground)" }}>确认净值</td>
                      <td className="num">{fmtAmount(detail.confirmation.nav)}</td>
                    </tr>
                    <tr>
                      <td style={{ color: "var(--color-muted-foreground)" }}>确认份额</td>
                      <td className="num">{fmtAmount(detail.confirmation.confirmed_shares)}</td>
                    </tr>
                    <tr>
                      <td style={{ color: "var(--color-muted-foreground)" }}>确认金额</td>
                      <td className="num">{fmtAmount(detail.confirmation.confirmed_amount)}</td>
                    </tr>
                    <tr>
                      <td style={{ color: "var(--color-muted-foreground)" }}>费用</td>
                      <td className="num">{fmtAmount(detail.confirmation.fee_amount)}</td>
                    </tr>
                  </tbody>
                </table>
              </>
            )}
            {detail.entry && (
              <>
                <div className="card__title" style={{ margin: "var(--space-4) 0 var(--space-2)" }}>
                  账务分录（{detail.entry.entry_type === "REVERSAL" ? "冲正" : "正常"}）
                </div>
                <table className="table">
                  <thead>
                    <tr>
                      <th>方向</th>
                      <th>科目</th>
                      <th className="cell--num">金额</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.entry.lines.map((l) => (
                      <tr key={l.ledger_account_id + l.direction}>
                        <td>{l.direction === "DEBIT" ? "借" : "贷"}</td>
                        <td>{l.ledger_account_name}</td>
                        <td className="cell--num num">{fmtAmount(l.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
            {!detail.confirmation && !detail.entry && (
              <p style={{ color: "var(--color-muted-foreground)", marginTop: "var(--space-3)" }}>
                尚未确认、尚未入账。请在列表中录入确认信息后再过账。
              </p>
            )}
          </>
        )}
      </Dialog>
    </div>
  )
}
