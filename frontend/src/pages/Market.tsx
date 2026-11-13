import { useEffect, useState } from "react"
import {
  Activity,
  BarChart3,
  Camera,
  Database,
  Info,
  Plus,
  RefreshCw,
  TrendingDown,
  TrendingUp,
} from "lucide-react"
import {
  DATA_QUALITY_LABELS,
  DATA_TYPE_LABELS,
  marketApi,
  METRIC_STATUS_LABELS,
  QUOTE_STATUS_LABELS,
  QUOTE_STATUS_TONE,
  type MetricOut,
  type NavOut,
  type QuoteOut,
  type ReturnsOut,
  type RebuildOut,
  type SummaryOut,
  type ValuationOut,
} from "../api/market"
import { instrumentsApi } from "../api/instruments"
import { fmtAmount } from "../api/transactions"
import type { Instrument } from "../api/types"
import { Dialog } from "../components/Dialog"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"
import { useToast } from "../components/Toast"

const INSTRUMENT_TYPE_LABELS: Record<string, string> = {
  STOCK: "股票",
  ETF: "ETF",
  FUND: "基金",
}

type Tab = "valuation" | "entry" | "snapshots"

const TABS: { key: Tab; label: string }[] = [
  { key: "valuation", label: "估值明细" },
  { key: "entry", label: "行情录入" },
  { key: "snapshots", label: "组合快照" },
]

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function QuoteBadge({ status }: { status: string }) {
  const tone = QUOTE_STATUS_TONE[status] ?? "gray"
  return <span className={`badge badge--${tone}`}>{QUOTE_STATUS_LABELS[status] ?? status}</span>
}

function MetricCard({
  label,
  metric,
  suffix = "%",
  icon,
}: {
  label: string
  metric: MetricOut
  suffix?: string
  icon: React.ReactNode
}) {
  const ok = metric.status === "OK" && metric.value !== null
  const pct = ok ? (Number(metric.value) * 100).toLocaleString("zh-CN", { maximumFractionDigits: 4 }) : null
  return (
    <div className="card">
      <div className="card__title" style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {icon}
        {label}
      </div>
      {ok ? (
        <div className="card__value num" style={{ color: Number(metric.value) < 0 ? "var(--color-destructive)" : undefined }}>
          {pct}{suffix}
        </div>
      ) : (
        <div style={{ fontSize: 15, fontWeight: 600, color: "var(--color-muted-foreground)" }}>
          {METRIC_STATUS_LABELS[metric.status] ?? metric.status}
        </div>
      )}
      <div className="card__hint">
        {metric.reason ?? (ok ? `${label}（按 §17 口径）` : "覆盖不足或缺少期初资本时不会给出看似合理的数字")}
        {metric.missing.length > 0 && ` · 缺失日期：${metric.missing.join("、")}`}
        {ok && metric.peak_date && metric.trough_date && ` · 峰 ${metric.peak_date} → 谷 ${metric.trough_date}`}
      </div>
    </div>
  )
}

function StatCard({ title, value, hint }: { title: string; value: string; hint?: string }) {
  return (
    <div className="card">
      <div className="card__title">{title}</div>
      <div className="card__value num">{value}</div>
      {hint && <div className="card__hint">{hint}</div>}
    </div>
  )
}

