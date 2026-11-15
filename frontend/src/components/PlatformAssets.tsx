import { useEffect, useState } from "react"
import { api } from "../api/client"

type Observation = { id: string; account_id: string; observed_on: string; source: string; market_value: string; holding_pnl: string; warning: string; pending: {code: string; amount: string; expected_confirmation_date: string}[]; items: {id: string; name: string; kind: string; code: string | null; market_value: string; holding_pnl: string; cumulative_pnl: string | null; reference_cost: string; quantity: string | null; reconstructed_quantity: string | null; advisory?: {flow_count: number; nominal_contributions: string; personal_contributions: string; subsidy: string; nominal_pnl: string | null; personal_pnl: string | null; unknown_fees: string; warning: string; flows: {external_id: string; kind: string; occurred_on: string; confirmed_on: string | null; amount: string; subsidy: string; fee_scope: string}[]}}[] }
type Account = {id: string; name: string}

export function PlatformAssets() {
  const [rows, setRows] = useState<Observation[] | null>(null)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [error, setError] = useState("")
  useEffect(() => { Promise.all([api<Observation[]>("/api/v1/platform-assets"), api<Account[]>("/api/v1/accounts")]).then(([r, a]) => { setRows(r); setAccounts(a) }).catch(e => setError((e as Error).message)) }, [])
  return <section className="card stack" style={{padding: "var(--space-4)"}}>
    <div><h2>现有资产 · 平台快照</h2><p className="muted">先记现在持有什么，不要求补齐历史流水。以下为平台展示值，独立于正式账本，不与账本持仓重复相加。</p></div>
    {error && <p className="banner banner--error" role="alert">{error}</p>}
    {!rows && !error && <p role="status">加载平台资产…</p>}
    {rows?.length === 0 && <p className="muted">暂无平台快照。只有份额和成本齐全时，才使用下方正式期初资产导入。</p>}
    {rows?.map(row => <article className="stack" key={row.id}>
      <h3>{accounts.find(a => a.id === row.account_id)?.name ?? "投资账户"} · {row.observed_on}</h3>
      <p>平台持有金额 <strong className="num">¥{row.market_value}</strong> · 持有收益 <strong className="num">¥{row.holding_pnl}</strong></p>
      <div className="table-scroll"><table className="table"><thead><tr><th>资产</th><th>代码 / 类型</th><th>持有金额</th><th>持有收益</th><th>平台累计收益</th><th>参考成本</th><th>份额</th></tr></thead><tbody>
        {row.items.map(i => <tr key={i.id}><td>{i.name}</td><td>{i.code ?? "投顾组合"} / {i.kind === "ADVISORY" ? "组合汇总" : i.kind}</td><td className="num">{i.market_value}</td><td className="num">{i.holding_pnl}</td><td className="num">{i.cumulative_pnl ?? "未知"}</td><td className="num">{i.reference_cost}</td><td>{i.reconstructed_quantity ? i.reconstructed_quantity + "（历史已入账）" : i.quantity ?? "待补全，未入账"}</td></tr>)}
      </tbody></table></div>
      {row.items.filter(i => i.advisory && i.advisory.flow_count > 0).map(i => <details key={i.id}><summary>{i.name} · 组合整体记账（无需底层基金）</summary><div className="stack"><p>转入 {i.advisory!.nominal_contributions} 元 · 个人实付 {i.advisory!.personal_contributions} 元 · 福利 {i.advisory!.subsidy} 元</p><p>平台金额口径收益 {i.advisory!.nominal_pnl} 元 · 个人实付口径收益 {i.advisory!.personal_pnl} 元 · 来源待核实费用 {i.advisory!.unknown_fees} 元</p><p className="muted">{i.advisory!.warning}</p><div className="table-scroll"><table className="table"><thead><tr><th>日期</th><th>类型</th><th>金额</th><th>福利抵扣</th><th>确认日期 / 费用来源</th></tr></thead><tbody>{i.advisory!.flows.map(f => <tr key={f.external_id}><td>{f.occurred_on}</td><td>{{CONTRIBUTION:"转入",WITHDRAWAL:"转出",REFUND:"退款",FEE:"费用"}[f.kind] ?? f.kind}</td><td>{f.amount}</td><td>{f.subsidy}</td><td>{f.kind === "FEE" ? {UNKNOWN:"待核实，未再次扣减",INTERNAL:"组合内部，未再次扣减",EXTERNAL:"外部另付"}[f.fee_scope] : f.confirmed_on ?? "未提供"}</td></tr>)}</tbody></table></div></div></details>)}
      {row.pending.length > 0 && <details><summary>平台待确认事项（不另行加到资产中）</summary><ul>{row.pending.map((p, n) => <li key={n}>{p.code} · ¥{p.amount} · 平台预计 {p.expected_confirmation_date} 确认，需以后核对实际结果</li>)}</ul></details>}
      <p className="muted">来源：{row.source}。{row.warning} 组合按汇总记录，不同时计入底层基金；观察日期不代表全部资产的净值日期。</p>
    </article>)}
  </section>
}
