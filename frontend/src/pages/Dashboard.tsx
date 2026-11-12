import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Wallet, ArrowLeftRight, PieChart } from "lucide-react"
import { accountsApi } from "../api/accounts"
import { instrumentsApi } from "../api/instruments"
import { TXN_TYPE_LABELS, fmtAmount, transactionsApi, type Txn } from "../api/transactions"
import type { Instrument, InvestmentAccount } from "../api/types"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"
import { StatusBadge } from "../components/StatusBadge"

export function Dashboard() {
  const navigate = useNavigate()
  const [accounts, setAccounts] = useState<InvestmentAccount[] | null>(null)
  const [instruments, setInstruments] = useState<Instrument[] | null>(null)
  const [recent, setRecent] = useState<Txn[] | null>(null)

  useEffect(() => {
    accountsApi.list().then(setAccounts).catch(() => setAccounts([]))
    instrumentsApi.list().then(setInstruments).catch(() => setInstruments([]))
    transactionsApi.list().then(setRecent).catch(() => setRecent([]))
  }, [])

  const todoCount = (recent ?? []).filter((t) => t.status === "DRAFT" || t.status === "CONFIRMED").length

  const noAccounts = accounts !== null && accounts.length === 0

  return (
    <div className="page">
      <div className="page__head">
        <div>
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
          <div className="stat-grid">
            <div className="card">
              <div className="card__title">总资产</div>
              <div className="card__value num">—</div>
              <div className="card__hint">随 M1 账本上线</div>
            </div>
            <div className="card">
              <div className="card__title">现金合计</div>
              <div className="card__value num">—</div>
              <div className="card__hint">随 M1 账本上线</div>
            </div>
            <div className="card">
              <div className="card__title">持仓市值</div>
              <div className="card__value num">—</div>
              <div className="card__hint">随 M2 持仓上线</div>
            </div>
            <div className="card">
              <div className="card__title">累计盈亏</div>
              <div className="card__value num">—</div>
              <div className="card__hint">随 M2 成本核算上线</div>
            </div>
          </div>

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
                    持仓构成图随 M5 上线
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