export function Market() {
  const toast = useToast()
  const [asOf, setAsOf] = useState(today())
  const [staleDays, setStaleDays] = useState(7)
  const [tab, setTab] = useState<Tab>("valuation")
  const [busy, setBusy] = useState(false)

  const [valuation, setValuation] = useState<ValuationOut | null>(null)
  const [summary, setSummary] = useState<SummaryOut | null>(null)
  const [returns, setReturns] = useState<ReturnsOut | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [instruments, setInstruments] = useState<Instrument[]>([])
  const [quotes, setQuotes] = useState<QuoteOut[]>([])
  const [navs, setNavs] = useState<NavOut[]>([])
  const [entryOpen, setEntryOpen] = useState(false)
  const [entryKind, setEntryKind] = useState<"QUOTE" | "NAV">("QUOTE")
  const [entryInstrument, setEntryInstrument] = useState("")
  const [entryDate, setEntryDate] = useState(today())
  const [entryPrice, setEntryPrice] = useState("")
  const [entryNav, setEntryNav] = useState("")
  const [entryAccNav, setEntryAccNav] = useState("")
  const [entryDataType, setEntryDataType] = useState("OFFICIAL")
  const [entryProviderCode, setEntryProviderCode] = useState("")

  const [snapshots, setSnapshots] = useState<RebuildOut["snapshot"][] | null>(null)
  const [rebuildDate, setRebuildDate] = useState(today())
  const [rebuildOpen, setRebuildOpen] = useState(false)
  const [snapshotDetail, setSnapshotDetail] = useState<string | null>(null)
  const [snapshotRows, setSnapshotRows] = useState<RebuildOut["positions"]>([])

  // 汇总三件套随日期/过期阈值变化重算
  const loadDerived = () => {
    setLoadError(null)
    Promise.all([
      marketApi.valuation(asOf, staleDays),
      marketApi.summary(asOf, staleDays),
      marketApi.returns(asOf, staleDays),
    ])
      .then(([v, s, r]) => {
        setValuation(v)
        setSummary(s)
        setReturns(r)
      })
      .catch((e: unknown) => setLoadError((e as Error).message))
  }

  useEffect(() => {
    loadDerived()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asOf, staleDays])

  useEffect(() => {
    instrumentsApi.list().then(setInstruments).catch(() => setInstruments([]))
  }, [])

  const loadEntry = () => {
    marketApi.quotes().then(setQuotes).catch(() => setQuotes([]))
    marketApi.navs().then(setNavs).catch(() => setNavs([]))
  }
  useEffect(() => {
    loadEntry()
  }, [])

  useEffect(() => {
    marketApi.snapshots().then(setSnapshots).catch(() => setSnapshots([]))
  }, [])

  const openEntry = (kind: "QUOTE" | "NAV") => {
    setEntryKind(kind)
    setEntryInstrument("")
    setEntryDate(asOf)
    setEntryPrice("")
    setEntryNav("")
    setEntryAccNav("")
    setEntryDataType("OFFICIAL")
    setEntryProviderCode("")
    setEntryOpen(true)
  }

  const submitEntry = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!entryInstrument) return
    setBusy(true)
    try {
      if (entryKind === "QUOTE") {
        await marketApi.createQuote({
          instrument_id: entryInstrument,
          quote_date: entryDate,
          price: entryPrice,
          data_type: entryDataType === "ESTIMATED" ? "ESTIMATED" : "OFFICIAL",
          provider_code: entryProviderCode || null,
        })
        toast("success", "行情已录入（估值输入，不改动账本）")
      } else {
        await marketApi.createNav({
          instrument_id: entryInstrument,
          nav_date: entryDate,
          nav: entryNav,
          data_type: entryDataType === "ESTIMATED" ? "ESTIMATED" : "OFFICIAL",
          accumulated_nav: entryAccNav || null,
          provider_code: entryProviderCode || null,
        })
        toast("success", "基金净值已录入")
      }
      setEntryOpen(false)
      loadEntry()
      loadDerived()
    } catch (err) {
      toast("error", (err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const doRebuild = async () => {
    setBusy(true)
    try {
      const result = await marketApi.rebuild(rebuildDate, staleDays)
      toast("success", `快照已重建：${result.positions.length} 条持仓（同日重算幂等）`)
      setRebuildOpen(false)
      setSnapshots(await marketApi.snapshots())
      loadDerived()
    } catch (err) {
      toast("error", (err as Error).message)
      setRebuildOpen(false)
    } finally {
      setBusy(false)
    }
  }

  const showSnapshot = async (date: string) => {
    setSnapshotDetail(date)
    setSnapshotRows([])
    try {
      setSnapshotRows(await marketApi.snapshotPositions(date))
    } catch (err) {
      toast("error", (err as Error).message)
    }
  }

  const instrumentName = (id: string) =>
    instruments.find((i) => i.id === id)?.name ?? id.slice(0, 8)
  const instrumentCode = (id: string) =>
    instruments.find((i) => i.id === id)?.code ?? ""

  const fundInstruments = instruments.filter((i) => i.instrument_type === "FUND")
  const nonFundInstruments = instruments.filter((i) => i.instrument_type !== "FUND")
  const entryOptions = entryKind === "NAV" ? fundInstruments : nonFundInstruments

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <p className="page__sub">
            行情是估值输入，不是交易事实；缺失或过期报价不会静默当成实时，收益指标数据不足时如实返回状态
          </p>
        </div>
        <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", flexWrap: "wrap" }}>
          <input
            className="input"
            type="date"
            aria-label="估值日期"
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
            style={{ width: 150 }}
          />
          <select
            className="select"
            aria-label="过期阈值"
            value={staleDays}
            onChange={(e) => setStaleDays(Number(e.target.value))}
            style={{ width: 120 }}
          >
            <option value={7}>7 天过期</option>
            <option value={3}>3 天过期</option>
            <option value={30}>30 天过期</option>
          </select>
          <button className="btn btn--secondary" onClick={loadDerived} aria-label="刷新">
            <RefreshCw size={15} aria-hidden />
          </button>
        </div>
      </div>

      {loadError && <div className="banner banner--error">{loadError}</div>}

      {/* 顶部派生汇总 */}
      {summary === null ? (
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          <Skeleton />
          <Skeleton />
        </div>
      ) : (
        <div className="stat-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)", marginBottom: "var(--space-4)" }}>
          <StatCard title="现金合计" value={fmtAmount(summary.cash_total)} hint="CASH 科目借贷净额" />
          <StatCard title="持仓市值" value={fmtAmount(summary.market_value)} hint="仅已估值持仓" />
          <StatCard title="总资产" value={fmtAmount(summary.total_assets)} hint="现金 + 持仓市值" />
          <StatCard title="账面成本" value={fmtAmount(summary.book_cost_total)} hint="SECURITY 科目双口径校验" />
        </div>
      )}
      {summary && (
        <div className="stat-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)", marginBottom: "var(--space-5)" }}>
          <StatCard title="已实现盈亏" value={fmtAmount(summary.realized_total)} />
          <StatCard title="未实现盈亏" value={fmtAmount(summary.unrealized_total)} hint="市值 − 账面成本" />
          <StatCard title="分红收入" value={fmtAmount(summary.dividend_income)} />
          <StatCard
            title="报价覆盖"
            value={`${(Number(summary.coverage) * 100).toFixed(2)}%`}
            hint={`${summary.valued_positions}/${summary.total_positions} 个持仓已估值 · ${DATA_QUALITY_LABELS[summary.data_quality] ?? summary.data_quality}`}
          />
        </div>
      )}

      {/* 收益指标 */}
      <div style={{ marginBottom: "var(--space-5)" }}>
        <h2 className="page__title" style={{ fontSize: 15, marginBottom: "var(--space-3)" }}>
          收益指标（XIRR / TWR / 最大回撤）
        </h2>
        {returns === null ? (
          <Skeleton />
        ) : (
          <div className="stat-grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
            <MetricCard label="XIRR（年化内部收益率）" metric={returns.xirr} icon={<TrendingUp size={14} aria-hidden />} />
            <MetricCard label="TWR（时间加权收益率）" metric={returns.twr} icon={<BarChart3 size={14} aria-hidden />} />
            <MetricCard label="最大回撤" metric={returns.max_drawdown} icon={<TrendingDown size={14} aria-hidden />} />
          </div>
        )}
      </div>

      {/* Tab 切换 */}
      <div style={{ display: "flex", gap: "var(--space-2)", borderBottom: "1px solid var(--color-border)", marginBottom: "var(--space-4)" }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`btn ${tab === t.key ? "btn--primary" : "btn--ghost"}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 估值明细 */}
      {tab === "valuation" && (
        <div className="card table-scroll">
          {valuation === null ? (
            <div style={{ padding: "var(--space-4)", display: "grid", gap: "var(--space-3)" }}>
              <Skeleton />
              <Skeleton />
            </div>
          ) : valuation.positions.length === 0 ? (
            <EmptyState
              icon={<Activity size={40} aria-hidden />}
              title="暂无持仓估值"
              description="完成一笔买入并入账后，持仓会在这里按报价状态显示市值与浮盈。"
            />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>品种</th>
                  <th>报价状态</th>
                  <th className="cell--num">数量</th>
                  <th className="cell--num">账面成本</th>
                  <th className="cell--num">报价</th>
                  <th className="cell--num">市值</th>
                  <th className="cell--num">未实现盈亏</th>
                </tr>
              </thead>
              <tbody>
                {valuation.positions.map((r) => (
                  <tr key={r.account_id + r.instrument_id}>
                    <td>
                      {r.instrument_name}
                      <div style={{ color: "var(--color-muted-foreground)", fontSize: 12 }}>
                        {r.instrument_code} · {INSTRUMENT_TYPE_LABELS[r.instrument_type] ?? r.instrument_type}
                      </div>
                    </td>
                    <td>
                      <QuoteBadge status={r.quote.status} />
                      {r.quote.quote_date && (
                        <div style={{ color: "var(--color-muted-foreground)", fontSize: 11, marginTop: 2 }}>
                          {r.quote.quote_date}
                        </div>
                      )}
                    </td>
                    <td className="cell--num num">{fmtAmount(r.quantity)}</td>
                    <td className="cell--num num">{fmtAmount(r.book_cost)}</td>
                    <td className="cell--num num">{fmtAmount(r.quote.price)}</td>
                    <td className="cell--num num">{fmtAmount(r.market_value)}</td>
                    <td className="cell--num num">{fmtAmount(r.unrealized)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={5} style={{ fontWeight: 600 }}>
                    合计（仅已估值持仓计入）
                  </td>
                  <td className="cell--num num" style={{ fontWeight: 600 }}>
                    {fmtAmount(valuation.market_value)}
                  </td>
                  <td className="cell--num num" style={{ fontWeight: 600 }}>
                    {fmtAmount(valuation.unrealized_total)}
                  </td>
                </tr>
              </tfoot>
            </table>
          )}
        </div>
      )}

      {/* 行情录入 */}
      {tab === "entry" && (
        <>
          <div className="page__head" style={{ marginBottom: "var(--space-3)" }}>
            <p className="page__sub">
              第一版只提供手动录入；正式行情仅接受未复权，盘中估值（ESTIMATED）不用于核算。
            </p>
            <div style={{ display: "flex", gap: "var(--space-2)" }}>
              <button className="btn btn--secondary" onClick={() => openEntry("NAV")}>
                <Plus size={15} aria-hidden /> 录入净值
              </button>
              <button className="btn btn--primary" onClick={() => openEntry("QUOTE")}>
                <Plus size={15} aria-hidden /> 录入行情
              </button>
            </div>
          </div>
          <div className="grid-2">
            <div className="card table-scroll">
              <div className="card__title">股票 / ETF 日行情（{quotes.length}）</div>
              {quotes.length === 0 ? (
                <EmptyState icon={<Database size={32} aria-hidden />} title="还没有行情" description="点击「录入行情」添加一条正式报价。" />
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>品种</th>
                      <th>日期</th>
                      <th>类型</th>
                      <th className="cell--num">价格</th>
                      <th>来源</th>
                    </tr>
                  </thead>
                  <tbody>
                    {quotes.map((q) => (
                      <tr key={q.id}>
                        <td>{instrumentName(q.instrument_id)}<div style={{ fontSize: 11, color: "var(--color-muted-foreground)" }}>{instrumentCode(q.instrument_id)}</div></td>
                        <td className="num" style={{ fontSize: 12 }}>{q.quote_date}</td>
                        <td><span className={`badge badge--${q.data_type === "OFFICIAL" ? "green" : "blue"}`}>{DATA_TYPE_LABELS[q.data_type] ?? q.data_type}</span></td>
                        <td className="cell--num num">{fmtAmount(q.price)}</td>
                        <td style={{ fontSize: 12 }}>{q.provider}{q.provider_code ? ` · ${q.provider_code}` : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div className="card table-scroll">
              <div className="card__title">基金净值（{navs.length}）</div>
              {navs.length === 0 ? (
                <EmptyState icon={<Database size={32} aria-hidden />} title="还没有净值" description="点击「录入净值」添加一条 FUND 品种净值。" />
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>品种</th>
                      <th>日期</th>
                      <th className="cell--num">单位净值</th>
                      <th className="cell--num">累计</th>
                    </tr>
                  </thead>
                  <tbody>
                    {navs.map((n) => (
                      <tr key={n.id}>
                        <td>{instrumentName(n.instrument_id)}</td>
                        <td className="num" style={{ fontSize: 12 }}>{n.nav_date}</td>
                        <td className="cell--num num">{fmtAmount(n.nav)}</td>
                        <td className="cell--num num">{fmtAmount(n.accumulated_nav)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </>
      )}

      {/* 快照 */}
      {tab === "snapshots" && (
        <>
          <div className="page__head" style={{ marginBottom: "var(--space-3)" }}>
            <p className="page__sub">快照是可删除重建的派生结果；同日重复重建先删后建，不产生重复行。</p>
            <button className="btn btn--primary" onClick={() => { setRebuildDate(asOf); setRebuildOpen(true) }}>
              <Camera size={15} aria-hidden /> 重建快照
            </button>
          </div>
          <div className="card table-scroll">
            {snapshots === null ? (
              <Skeleton />
            ) : snapshots.length === 0 ? (
              <EmptyState icon={<Camera size={40} aria-hidden />} title="还没有快照" description="重建快照后可查看组合净值序列，用于 TWR 与最大回撤。" />
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>快照日期</th>
                    <th className="cell--num">总资产</th>
                    <th className="cell--num">市值</th>
                    <th className="cell--num">覆盖率</th>
                    <th>数据质量</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {snapshots.map((s) => (
                    <tr key={s.id}>
                      <td className="num">{s.snapshot_date}</td>
                      <td className="cell--num num">{fmtAmount(s.total_assets)}</td>
                      <td className="cell--num num">{fmtAmount(s.market_value)}</td>
                      <td className="cell--num num">{(Number(s.coverage) * 100).toFixed(2)}%</td>
                      <td>{DATA_QUALITY_LABELS[s.data_quality] ?? s.data_quality}</td>
                      <td className="cell--actions">
                        <button className="btn btn--secondary" onClick={() => showSnapshot(s.snapshot_date)}>
                          查看明细
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {/* 录入行情 / 净值 Dialog */}
      <Dialog
        open={entryOpen}
        title={entryKind === "QUOTE" ? "录入股票 / ETF 行情" : "录入基金净值"}
        onClose={() => setEntryOpen(false)}
      >
        <form onSubmit={submitEntry}>
          <div className="banner" style={{ display: "block", marginBottom: "var(--space-3)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
              <Info size={14} aria-hidden />
              <strong>仅作为估值输入</strong>
            </div>
            <p style={{ margin: 0, lineHeight: 1.7, fontSize: 13 }}>
              行情不覆盖账本成交价；正式数据仅接受未复权报价，盘中估值（ESTIMATED）只展示、不用于核算。
            </p>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="entry-instrument" aria-required="true">
              投资品种{entryKind === "NAV" ? "（仅 FUND）" : "（股票 / ETF）"}
            </label>
            <select
              id="entry-instrument"
              className="select"
              required
              value={entryInstrument}
              onChange={(e) => setEntryInstrument(e.target.value)}
            >
              <option value="">请选择</option>
              {entryOptions.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name}（{i.code}）
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="entry-date" aria-required="true">
              日期
            </label>
            <input id="entry-date" className="input" type="date" required value={entryDate} onChange={(e) => setEntryDate(e.target.value)} />
          </div>
          <div className="field">
            <label className="field__label" htmlFor="entry-price" aria-required="true">
              {entryKind === "QUOTE" ? "价格" : "单位净值"}
            </label>
            <input
              id="entry-price"
              className="input"
              type="number"
              step="0.000001"
              min="0.000001"
              required
              value={entryKind === "QUOTE" ? entryPrice : entryNav}
              onChange={(e) => (entryKind === "QUOTE" ? setEntryPrice(e.target.value) : setEntryNav(e.target.value))}
              placeholder="例如 12.500000"
            />
          </div>
          {entryKind === "NAV" && (
            <div className="field">
              <label className="field__label" htmlFor="entry-accnav">累计净值（选填）</label>
              <input id="entry-accnav" className="input" type="number" step="0.000001" min="0" value={entryAccNav} onChange={(e) => setEntryAccNav(e.target.value)} placeholder="例如 2.000000" />
            </div>
          )}
          <div className="field">
            <label className="field__label" htmlFor="entry-datatype">数据类型</label>
            <select id="entry-datatype" className="select" value={entryDataType} onChange={(e) => setEntryDataType(e.target.value)}>
              <option value="OFFICIAL">正式（用于核算）</option>
              <option value="ESTIMATED">盘中估值（不用于核算）</option>
            </select>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="entry-providercode">来源代码（选填）</label>
            <input id="entry-providercode" className="input" value={entryProviderCode} onChange={(e) => setEntryProviderCode(e.target.value)} placeholder="例如 600519 / 000001" />
          </div>
          <div className="dialog__foot" style={{ margin: "0 calc(-1 * var(--space-5))", marginBottom: "calc(-1 * var(--space-5))" }}>
            <button type="button" className="btn btn--secondary" onClick={() => setEntryOpen(false)}>取消</button>
            <button type="submit" className="btn btn--primary" disabled={busy || !entryInstrument}>
              {busy ? "保存中…" : "保存"}
            </button>
          </div>
        </form>
      </Dialog>

      {/* 重建快照 Dialog */}
      <Dialog open={rebuildOpen} title="重建组合快照" onClose={() => setRebuildOpen(false)}>
        <p>确定按当前账本余额、持仓批次与有效报价重建快照？</p>
        <p style={{ color: "var(--color-muted-foreground)", marginTop: "var(--space-2)", lineHeight: 1.7 }}>
          快照是可删除重建的派生结果，不会改动任何交易或持仓批次；同日重复重建先删后建（幂等）。
          第一版按当前实时余额生成，<code>snapshot_date</code> 是保存标签，不回放任意历史日账面余额。
        </p>
        <div className="field" style={{ marginTop: "var(--space-3)" }}>
          <label className="field__label" htmlFor="rebuild-date">快照日期</label>
          <input id="rebuild-date" className="input" type="date" value={rebuildDate} onChange={(e) => setRebuildDate(e.target.value)} />
        </div>
        <div className="dialog__foot" style={{ margin: "var(--space-4) calc(-1 * var(--space-5)) calc(-1 * var(--space-5))" }}>
          <button className="btn btn--secondary" onClick={() => setRebuildOpen(false)}>返回</button>
          <button className="btn btn--primary" disabled={busy || !rebuildDate} onClick={doRebuild}>
            <Camera size={14} aria-hidden /> 重建
          </button>
        </div>
      </Dialog>

      {/* 快照明细 Dialog */}
      <Dialog open={snapshotDetail !== null} title={`快照明细 · ${snapshotDetail ?? ""}`} onClose={() => setSnapshotDetail(null)}>
        {snapshotRows.length === 0 ? (
          <p style={{ color: "var(--color-muted-foreground)" }}>加载中或该日无持仓明细…</p>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>品种</th>
                  <th>报价状态</th>
                  <th className="cell--num">数量</th>
                  <th className="cell--num">市值</th>
                  <th className="cell--num">未实现盈亏</th>
                </tr>
              </thead>
              <tbody>
                {snapshotRows.map((r) => (
                  <tr key={r.id}>
                    <td>{instrumentName(r.instrument_id)}</td>
                    <td><QuoteBadge status={r.quote_status} /></td>
                    <td className="cell--num num">{fmtAmount(r.quantity)}</td>
                    <td className="cell--num num">{fmtAmount(r.market_value)}</td>
                    <td className="cell--num num">{fmtAmount(r.unrealized)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="dialog__foot" style={{ margin: "var(--space-4) calc(-1 * var(--space-5)) calc(-1 * var(--space-5))" }}>
          <button className="btn btn--secondary" onClick={() => setSnapshotDetail(null)}>关闭</button>
        </div>
      </Dialog>
    </div>
  )
}
