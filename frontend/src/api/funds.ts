import { api } from "./client"

// 场外基金（M3）：申请 → 确认（净值/份额/费用）→ 过账。与证券成交明细分离。
// 生命周期与字段语义见 docs/ledger-rules.md §15。
export type FundTxnType = "FUND_SUBSCRIBE" | "FUND_REDEEM" | "CASH_DIVIDEND" | "DIVIDEND_REINVEST"

export const FUND_TYPES: FundTxnType[] = [
  "FUND_SUBSCRIBE",
  "FUND_REDEEM",
  "CASH_DIVIDEND",
  "DIVIDEND_REINVEST",
]

export const FUND_TYPE_LABELS: Record<string, string> = {
  FUND_SUBSCRIBE: "买入",
  FUND_REDEEM: "卖出",
  CASH_DIVIDEND: "现金分红",
  DIVIDEND_REINVEST: "红利再投资",
}

// 两段式申请（需要录入确认净值/份额）；现金分红创建即确认，无需此步。
export const TWO_STAGE_TYPES: FundTxnType[] = ["FUND_SUBSCRIBE", "FUND_REDEEM", "DIVIDEND_REINVEST"]

export function isFundType(t: string): boolean {
  return (FUND_TYPES as string[]).includes(t)
}

export function isTwoStageType(t: string): boolean {
  return (TWO_STAGE_TYPES as string[]).includes(t)
}

export interface FundOrder {
  id: string
  account_id: string
  instrument_id: string
  transaction_type: string
  status: string
  confirmation_status: string | null
  business_date: string
  confirmation_date: string | null
  currency: string
  total_amount: string | null
  memo: string | null
  platform: string
  apply_amount: string | null
  apply_shares: string | null
  expected_fee: string | null
}

export interface FundConfirmation {
  confirmation_date: string
  nav: string
  confirmed_shares: string
  confirmed_amount: string
  fee_amount: string
}

export interface FundEntryLine {
  direction: string
  amount: string
  ledger_account_id: string
  ledger_account_name: string
}

export interface FundOrderDetail extends FundOrder {
  confirmation: FundConfirmation | null
  entry: { id: string; entry_type: string; posted_at: unknown; lines: FundEntryLine[] } | null
}

// 新建申请入参：按类型只传相关字段（服务端 check_shape 会校验必填）。
export interface FundOrderCreate {
  transaction_type: FundTxnType
  account_id: string
  instrument_id: string
  business_date: string
  platform?: string
  apply_amount?: string
  apply_shares?: string
  expected_fee?: string
  memo?: string | null
}

export interface FundConfirmationIn {
  confirmation_date: string
  nav: string
  confirmed_shares: string
  confirmed_amount: string
  fee_amount: string
}

const BASE = "/api/v1/funds/orders"

export const fundsApi = {
  list: (params?: { account_id?: string; instrument_id?: string; transaction_type?: string; status_filter?: string; active_only?: boolean }) => {
    const q = new URLSearchParams()
    if (params?.active_only) q.set("active_only", "true")
    if (params?.instrument_id) q.set("instrument_id", params.instrument_id)
    if (params?.account_id) q.set("account_id", params.account_id)
    if (params?.transaction_type) q.set("transaction_type", params.transaction_type)
    if (params?.status_filter) q.set("status_filter", params.status_filter)
    const qs = q.toString()
    return api<FundOrder[]>(qs ? `${BASE}?${qs}` : BASE)
  },
  get: (id: string) => api<FundOrderDetail>(`${BASE}/${id}`),
  create: (payload: FundOrderCreate) =>
    api<FundOrderDetail>(BASE, { method: "POST", body: JSON.stringify(payload) }),
  confirm: (id: string, payload: FundConfirmationIn) =>
    api<FundOrderDetail>(`${BASE}/${id}/confirm`, { method: "POST", body: JSON.stringify(payload) }),
  fail: (id: string) => api<FundOrder>(`${BASE}/${id}/fail`, { method: "POST" }),
}
