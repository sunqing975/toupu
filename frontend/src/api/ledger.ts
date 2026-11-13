// 账本只读 API（docs 不涉及，纯展现）。金额均为六位小数字符串。
import { api } from "./client"

export interface LedgerLine {
  ledger_account_id: string
  ledger_account_name: string
  direction: string
  amount: string
  line_no: number
}

export interface LedgerEntry {
  id: string
  transaction_id: string
  entry_type: string
  reversal_of_entry_id: string | null
  posted_at: string
  lines: LedgerLine[]
}

export interface LedgerParams {
  account_id?: string
  entry_type?: string
  from_date?: string
  to_date?: string
  limit?: number
}

export const ledgerApi = {
  entries: (params?: LedgerParams) => {
    const q = new URLSearchParams()
    if (params?.account_id) q.set("account_id", params.account_id)
    if (params?.entry_type) q.set("entry_type", params.entry_type)
    if (params?.from_date) q.set("from_date", params.from_date)
    if (params?.to_date) q.set("to_date", params.to_date)
    if (params?.limit) q.set("limit", String(params.limit))
    const qs = q.toString()
    return api<LedgerEntry[]>(qs ? `/api/v1/ledger/entries?${qs}` : "/api/v1/ledger/entries")
  },
}

export const ENTRY_TYPE_LABELS: Record<string, string> = {
  NORMAL: "正常",
  REVERSAL: "冲正",
}

export const DIRECTION_LABELS: Record<string, string> = {
  DEBIT: "借",
  CREDIT: "贷",
}
