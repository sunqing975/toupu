import { useEffect, useState } from "react"
import { api } from "../api/client"
import { fmtMoney, fmtQuantity } from "../api/marketFormat"
type Row = {id:string;name:string;account:string;value:string|null;quantity:string|null;cost:string|null;pnl:string|null;date:string|null;basis:string;weight:string|null}
export function OverviewHoldings(){
 const [data,setData]=useState<{rows:Row[];holdings_value:string;pending_total:string;warning:string}|null>(null)
 const [error,setError]=useState("")
 const [group,setGroup]=useState("holding")
 useEffect(()=>{api<typeof data>("/api/v1/performance/holdings-overview").then(setData).catch(e=>setError((e as Error).message))},[])
 const colors=["#2748c8","#008579","#bf783b","#8059a6","#b94b66","#5a7894","#767c37"]
 const groups: {name:string;value:number}[]=[]
 for(const r of data?.rows??[]){if(r.value===null)continue;const name=group==="account"?r.account:r.name;const old=groups.find(g=>g.name===name);if(old)old.value+=Number(r.value);else groups.push({name,value:Number(r.value)})}
 const total=groups.reduce((s,g)=>s+g.value,0);let start=0
 const segments=groups.map((g,i)=>{const from=start;start+=total>0?g.value/total*100:0;return colors[i%colors.length]+" "+from+"% "+start+"%"}).join(",")
 return <section className="card stack" style={{padding:"var(--space-4)",marginTop:"var(--space-5)"}}><h2>持仓与资产分布</h2>{error&&<p role="alert">{error}</p>}{!data&&!error&&<p role="status">正在加载持仓…</p>}{data&&<><p className="muted">{data.warning}</p><label>分布方式 <select className="select" value={group} onChange={e=>setGroup(e.target.value)}><option value="holding">按持仓</option><option value="account">按账户</option></select></label><div style={{display:"flex",gap:24,flexWrap:"wrap",alignItems:"center"}}>{total>0&&<div role="img" aria-label={groups.map(g=>g.name+" "+(g.value/total*100).toFixed(2)+"%").join("；")} style={{width:200,height:200,borderRadius:"50%",background:"conic-gradient("+segments+")",position:"relative"}}><div style={{position:"absolute",inset:40,borderRadius:"50%",background:"var(--color-card)",display:"grid",placeContent:"center",textAlign:"center"}}><span>持仓金额</span><strong>{fmtMoney(data.holdings_value)}</strong></div></div>}<ul style={{listStyle:"none",padding:0}}>{groups.map((g,i)=><li key={g.name}><span aria-hidden style={{color:colors[i%colors.length]}}>● </span>{g.name} · {total>0?(g.value/total*100).toFixed(2):"0.00"}%</li>)}</ul></div><p>待确认资金：<strong>{fmtMoney(data.pending_total)} 元</strong>（单列，不计入环形图份额）</p><div className="table-scroll"><table className="table"><thead><tr><th>持仓 / 账户</th><th>市值</th><th>占比</th><th>盈亏</th><th>价格依据 / 日期</th><th>详情</th></tr></thead><tbody>{data.rows.map(r=><tr key={r.id}><td>{r.name}<div className="muted">{r.account}</div></td><td>{fmtMoney(r.value)}</td><td>{r.weight===null?"—":(Number(r.weight)*100).toFixed(2)+"%"}</td><td>{fmtMoney(r.pnl)}</td><td>{r.basis}<div>{r.date??"未知"}</div></td><td><details><summary>份额与成本</summary><p>份额：{r.quantity===null?"组合不适用":fmtQuantity(r.quantity)}</p><p>账面成本：{fmtMoney(r.cost)}</p><a href="/transactions">查看交易记录</a></details></td></tr>)}</tbody></table></div></>}</section>
}
