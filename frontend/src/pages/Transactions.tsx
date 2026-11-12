import { useEffect, useState } from "react"
import { ArrowLeftRight, Check, Ban, Undo2, Send, Eye } from "lucide-react"
import { accountsApi } from "../api/accounts"
import {
  TXN_TYPE_LABELS,
  fmtAmount,
  transactionsApi,
  type Txn,
  type TxnDetail,
} from "../api/transactions"
import type { InvestmentAccount } from "../api/types"
import { Dialog } from "../components/Dialog"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"
import { StatusBadge } from "../components/StatusBadge"
import { useToast } from "../components/Toast"

const FORM_TYPES = [
  { value: "DEPOSIT", label: "入金" },
  { value: "WITHDRAW", label: "出金" },
  { value: "ACCOUNT_TRANSFER", label: "转账" },
] as const

const STATUS_OPTIONS = ["", "DRAFT", "CONFIRMED", "POSTED", "REVERSED", "CANCELLED"] as const

type FormState = {
  transaction_type: string
  account_id: string
  counter_account_id: string
  business_date: string
  amount: string
  memo: string
}

const today = () => new Date().toISOString().slice(0, 10)

const EMPTY_FORM: FormState = {
  transaction_type: "DEPOSIT",
  account_id: "",
  counter_account_id: "",
  business_date: today(),
  amount: "",
  memo: "",
}

