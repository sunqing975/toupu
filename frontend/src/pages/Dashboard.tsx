import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Wallet, ArrowLeftRight, PieChart, TrendingUp } from "lucide-react"
import { accountsApi } from "../api/accounts"
import { instrumentsApi } from "../api/instruments"
import { TXN_TYPE_LABELS, fmtAmount, transactionsApi, type Txn } from "../api/transactions"
import { api } from "../api/client"
import { OverviewHoldings } from "../components/OverviewHoldings"
type RecordedOverview = {recorded_assets: string | null; platform_holding_pnl: string | null; platform_cumulative_pnl: string | null; item_count: number; advisory_count: number; observation_dates: string[]; unrecorded_accounts: string[]; warning: string}
import type { Instrument, InvestmentAccount } from "../api/types"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"
import { StatusBadge } from "../components/StatusBadge"

export function Dashboard() {
  const navigate = useNavigate()
  const [accounts, setAccounts] = useState<InvestmentAccount[] | null>(null)
  const [instruments, setInstruments] = useState<Instrument[] | null>(null)
  const [recent, setRecent] = useState<Txn[] | null>(null)
  const [summary, setSummary] = useState<RecordedOverview | null>(null)

  useEffect(() => {
    accountsApi.list().then(setAccounts).catch(() => setAccounts([]))
    instrumentsApi.list().then(setInstruments).catch(() => setInstruments([]))
    transactionsApi.list({ investment_only: true }).then(setRecent).catch(() => setRecent([]))
    api<RecordedOverview>("/api/v1/performance/overview").then(setSummary).catch(() => setSummary(null))
  }, [])

  const todoCount = (recent ?? []).filter((t) => t.status === "DRAFT" || t.status === "CONFIRMED").length

  const noAccounts = accounts !== null && accounts.length === 0

  const pnl = summary?.platform_holding_pnl != null ? Number(summary.platform_holding_pnl) : null
  const pnlClass = pnl === null ? "metric-card__value num" : pnl >= 0 ? "metric-card__value num num--up" : "metric-card__value num num--down"

  // 资产构成条：现金 / 平台累计收益 的相对占比（总资产为 0 时不渲染）
  const cash = 0
  const market = summary?.recorded_assets ? Number(summary.recorded_assets) : 0
  const compositionTotal = cash + market
  const cashPct = compositionTotal > 0 ? Math.round((cash / compositionTotal) * 100) : 0
  const marketPct = compositionTotal > 0 ? 100 - cashPct : 0

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <p className="page__eyebrow">OVERVIEW</p>
          <h2 className="page__title">总览</h2>
          <p className="page__sub">你的资产与待办</p>
        </div>
      </div>

      {noAccounts ? (
        <div className="card">
          <EmptyState
            icon={<Wallet size={40} aria-hidden />}
            title="先创建一个账户"
            description="券商、基金平台或现金账户都可以。账户是记账的基础，之后录入交易、导入资产都需要它。"
            action={
              <button className="btn btn--primary" onClick={() => navigate("/accounts")}>
                创建账户
              </button>
            }
          />
        </div>
      ) : (
        <>
          {summary && <div className="banner" role="status">{summary.warning}{summary.unrecorded_accounts.length > 0 && ` 尚未录入：${summary.unrecorded_accounts.join("、")}（不是零资产）。`}</div>}
          <div className="overview">
            <section className="hero-card" aria-label="总资产">
              <div className="hero-card__glow" aria-hidden />
              <div className="hero-card__top">
                <span className="hero-card__eyebrow">已录资产 · RECORDED ASSETS</span>
                <span className="hero-card__badge">平台快照口径</span>
              </div>
              <div className="hero-card__value num">
                {summary ? fmtAmount(summary.recorded_assets) : "—"}
              </div>
              <div className="hero-card__composition">
                <div className="hero-card__bar" aria-hidden>
                  <span
                    className="hero-card__bar-seg hero-card__bar-seg--cash"
                    style={{ width: `${cashPct}%` }}
                  />
                  <span
                    className="hero-card__bar-seg hero-card__bar-seg--market"
                    style={{ width: `${marketPct}%` }}
                  />
                </div>
                <div className="hero-card__legend">
                  <span>
                    <i className="hero-card__dot hero-card__dot--cash" aria-hidden /> 现金未纳入此汇总
                  </span>
                  <span>
                    <i className="hero-card__dot hero-card__dot--market" aria-hidden /> 持仓 {marketPct}%
                  </span>
                </div>
              </div>
              <p className="hero-card__foot">
                {summary ? `数据日期：${summary.observation_dates.join("、")} · 非实时市值` : "最近已录平台资产，不以缺失报价作零估值"}
              </p>
            </section>

            <div className="overview__side">
              <section className="metric-card" aria-label="投顾组合">
                <div className="metric-card__label">投顾组合</div>
                <div className="metric-card__value num">
                  {summary ? String(summary.advisory_count) : "—"}
                </div>
                <div className="metric-card__hint">已包含在左侧已录资产中，不重复相加</div>
              </section>
              <section className="metric-card" aria-label="平台累计收益">
                <div className="metric-card__label">平台累计收益</div>
                <div className="metric-card__value num">
                  {summary ? fmtAmount(summary.platform_cumulative_pnl) : "—"}
                </div>
                <div className="metric-card__hint">
                  {summary ? `已录 ${summary.item_count} 项资产（含 ${summary.advisory_count} 个组合）` : "资产数据未加载"}
                </div>
              </section>
              <section className="metric-card" aria-label="平台持有收益">
                <div className="metric-card__label">
                  平台持有收益 <TrendingUp size={14} aria-hidden />
                </div>
                <div className={pnlClass}>{pnl !== null ? fmtAmount(pnl.toString()) : "—"}</div>
                <div className="metric-card__hint">平台展示口径，不混入账本已实现收益</div>
              </section>
            </div>
          </div>

          <OverviewHoldings />
          <div className="grid-2" style={{ marginTop: "var(--space-5)" }}>
            <div className="card">
              <div className="card__title">
                近期交易
                {todoCount > 0 && (
                  <span className="badge badge--yellow" style={{ marginLeft: 8 }}>
                    待处理 {todoCount}
                  </span>
                )}
              </div>
              {recent === null ? (
                <Skeleton />
              ) : recent.length === 0 ? (
                <EmptyState
                  icon={<ArrowLeftRight size={32} aria-hidden />}
                  title="还没有交易"
                  description="从一笔入金开始记账。"
                />
              ) : (
                <table className="table">
                  <tbody>
                    {recent.slice(0, 8).map((t) => (
                      <tr key={t.id}>
                        <td className="num">{t.business_date}</td>
                        <td>{TXN_TYPE_LABELS[t.transaction_type] ?? t.transaction_type}</td>
                        <td className="cell--num num">{fmtAmount(t.total_amount)}</td>
                        <td>
                          <StatusBadge status={t.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div className="card">
              <div className="card__title">账户与品种</div>
              {accounts === null || instruments === null ? (
                <div style={{ display: "grid", gap: "var(--space-3)" }}>
                  <Skeleton />
                  <Skeleton />
                </div>
              ) : (
                <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                  <li className="num" style={{ padding: "var(--space-2) 0" }}>
                    账户 {accounts.length} 个
                  </li>
                  <li className="num" style={{ padding: "var(--space-2) 0" }}>
                    品种 {instruments.length} 个
                  </li>
                  <li style={{ padding: "var(--space-2) 0", color: "var(--color-muted-foreground)" }}>
                    <PieChart size={14} aria-hidden style={{ verticalAlign: "-2px", marginRight: 6 }} />
                    {summary ? `已录 ${summary.item_count} 项资产（含 ${summary.advisory_count} 个组合）` : "资产数据未加载"}
                  </li>
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
