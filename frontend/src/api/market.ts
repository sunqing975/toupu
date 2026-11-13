// M5 行情与收益 API：显式 MANUAL 录入行情/净值、派生估值、收益指标、快照幂等重建。
// 口径见 docs/ledger-rules.md §17；缺失/过期行情返回状态而非静默用 0 冒充。
import { api } from "./client"

const MARKET = "/api/v1/market"
const PERF = "/api/v1/performance"
const SNAP = "/api/v1/snapshots"

export type QuoteStatus = "FRESH" | "STALE" | "UNKNOWN" | "ESTIMATED"
export type DataType = "OFFICIAL" | "ESTIMATED"
export type QualityStatus = "FRESH" | "STALE" | "SUSPENDED" | "NO_QUOTE"
export type AdjustType = "NONE" | "PRE" | "POST"
export type MetricStatus = "OK" | "INSUFFICIENT_DATA" | "NO_SOLUTION"

export interface QuoteOut {
  id: string
  instrument_id: string
  quote_date: string
  provider: string
  provider_code: string | null
  data_type: string
  price: string
  adjust_type: string
  quality_status: string
  delayed: boolean
  currency: string
  collected_at: string
  market_time: string | null
}

export interface QuoteIn {
  instrument_id: string
  quote_date: string
  price: string
  provider?: string
  provider_code?: string | null
  data_type?: DataType
  quality_status?: QualityStatus
  adjust_type?: AdjustType
  delayed?: boolean
  currency?: string
}

export interface NavOut {
  id: string
  instrument_id: string
  nav_date: string
  provider: string
  provider_code: string | null
  data_type: string
  nav: string
  accumulated_nav: string | null
  quality_status: string
  collected_at: string
}

export interface NavIn {
  instrument_id: string
  nav_date: string
  nav: string
  provider?: string
  provider_code?: string | null
  data_type?: DataType
  accumulated_nav?: string | null
  quality_status?: QualityStatus
}

export interface QuoteView {
  price: string | null
  status: QuoteStatus
  quote_date: string | null
  provider: string | null
  data_type: string | null
  adjust_type: string | null
  quality_status: string | null
}

export interface ValuationRow {
  account_id: string
  instrument_id: string
  instrument_code: string
  instrument_name: string
  instrument_type: string
  quantity: string
  book_cost: string
  quote: QuoteView
  market_value: string | null
  unrealized: string | null
  valued: boolean
}

export interface ValuationOut {
  as_of: string
  stale_days: number
  positions: ValuationRow[]
  cash_total: string
  market_value: string
  total_assets: string
  realized_total: string
  dividend_income: string
  unrealized_total: string
  coverage: string
  valued_positions: number
  total_positions: number
  data_quality: string
}

export interface SummaryOut {
  as_of: string
  cash_total: string
  market_value: string
  total_assets: string
  realized_total: string
  dividend_income: string
  unrealized_total: string
  book_cost_total: string
  coverage: string
  valued_positions: number
  total_positions: number
  data_quality: string
}

export interface MetricOut {
  status: MetricStatus
  value: string | null
  missing: string[]
  reason: string | null
  peak_date: string | null
  trough_date: string | null
}

export interface ReturnsOut {
  as_of: string
  xirr: MetricOut
  twr: MetricOut
  max_drawdown: MetricOut
}

export interface PositionSnapshot {
  id: string
  snapshot_date: string
  account_id: string
  instrument_id: string
  quantity: string
  book_cost: string
  quote_price: string | null
  quote_status: QuoteStatus
  quote_date: string | null
  quote_provider: string | null
  market_value: string | null
  unrealized: string | null
  created_at: string
}

export interface PortfolioSnapshot {
  id: string
  snapshot_date: string
  cash_total: string
  market_value: string
  total_assets: string
  realized_total: string
  dividend_income: string
  unrealized_total: string
  coverage: string
  valued_positions: number
  total_positions: number
  data_quality: string
  created_at: string
}

export interface RebuildOut {
  snapshot: PortfolioSnapshot
  positions: PositionSnapshot[]
}

export const QUOTE_STATUS_LABELS: Record<string, string> = {
  FRESH: "有效报价",
  STALE: "已过期",
  UNKNOWN: "无报价",
  ESTIMATED: "盘中估值",
}

export const QUOTE_STATUS_TONE: Record<string, string> = {
  FRESH: "green",
  STALE: "yellow",
  UNKNOWN: "gray",
  ESTIMATED: "blue",
}

export const DATA_TYPE_LABELS: Record<string, string> = {
  OFFICIAL: "正式",
  ESTIMATED: "盘中估值",
}

export const DATA_QUALITY_LABELS: Record<string, string> = {
  COMPLETE: "报价完整",
  PARTIAL: "部分缺失",
  NO_QUOTES: "无报价",
}

export const METRIC_STATUS_LABELS: Record<string, string> = {
  OK: "已计算",
  INSUFFICIENT_DATA: "数据不足",
  NO_SOLUTION: "无解",
}

function params(asOf: string, staleDays: number): string {
  return `?as_of=${encodeURIComponent(asOf)}&stale_days=${staleDays}`
}

export const marketApi = {
  quotes: (instrumentId?: string) =>
    api<QuoteOut[]>(instrumentId ? `${MARKET}/quotes?instrument_id=${instrumentId}` : `${MARKET}/quotes`),
  createQuote: (payload: QuoteIn) =>
    api<QuoteOut>(`${MARKET}/quotes`, { method: "POST", body: JSON.stringify(payload) }),
  navs: (instrumentId?: string) =>
    api<NavOut[]>(instrumentId ? `${MARKET}/navs?instrument_id=${instrumentId}` : `${MARKET}/navs`),
  createNav: (payload: NavIn) =>
    api<NavOut>(`${MARKET}/navs`, { method: "POST", body: JSON.stringify(payload) }),
  valuation: (asOf: string, staleDays = 7) =>
    api<ValuationOut>(`${MARKET}/valuation${params(asOf, staleDays)}`),
  summary: (asOf: string, staleDays = 7) =>
    api<SummaryOut>(`${PERF}/summary${params(asOf, staleDays)}`),
  returns: (asOf: string, staleDays = 7) =>
    api<ReturnsOut>(`${PERF}/returns${params(asOf, staleDays)}`),
  snapshots: () => api<PortfolioSnapshot[]>(SNAP),
  snapshotPositions: (snapshotDate: string) =>
    api<PositionSnapshot[]>(`${SNAP}/${snapshotDate}/positions`),
  rebuild: (snapshotDate: string, staleDays = 7) =>
    api<RebuildOut>(`${SNAP}/rebuild?stale_days=${staleDays}`, {
      method: "POST",
      body: JSON.stringify({ snapshot_date: snapshotDate }),
    }),
}
