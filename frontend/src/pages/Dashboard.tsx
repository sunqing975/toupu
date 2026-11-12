import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Wallet, ArrowLeftRight, PieChart } from "lucide-react"
import { accountsApi } from "../api/accounts"
import { instrumentsApi } from "../api/instruments"
import type { Instrument, InvestmentAccount } from "../api/types"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"

export function Dashboard() {
  const navigate = useNavigate()
  const [accounts, setAccounts] = useState<InvestmentAccount[] | null>(null)
  const [instruments, setInstruments] = useState<Instrument[] | null>(null)

  useEffect(() => {
    accountsApi.list().then(setAccounts).catch(() => setAccounts([]))
    instrumentsApi.list().then(setInstruments).catch(() => setInstruments([]))
  }, [])

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
              <div className="card__title">近期交易</div>
              <EmptyState
                icon={<ArrowLeftRight size={32} aria-hidden />}
                title="交易功能即将上线"
                description="交易草稿、确认与入账随 M1 里程碑推进。"
              />
            </div>
            <div className="card">
              <div className="card__title">账户与标的</div>
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
                    标的 {instruments.length} 个
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
