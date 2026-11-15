import { useEffect, useState } from "react"
import { api } from "../api/client"
import { fmtAmount } from "../api/transactions"

type Batch = {account_id: string; observed_on: string; items: {id: string; name: string; kind: string; market_value: string; holding_pnl: string; cumulative_pnl: string | null; advisory?: {nominal_contributions: string; personal_contributions: string; unknown_fees: string; nominal_pnl: string | null; flow_count: number}}[]}

export function AdvisoryHoldings({ accountId }: {accountId: string}) {
  const [batches, setBatches] = useState<Batch[] | null>(null)
  const [error, setError] = useState("")
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let active = true
    setError(""); setBatches(null)
    api<Batch[]>("/api/v1/platform-assets").then(data => { if (active) setBatches(data) }).catch(e => { if (active) setError((e as Error).message) })
    return () => { active = false }
  }, [retry])
  const rows = batches?.filter(b => !accountId || b.account_id === accountId).flatMap(b => b.items.filter(i => i.kind === "ADVISORY").map(i => ({...i, observed_on: b.observed_on})))
  return <section className="card stack" style={{padding: "var(--space-4)"}} aria-labelledby="advisory-holdings-title">
    <div><h2 id="advisory-holdings-title">投顾组合 · 帮你投</h2><p className="muted">独立于普通基金份额核算，直接展示已录组合金额。金额截至下列日期，不是实时市值；不与底层基金重复计算。</p></div>
    {error ? <div role="alert"><p>{error}</p><button className="btn btn--secondary" onClick={() => setRetry(v => v + 1)}>重新加载组合</button></div> : rows === undefined ? <p role="status">正在加载投顾组合…</p> : rows.length === 0 ? <p className="muted">当前账户暂无投顾组合。</p> :
      <div className="table-scroll"><table className="table"><thead><tr><th>组合</th><th>数据日期</th><th className="cell--num">已录持有金额</th><th className="cell--num">累计转入</th><th className="cell--num">个人实付</th><th className="cell--num">平台持有收益</th><th className="cell--num">平台累计收益</th></tr></thead><tbody>{rows.map(i => <tr key={i.id}><td><strong>{i.name}</strong><div className="muted">组合汇总 · 无需基金份额</div></td><td>{i.observed_on}</td><td className="cell--num">¥{fmtAmount(i.market_value)}</td><td className="cell--num">{i.advisory?.flow_count ? fmtAmount(i.advisory.nominal_contributions) : "未录入"}</td><td className="cell--num">{i.advisory?.flow_count ? fmtAmount(i.advisory.personal_contributions) : "未录入"}</td><td className="cell--num">{fmtAmount(i.holding_pnl)}</td><td className="cell--num">{i.cumulative_pnl === null ? "未知" : fmtAmount(i.cumulative_pnl)}</td></tr>)}</tbody></table></div>}
    <p className="muted">费用来源未核实的记录只作明细，不再次扣减金额；平台收益与按投入核对的收益口径分别保留。此区域不改变上方普通持仓的成本合计。</p>
  </section>
}
