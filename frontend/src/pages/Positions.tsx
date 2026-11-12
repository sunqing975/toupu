import { useEffect, useState } from "react"
import { ChartPie } from "lucide-react"
import { accountsApi } from "../api/accounts"
import { positionsApi } from "../api/positions"
import { fmtAmount } from "../api/transactions"
import type { InvestmentAccount, PositionOut } from "../api/types"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"

const INSTRUMENT_TYPE_LABELS: Record<string, string> = {
  STOCK: "股票",
  ETF: "ETF",
  FUND: "基金",
  BOND: "债券",
  CASH: "现金",
}

export function Positions() {
  const [positions, setPositions] = useState<PositionOut[] | null>(null)
  const [accounts, setAccounts] = useState<InvestmentAccount[]>([])
  const [accountId, setAccountId] = useState("")

  useEffect(() => {
    accountsApi.list().then(setAccounts).catch(() => setAccounts([]))
  }, [])

  useEffect(() => {
    setPositions(null)
    positionsApi
      .list(accountId || undefined)
      .then(setPositions)
      .catch(() => setPositions([]))
  }, [accountId])

  const totalCost = positions?.reduce((s, p) => s + Number(p.total_cost), 0) ?? 0

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <p className="page__sub">按账户 × 品种聚合的持仓数量与移动加权平均成本</p>
        </div>
      </div>

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
            aria-label="按账户筛选"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
          >
            <option value="">全部账户</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>

        {positions === null ? (
          <div style={{ padding: "var(--space-4)", display: "grid", gap: "var(--space-3)" }}>
            <Skeleton />
            <Skeleton />
          </div>
        ) : positions.length === 0 ? (
          <EmptyState
            icon={<ChartPie size={40} aria-hidden />}
            title="暂无持仓"
            description="完成一笔证券买入并入账后，这里会按品种显示持仓与成本。"
          />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>账户</th>
                <th>品种</th>
                <th>类型</th>
                <th className="cell--num">数量</th>
                <th className="cell--num">单位成本</th>
                <th className="cell--num">总成本</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.account_id + p.instrument_id}>
                  <td>{accounts.find((a) => a.id === p.account_id)?.name ?? p.account_id.slice(0, 8)}</td>
                  <td>
                    {p.instrument_name}
                    <div style={{ color: "var(--color-muted-foreground)", fontSize: 12 }}>
                      {p.instrument_code}
                    </div>
                  </td>
                  <td>{INSTRUMENT_TYPE_LABELS[p.instrument_type] ?? p.instrument_type}</td>
                  <td className="cell--num num">{fmtAmount(p.quantity)}</td>
                  <td className="cell--num num">{fmtAmount(p.unit_cost)}</td>
                  <td className="cell--num num">{fmtAmount(p.total_cost)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={5} style={{ fontWeight: 600 }}>
                  合计成本
                </td>
                <td className="cell--num num" style={{ fontWeight: 600 }}>
                  {totalCost.toLocaleString("zh-CN", { maximumFractionDigits: 6 })}
                </td>
              </tr>
            </tfoot>
          </table>
        )}
      </div>
    </div>
  )
}
