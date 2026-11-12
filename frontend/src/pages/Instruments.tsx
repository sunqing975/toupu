import { useEffect, useState } from "react"
import { Plus, Tags } from "lucide-react"
import { instrumentsApi } from "../api/instruments"
import type { Instrument } from "../api/types"
import { Dialog } from "../components/Dialog"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"
import { useToast } from "../components/Toast"

const TYPE_LABELS: Record<string, string> = {
  FUND: "基金",
  ETF: "ETF",
  STOCK: "股票",
}

type FormState = {
  instrument_type: string
  market: string
  exchange: string
  code: string
  name: string
  currency: string
}

const EMPTY_FORM: FormState = {
  instrument_type: "STOCK",
  market: "CN",
  exchange: "",
  code: "",
  name: "",
  currency: "CNY",
}

export function Instruments() {
  const toast = useToast()
  const [instruments, setInstruments] = useState<Instrument[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filterType, setFilterType] = useState<string>("")
  const [formOpen, setFormOpen] = useState(false)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [busy, setBusy] = useState(false)

  const load = (type = filterType) => {
    instrumentsApi
      .list(type || undefined)
      .then(setInstruments)
      .catch((e: unknown) => setError(String((e as Error).message)))
  }

  useEffect(() => {
    load(filterType)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterType])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      await instrumentsApi.create({
        instrument_type: form.instrument_type,
        market: form.market,
        exchange: form.exchange || null,
        code: form.code,
        name: form.name,
        currency: form.currency,
      })
      toast("success", "品种已创建")
      setFormOpen(false)
      setForm(EMPTY_FORM)
      load()
    } catch (err) {
      toast("error", (err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <p className="page__sub">你投资的对象：基金、ETF 与股票，市场 + 代码唯一</p>
        </div>
        <button className="btn btn--primary" onClick={() => setFormOpen(true)}>
          <Plus size={16} aria-hidden />
          新建品种
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
            aria-label="按类型筛选"
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
          >
            <option value="">全部类型</option>
            {Object.entries(TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>

        {instruments === null ? (
          <div style={{ padding: "var(--space-4)", display: "grid", gap: "var(--space-3)" }}>
            <Skeleton />
            <Skeleton />
          </div>
        ) : instruments.length === 0 ? (
          <EmptyState
            icon={<Tags size={40} aria-hidden />}
            title={filterType ? "该类型下暂无品种" : "还没有投资品种"}
            description="品种是你投资的对象（股票/基金/ETF），市场 + 代码全局唯一。"
            action={
              !filterType && (
                <button className="btn btn--primary" onClick={() => setFormOpen(true)}>
                  新建品种
                </button>
              )
            }
          />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>代码</th>
                <th>名称</th>
                <th>类型</th>
                <th>市场</th>
                <th>交易所</th>
                <th className="cell--num">币种</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {instruments.map((i) => (
                <tr key={i.id}>
                  <td className="num">{i.code}</td>
                  <td>{i.name}</td>
                  <td>{TYPE_LABELS[i.instrument_type] ?? i.instrument_type}</td>
                  <td>{i.market}</td>
                  <td>{i.exchange ?? "—"}</td>
                  <td className="cell--num">{i.currency}</td>
                  <td>
                    <span className={`badge ${i.status === "ACTIVE" ? "badge--green" : "badge--gray"}`}>
                      {i.status === "ACTIVE" ? "正常" : "已退市"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Dialog open={formOpen} title="新建投资品种" onClose={() => setFormOpen(false)}>
        <form onSubmit={submit}>
          <div className="field">
            <label className="field__label" htmlFor="ins-type" aria-required="true">
              类型
            </label>
            <select
              id="ins-type"
              className="select"
              value={form.instrument_type}
              onChange={(e) => setForm({ ...form, instrument_type: e.target.value })}
            >
              {Object.entries(TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
            <div className="field">
              <label className="field__label" htmlFor="ins-market" aria-required="true">
                市场
              </label>
              <input
                id="ins-market"
                className="input"
                required
                value={form.market}
                onChange={(e) => setForm({ ...form, market: e.target.value })}
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="ins-exchange">
                交易所
              </label>
              <input
                id="ins-exchange"
                className="input"
                placeholder="基金可留空"
                value={form.exchange}
                onChange={(e) => setForm({ ...form, exchange: e.target.value })}
              />
            </div>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="ins-code" aria-required="true">
              代码
            </label>
            <input
              id="ins-code"
              className="input"
              required
              value={form.code}
              onChange={(e) => setForm({ ...form, code: e.target.value })}
              placeholder="如 600519 / 110038"
            />
          </div>
          <div className="field">
            <label className="field__label" htmlFor="ins-name" aria-required="true">
              名称
            </label>
            <input
              id="ins-name"
              className="input"
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          <div className="dialog__foot" style={{ margin: "0 calc(-1 * var(--space-5))", marginBottom: "calc(-1 * var(--space-5))" }}>
            <button type="button" className="btn btn--secondary" onClick={() => setFormOpen(false)}>
              取消
            </button>
            <button
              type="submit"
              className="btn btn--primary"
              disabled={busy || !form.code.trim() || !form.name.trim()}
            >
              创建
            </button>
          </div>
        </form>
      </Dialog>
    </div>
  )
}
