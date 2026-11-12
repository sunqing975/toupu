import { useEffect, useState } from "react"
import { Plus, Wallet } from "lucide-react"
import { accountsApi } from "../api/accounts"
import type { InvestmentAccount } from "../api/types"
import { Dialog } from "../components/Dialog"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"
import { StatusBadge } from "../components/StatusBadge"
import { useToast } from "../components/Toast"

const ACCOUNT_TYPES: Record<string, string> = {
  BROKER: "券商",
  FUND_PLATFORM: "基金平台",
}

type FormState = { name: string; account_type: string; currency: string; notes: string }

const EMPTY_FORM: FormState = { name: "", account_type: "BROKER", currency: "CNY", notes: "" }

export function Accounts() {
  const toast = useToast()
  const [accounts, setAccounts] = useState<InvestmentAccount[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<InvestmentAccount | null>(null)
  const [deleting, setDeleting] = useState<InvestmentAccount | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [busy, setBusy] = useState(false)

  const load = () => {
    accountsApi
      .list()
      .then(setAccounts)
      .catch((e: unknown) => setError(String((e as Error).message)))
  }

  useEffect(load, [])

  const openCreate = () => {
    setForm(EMPTY_FORM)
    setEditing(null)
    setFormOpen(true)
  }

  const openEdit = (account: InvestmentAccount) => {
    setForm({
      name: account.name,
      account_type: account.account_type,
      currency: account.currency,
      notes: account.notes ?? "",
    })
    setEditing(account)
    setFormOpen(true)
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      if (editing) {
        await accountsApi.update(editing.id, {
          name: form.name,
          status: editing.status,
          notes: form.notes || null,
        })
        toast("success", "账户已保存")
      } else {
        await accountsApi.create({
          name: form.name,
          account_type: form.account_type,
          currency: form.currency,
          notes: form.notes || null,
        })
        toast("success", "账户已创建")
      }
      setFormOpen(false)
      load()
    } catch (err) {
      toast("error", (err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!deleting) return
    setBusy(true)
    try {
      await accountsApi.remove(deleting.id)
      toast("success", "账户已删除")
      setDeleting(null)
      load()
    } catch (err) {
      // 被账本引用的账户不能删，提示改用关闭
      toast("error", `${(err as Error).message}。可将账户状态改为"已关闭"。`)
      setDeleting(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <p className="page__sub">券商、基金平台、银行与现金账户</p>
        </div>
        <button className="btn btn--primary" onClick={openCreate}>
          <Plus size={16} aria-hidden />
          新建账户
        </button>
      </div>

      {error && <div className="banner banner--error">{error}</div>}

      <div className="card table-scroll">
        {accounts === null ? (
          <div style={{ padding: "var(--space-4)", display: "grid", gap: "var(--space-3)" }}>
            <Skeleton />
            <Skeleton />
          </div>
        ) : accounts.length === 0 ? (
          <EmptyState
            icon={<Wallet size={40} aria-hidden />}
            title="还没有账户"
            description="创建第一个账户，开始记账。"
            action={
              <button className="btn btn--primary" onClick={openCreate}>
                新建账户
              </button>
            }
          />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>名称</th>
                <th>类型</th>
                <th>币种</th>
                <th>状态</th>
                <th>备注</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.id}>
                  <td>{a.name}</td>
                  <td>{ACCOUNT_TYPES[a.account_type] ?? a.account_type}</td>
                  <td className="num">{a.currency}</td>
                  <td>
                    <StatusBadge status={a.status} />
                  </td>
                  <td style={{ color: "var(--color-muted-foreground)" }}>{a.notes ?? "—"}</td>
                  <td className="cell--actions">
                    <button className="btn btn--secondary" onClick={() => openEdit(a)}>
                      编辑
                    </button>{" "}
                    <button className="btn btn--destructive" onClick={() => setDeleting(a)}>
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Dialog
        open={formOpen}
        title={editing ? "编辑账户" : "新建账户"}
        onClose={() => setFormOpen(false)}
      >
        <form onSubmit={submit}>
          <div className="field">
            <label className="field__label" htmlFor="acc-name" aria-required="true">
              名称
            </label>
            <input
              id="acc-name"
              className="input"
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="如：华泰证券主账户"
            />
          </div>
          <div className="field">
            <label className="field__label" htmlFor="acc-type" aria-required="true">
              类型
            </label>
            <select
              id="acc-type"
              className="select"
              value={form.account_type}
              disabled={!!editing}
              onChange={(e) => setForm({ ...form, account_type: e.target.value })}
            >
              {Object.entries(ACCOUNT_TYPES).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="acc-currency">
              币种
            </label>
            <input
              id="acc-currency"
              className="input"
              value={form.currency}
              disabled={!!editing}
              onChange={(e) => setForm({ ...form, currency: e.target.value })}
            />
          </div>
          <div className="field">
            <label className="field__label" htmlFor="acc-notes">
              备注
            </label>
            <textarea
              id="acc-notes"
              className="textarea"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
            />
          </div>
          {editing && (
            <div className="field">
              <label className="field__label" htmlFor="acc-status">
                状态
              </label>
              <select
                id="acc-status"
                className="select"
                defaultValue={editing.status}
                onChange={(e) => setEditing({ ...editing, status: e.target.value })}
              >
                <option value="ACTIVE">正常</option>
                <option value="FROZEN">冻结</option>
                <option value="CLOSED">已关闭</option>
              </select>
            </div>
          )}
          <div className="dialog__foot" style={{ margin: "0 calc(-1 * var(--space-5))", marginBottom: "calc(-1 * var(--space-5))" }}>
            <button type="button" className="btn btn--secondary" onClick={() => setFormOpen(false)}>
              取消
            </button>
            <button type="submit" className="btn btn--primary" disabled={busy || !form.name.trim()}>
              {editing ? "保存" : "创建"}
            </button>
          </div>
        </form>
      </Dialog>

      <Dialog
        open={deleting !== null}
        title="删除账户"
        onClose={() => setDeleting(null)}
      >
        <p>确定删除「{deleting?.name}」？删除后该账户的记录关联将失效，此操作不可恢复。</p>
        <div className="dialog__foot" style={{ margin: "var(--space-4) calc(-1 * var(--space-5)) calc(-1 * var(--space-5))" }}>
          <button className="btn btn--secondary" onClick={() => setDeleting(null)}>
            取消
          </button>
          <button className="btn btn--destructive" disabled={busy} onClick={remove}>
            删除
          </button>
        </div>
      </Dialog>
    </div>
  )
}
