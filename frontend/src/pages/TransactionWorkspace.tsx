import { useEffect, useState } from "react"
import { Transactions } from "./Transactions"
import { Funds } from "./Funds"
import { transactionsApi, TXN_TYPE_LABELS } from "../api/transactions"
import { fundsApi, FUND_TYPE_LABELS } from "../api/funds"
import { accountsApi } from "../api/accounts"
import { instrumentsApi } from "../api/instruments"
import { fmtMoney } from "../api/marketFormat"

type Row = {id: string; venue: "场内" | "场外"; date: string; confirmed: string | null; account: string; instrument: string; type: string; amount: string | null; status: string; pending: boolean; rawStatus: string}
export function TransactionWorkspace() {
  const [rows, setRows] = useState<Row[]>([])
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const [choose, setChoose] = useState(false)
  const [venue, setVenue] = useState("场外")
  const [fundDetail, setFundDetail] = useState<string>()
  const [exchangeDetail, setExchangeDetail] = useState<string>()
  const [confirmId, setConfirmId] = useState<string>()
  const [filter, setFilter] = useState("")
  const [accountFilter, setAccountFilter] = useState("")
  const [instrumentFilter, setInstrumentFilter] = useState("")
  const [venueFilter, setVenueFilter] = useState("")
  const [accountOptions, setAccountOptions] = useState<{id:string;name:string}[]>([])
  const [instrumentOptions, setInstrumentOptions] = useState<{id:string;name:string}[]>([])
  useEffect(() => {
    let active = true
    setLoading(true); setError("")
    Promise.all([transactionsApi.list({investment_only:true, active_only:true, account_id: accountFilter || undefined, instrument_id: instrumentFilter || undefined}), fundsApi.list({active_only:true, account_id: accountFilter || undefined, instrument_id: instrumentFilter || undefined}), accountsApi.list(), instrumentsApi.list()]).then(([txns,funds,accounts,instruments]) => {
      if (!active) return
      setAccountOptions(accounts); setInstrumentOptions(instruments)
      const name = (id: string) => instruments.find(i => i.id===id)?.name ?? "未知品种"
      const account = (id: string) => accounts.find(a => a.id===id)?.name ?? "未知账户"
      const label = (_s: string, pending: boolean) => pending ? "确认份额中" : "已完成"
      const a: Row[] = txns.filter(t => t.status === "POSTED").map(t => ({id:t.id,venue:"场内",date:t.business_date,confirmed:t.business_date,account:account(t.account_id),instrument:name(t.instrument_id ?? ""),type:TXN_TYPE_LABELS[t.transaction_type] ?? t.transaction_type,amount:t.total_amount,status:label(t.status,false),pending:false,rawStatus:t.status}))
      const b: Row[] = funds.filter(t => t.status === "POSTED" || (t.status === "DRAFT" && t.confirmation_status === "PENDING")).map(t => ({id:t.id,venue:"场外",date:t.business_date,confirmed:t.confirmation_date,account:account(t.account_id),instrument:name(t.instrument_id),type:FUND_TYPE_LABELS[t.transaction_type] ?? t.transaction_type,amount:t.apply_amount ?? t.total_amount,status:label(t.status,t.confirmation_status==="PENDING"),pending:t.confirmation_status==="PENDING",rawStatus:t.status}))
      setRows([...a,...b].sort((x,y) => y.date.localeCompare(x.date)))
    }).catch(e => {if(active)setError((e as Error).message)}).finally(() => {if(active)setLoading(false)})
    return () => {active=false}
  }, [revision, accountFilter, instrumentFilter])
  const changed = () => setRevision(v=>v+1)
  const marketSelector = <label className="field"><span className="field__label">交易市场</span><select className="select" value={venue} onChange={e=>setVenue(e.target.value)}><option>场外</option><option>场内</option></select></label>
  return <div className="page stack">
    <div className="page__head"><p className="page__sub">买入、卖出和分红统一查看；场外基金确认后补充日期与份额，不需要维护入金出金。</p><button className="btn btn--primary" onClick={()=>setChoose(true)}>新建交易</button></div>
    <div style={{display:"flex",gap:12,flexWrap:"wrap"}}><label className="field"><span className="field__label">账户</span><select className="select" value={accountFilter} onChange={e=>setAccountFilter(e.target.value)}><option value="">全部账户</option>{accountOptions.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label><label className="field"><span className="field__label">品种</span><select className="select" value={instrumentFilter} onChange={e=>setInstrumentFilter(e.target.value)}><option value="">全部品种</option>{instrumentOptions.map(i=><option key={i.id} value={i.id}>{i.name}</option>)}</select></label><label className="field"><span className="field__label">市场</span><select className="select" value={venueFilter} onChange={e=>setVenueFilter(e.target.value)}><option value="">场内和场外</option><option>场内</option><option>场外</option></select></label>
    <label className="field"><span className="field__label">状态筛选</span><select className="select" value={filter} onChange={e=>setFilter(e.target.value)}><option value="">全部状态</option>{["已完成","确认份额中"].map(s=><option key={s}>{s}</option>)}</select></label><button className="btn btn--secondary" onClick={()=>{setAccountFilter("");setInstrumentFilter("");setVenueFilter("");setFilter("")}}>清除筛选</button></div>
    {error && <div role="alert" className="banner banner--error">{error}<button className="btn btn--secondary" onClick={changed}>重试</button></div>}
    <div className="card table-scroll">{loading ? <p role="status">加载交易记录…</p> : <table className="table"><thead><tr><th>记录日期</th><th>品种 / 账户</th><th>市场</th><th>方向</th><th>金额</th><th>确认 / 成交日期</th><th>状态</th><th>操作</th></tr></thead><tbody>{rows.filter(r=>(!filter || r.status===filter) && (!venueFilter || r.venue===venueFilter)).map(r=><tr key={r.id}><td>{r.date}</td><td>{r.instrument}<div className="muted">{r.account}</div></td><td>{r.venue}</td><td>{r.type}</td><td className="num">{fmtMoney(r.amount)}</td><td>{r.confirmed ?? "待确认"}</td><td>{r.status}</td><td><button className="btn btn--secondary" onClick={()=>{ if(r.venue==="场外"){setFundDetail(undefined);setTimeout(()=>setFundDetail(r.id),0)}else{setExchangeDetail(undefined);setTimeout(()=>setExchangeDetail(r.id),0)} }}>详情</button>{r.pending && r.rawStatus==="DRAFT" && <button className="btn btn--secondary" onClick={()=>{setConfirmId(undefined);setTimeout(()=>setConfirmId(r.id),0)}}>补充确认份额</button>}{r.rawStatus==="CONFIRMED" && <button className="btn btn--secondary" onClick={async()=>{try{await transactionsApi.post(r.id);changed()}catch(e){setError((e as Error).message)}}}>确认记账</button>}{r.venue==="场内" && r.rawStatus==="DRAFT" && <button className="btn btn--secondary" onClick={async()=>{try{await transactionsApi.confirm(r.id);changed()}catch(e){setError((e as Error).message)}}}>核对成交</button>}</td></tr>)}</tbody></table>}{!loading && !error && rows.length===0 && <p>暂无交易记录。</p>}</div>

    <Funds embedded dialogOnly createOpen={choose && venue === "场外"} onCreateClose={()=>setChoose(false)} marketSelector={marketSelector} detailId={fundDetail} confirmId={confirmId} onChanged={changed}/>
    <Transactions embedded dialogOnly createOpen={choose && venue === "场内"} onCreateClose={()=>setChoose(false)} marketSelector={marketSelector} detailId={exchangeDetail} onChanged={changed}/>
  </div>
}
