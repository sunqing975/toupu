import { api } from "./client"

export interface Txn {
  id: string
  account_id: string
  counter_account_id: string | null
  instrument_id: string | null
  transaction_type: string
  status: string
  business_date: string
  currency: string
  total_amount: string | null
  memo: string | null
  reversal_of_id: string | null
}

// 成交明细：一笔证券交易可由多笔成交组成（服务端据此计算总成本/净金额）。
export interface ExecutionIn {
  execution_date: string
  quantity: number
  price: number
  fee_amount: number
}

export interface ExecutionOut {
  id: string
  sequence_no: number
  execution_date: string
  quantity: string
  price: string
  gross_amount: string
  fee_amount: string
  net_amount: string
}

export const SECURITY_BUY_TYPES = ["STOCK_BUY", "ETF_BUY"] as const
export const SECURITY_SELL_TYPES = ["STOCK_SELL", "ETF_SELL"] as const
export const SECURITY_TYPES = [...SECURITY_BUY_TYPES, ...SECURITY_SELL_TYPES] as const

// 新建交易可选的全部类型（含 M2 证券买卖）。
export const FORM_TYPES = [
  { value: "DEPOSIT", label: "入金" },
  { value: "WITHDRAW", label: "出金" },
  { value: "ACCOUNT_TRANSFER", label: "转账" },
  { value: "STOCK_BUY", label: "买入股票" },
  { value: "STOCK_SELL", label: "卖出股票" },
  { value: "ETF_BUY", label: "买入ETF" },
  { value: "ETF_SELL", label: "卖出ETF" },
] as const

export function isSecurityType(t: string): boolean {
  return (SECURITY_TYPES as readonly string[]).includes(t)
}

export interface EntryLine {
  direction: string
  amount: string
  ledger_account_id: string
  ledger_account_name: string
}

export interface TxnDetail extends Txn {
  entry: { id: string; entry_type: string; lines: EntryLine[] } | null
  executions: ExecutionOut[]
}

const BASE = "/api/v1/transactions"

export const transactionsApi = {
  list: (params?: { status_filter?: string; account_id?: string }) => {
    const q = new URLSearchParams()
    if (params?.status_filter) q.set("status_filter", params.status_filter)
    if (params?.account_id) q.set("account_id", params.account_id)
    const qs = q.toString()
    return api<Txn[]>(qs ? `${BASE}?${qs}` : BASE)
  },
  get: (id: string) => api<TxnDetail>(`${BASE}/${id}`),
  create: (payload: Record<string, unknown>) => api<TxnDetail>(BASE, { method: "POST", body: JSON.stringify(payload) }),
  confirm: (id: string) => api<Txn>(`${BASE}/${id}/confirm`, { method: "POST" }),
  post: (id: string) => api<TxnDetail>(`${BASE}/${id}/post`, { method: "POST" }),
  reverse: (id: string) => api<TxnDetail>(`${BASE}/${id}/reverse`, { method: "POST" }),
  cancel: (id: string) => api<Txn>(`${BASE}/${id}/cancel`, { method: "POST" }),
}

export const TXN_TYPE_LABELS: Record<string, string> = {
  DEPOSIT: "入金",
  WITHDRAW: "出金",
  ACCOUNT_TRANSFER: "转账",
  STOCK_BUY: "买入股票",
  STOCK_SELL: "卖出股票",
  ETF_BUY: "买入ETF",
  ETF_SELL: "卖出ETF",
  FUND_SUBSCRIBE: "基金申购",
  FUND_REDEEM: "基金赎回",
  OPENING_BALANCE: "期初余额",
  SECURITY_BUY: "证券买入",
  SECURITY_SELL: "证券卖出",
}

// 仅展示用途：把 "10000.000000" 格式化为千分位并去掉多余零（展示层格式化，不回写）。
export function fmtAmount(v: string | null | undefined): string {
  if (v === null || v === undefined) return "—"
  const n = Number(v)
  return n.toLocaleString("zh-CN", { maximumFractionDigits: 6 })
}
