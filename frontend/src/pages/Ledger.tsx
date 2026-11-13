import { useEffect, useMemo, useState } from "react"
import { BookText } from "lucide-react"
import {
  DIRECTION_LABELS,
  ENTRY_TYPE_LABELS,
  ledgerApi,
  type LedgerEntry,
} from "../api/ledger"
import { accountsApi, type InvestmentAccount } from "../api/accounts"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"
import { StatusBadge } from "../components/StatusBadge"

const fmt = (v: string) => {
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString("zh-CN", { maximumFractionDigits: 6 }) : v
}

type TypeFilter = "" | "NORMAL" | "REVERSAL"

export function Ledger() {
  const [accounts, setAccounts] = useState<InvestmentAccount[] | null>(null)
  const [accountId, setAccountId] = useState("")
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("")
  const [entries, setEntries] = useState<LedgerEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    accountsApi.list().then(setAccounts).catch(() => setAccounts([]))
  }, [])

  useEffect(() => {
    setEntries(null)
    setError(null)
    ledgerApi
      .entries({
        account_id: accountId || undefined,
        entry_type: typeFilter || undefined,
        limit: 200,
      })
      .then(setEntries)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [accountId, typeFilter])

  const accountName = useMemo(() => {
    const a = accounts?.find((x) => x.id === accountId)
    return a ? a.name : ""
  }, [accounts, accountId])

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h2 className="page__title">账本</h2>
          <p className="page__sub">复式记账分录流水（只读）。每笔交易过账后生成一条分录，借贷平衡。</p>
        </div>
        <div className="toolbar">
          <select
            className="select"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            aria-label="按账户过滤"
          >
            <option value="">全部账户</option>
            {accounts?.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          <select
            className="select"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as TypeFilter)}
            aria-label="按类型过滤"
          >
            <option value="">全部类型</option>
            <option value="NORMAL">正常</option>
            <option value="REVERSAL">冲正</option>
          </select>
        </div>
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {entries === null ? (
        <Skeleton rows={8} />
      ) : entries.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={<BookText size={40} aria-hidden />}
            title="暂无分录"
            description="还没有任何已入账的交易。先在「交易」或「基金」中录入并过账。"
          />
        </div>
      ) : (
        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th>过账时间</th>
                <th>类型</th>
                <th>摘要</th>
                <th className="num">借</th>
                <th className="num">贷</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => {
                const debit = e.lines
                  .filter((l) => l.direction === "DEBIT")
                  .reduce((s, l) => s + Number(l.amount), 0)
                const credit = e.lines
                  .filter((l) => l.direction === "CREDIT")
                  .reduce((s, l) => s + Number(l.amount), 0)
                const summary = e.lines
                  .map((l) => `${l.ledger_account_name} ${DIRECTION_LABELS[l.direction] ?? l.direction} ${fmt(l.amount)}`)
                  .join("；")
                return (
                  <tr key={e.id}>
                    <td className="num">{new Date(e.posted_at).toLocaleString("zh-CN")}</td>
                    <td>
                      <StatusBadge status={e.entry_type} />
                      <span className="muted">{ENTRY_TYPE_LABELS[e.entry_type] ?? e.entry_type}</span>
                    </td>
                    <td>{summary}</td>
                    <td className="num">{fmt(debit.toFixed(6))}</td>
                    <td className="num">{fmt(credit.toFixed(6))}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="page__foot muted">
            {accountId ? `账户「${accountName}」的最新 ${entries.length} 条分录` : `最新 ${entries.length} 条分录`}
            （仅展示前 200 条）
          </p>
        </div>
      )}
    </div>
  )
}