export function Transactions() {
  const toast = useToast()
  const [txns, setTxns] = useState<Txn[] | null>(null)
  const [accounts, setAccounts] = useState<InvestmentAccount[]>([])
  const [statusFilter, setStatusFilter] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [busy, setBusy] = useState(false)
  const [detail, setDetail] = useState<TxnDetail | null>(null)
  const [reversing, setReversing] = useState<Txn | null>(null)

  const accountName = (id: string | null) =>
    accounts.find((a) => a.id === id)?.name ?? (id ? "未知账户" : "—")

  useEffect(() => {
    accountsApi.list().then(setAccounts).catch(() => setAccounts([]))
  }, [])

  const load = (filter = statusFilter) => {
    transactionsApi
      .list({ status_filter: filter || undefined })
      .then(setTxns)
      .catch((e: unknown) => setError(String((e as Error).message)))
  }

  useEffect(() => {
    load(statusFilter)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      const body: Record<string, unknown> = {
        transaction_type: form.transaction_type,
        account_id: form.account_id,
        business_date: form.business_date,
        amount: form.amount,
        memo: form.memo || null,
      }
      if (form.transaction_type === "ACCOUNT_TRANSFER") {
        body.counter_account_id = form.counter_account_id
      }
      await transactionsApi.create(body)
      toast("success", "交易草稿已保存，确认后可入账")
      setFormOpen(false)
      setForm(EMPTY_FORM)
      load()
    } catch (err) {
      toast("error", (err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const act = async (id: string, action: "confirm" | "post" | "cancel") => {
    setBusy(true)
    try {
      await transactionsApi[action](id)
      toast("success", { confirm: "交易已确认", post: "交易已入账", cancel: "交易已取消" }[action])
      load()
    } catch (err) {
      toast("error", (err as Error).message)
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
      setDetail(await transactionsApi.get(id))
    } catch (err) {
      toast("error", (err as Error).message)
    }
  }

  const actions = (t: Txn) => (
    <span className="cell--actions" style={{ display: "inline-flex", gap: 6 }}>
      {t.status === "DRAFT" && (
        <button className="btn btn--secondary" disabled={busy} onClick={() => act(t.id, "confirm")}>
          <Check size={14} aria-hidden /> 确认
        </button>
      )}
      {t.status === "CONFIRMED" && (
        <button className="btn btn--primary" disabled={busy} onClick={() => act(t.id, "post")}>
          <Send size={14} aria-hidden /> 过账
        </button>
      )}
      {t.status === "POSTED" && (
        <button className="btn btn--destructive" disabled={busy} onClick={() => setReversing(t)}>
          <Undo2 size={14} aria-hidden /> 冲正
        </button>
      )}
      {(t.status === "DRAFT" || t.status === "CONFIRMED") && (
        <button className="btn btn--secondary" disabled={busy} onClick={() => act(t.id, "cancel")}>
          <Ban size={14} aria-hidden /> 取消
        </button>
      )}
      <button className="btn btn--secondary" onClick={() => showDetail(t.id)} aria-label={`查看交易 ${t.id}`}>
        <Eye size={14} aria-hidden />
      </button>
    </span>
  )

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <p className="page__sub">入金、出金与账户间转账；草稿确认后才可入账</p>
        </div>
        <button className="btn btn--primary" onClick={() => setFormOpen(true)}>
          <ArrowLeftRight size={16} aria-hidden />
          新建交易
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
          }}
        >
          <select
            className="select"
            aria-label="按状态筛选"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s ? ({"DRAFT":"草稿","CONFIRMED":"已确认","POSTED":"已入账","REVERSED":"已冲正","CANCELLED":"已取消"} as Record<string, string>)[s] : "全部状态"}
              </option>
            ))}
          </select>
        </div>

        {txns === null ? (
          <div style={{ padding: "var(--space-4)", display: "grid", gap: "var(--space-3)" }}>
            <Skeleton />
            <Skeleton />
          </div>
        ) : txns.length === 0 ? (
          <EmptyState
            icon={<ArrowLeftRight size={40} aria-hidden />}
            title="还没有交易"
            description="从一笔入金开始记账。"
            action={
              <button className="btn btn--primary" onClick={() => setFormOpen(true)}>
                新建交易
              </button>
            }
          />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>日期</th>
                <th>类型</th>
                <th>账户</th>
                <th className="cell--num">金额</th>
                <th>状态</th>
                <th>备注</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {txns.map((t) => (
                <tr key={t.id}>
                  <td className="num">{t.business_date}</td>
                  <td>{TXN_TYPE_LABELS[t.transaction_type] ?? t.transaction_type}</td>
                  <td>
                    {accountName(t.account_id)}
                    {t.counter_account_id && ` → ${accountName(t.counter_account_id)}`}
                  </td>
                  <td className="cell--num num">{fmtAmount(t.total_amount)}</td>
                  <td>
                    <StatusBadge status={t.status} />
                  </td>
                  <td style={{ color: "var(--color-muted-foreground)" }}>{t.memo ?? "—"}</td>
                  <td className="cell--actions">{actions(t)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 新建交易 */}
      <Dialog open={formOpen} title="新建交易" onClose={() => setFormOpen(false)}>
        <form onSubmit={submit}>
          <div className="field">
            <label className="field__label" htmlFor="txn-type" aria-required="true">
              类型
            </label>
            <select
              id="txn-type"
              className="select"
              value={form.transaction_type}
              onChange={(e) => setForm({ ...form, transaction_type: e.target.value })}
            >
              {FORM_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="txn-account" aria-required="true">
              {form.transaction_type === "ACCOUNT_TRANSFER" ? "转出账户" : "账户"}
            </label>
            <select
              id="txn-account"
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
          {form.transaction_type === "ACCOUNT_TRANSFER" && (
            <div className="field">
              <label className="field__label" htmlFor="txn-counter" aria-required="true">
                转入账户
              </label>
              <select
                id="txn-counter"
                className="select"
                required
                value={form.counter_account_id}
                onChange={(e) => setForm({ ...form, counter_account_id: e.target.value })}
              >
                <option value="">选择转入账户</option>
                {accounts
                  .filter((a) => a.id !== form.account_id)
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
              </select>
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
            <div className="field">
              <label className="field__label" htmlFor="txn-date" aria-required="true">
                日期
              </label>
              <input
                id="txn-date"
                className="input num"
                type="date"
                required
                value={form.business_date}
                onChange={(e) => setForm({ ...form, business_date: e.target.value })}
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="txn-amount" aria-required="true">
                金额
              </label>
              <input
                id="txn-amount"
                className="input num"
                type="number"
                step="0.000001"
                min="0.000001"
                required
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
                placeholder="0.00"
              />
            </div>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="txn-memo">
              备注
            </label>
            <input
              id="txn-memo"
              className="input"
              value={form.memo}
              onChange={(e) => setForm({ ...form, memo: e.target.value })}
            />
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
              disabled={busy || !form.account_id || !form.amount}
            >
              保存草稿
            </button>
          </div>
        </form>
      </Dialog>

      {/* 冲正确认 */}
      <Dialog open={reversing !== null} title="冲正交易" onClose={() => setReversing(null)}>
        <p>
          确定冲正这笔 {reversing ? TXN_TYPE_LABELS[reversing.transaction_type] : ""}{" "}
          {reversing && `¥${fmtAmount(reversing.total_amount)}`}？
        </p>
        <p style={{ color: "var(--color-muted-foreground)", marginTop: "var(--space-2)" }}>
          将生成一条反向分录并计入账本，原交易标记为已冲正，记录保留。
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

      {/* 交易详情（含分录） */}
      <Dialog open={detail !== null} title="交易详情" onClose={() => setDetail(null)}>
        {detail && (
          <>
            <table className="table">
              <tbody>
                <tr>
                  <td style={{ color: "var(--color-muted-foreground)" }}>类型</td>
                  <td>{TXN_TYPE_LABELS[detail.transaction_type]}</td>
                </tr>
                <tr>
                  <td style={{ color: "var(--color-muted-foreground)" }}>账户</td>
                  <td>
                    {accountName(detail.account_id)}
                    {detail.counter_account_id && ` → ${accountName(detail.counter_account_id)}`}
                  </td>
                </tr>
                <tr>
                  <td style={{ color: "var(--color-muted-foreground)" }}>状态</td>
                  <td>
                    <StatusBadge status={detail.status} />
                  </td>
                </tr>
                <tr>
                  <td style={{ color: "var(--color-muted-foreground)" }}>金额</td>
                  <td className="num">{fmtAmount(detail.total_amount)}</td>
                </tr>
              </tbody>
            </table>
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
          </>
        )}
      </Dialog>
    </div>
  )
}
