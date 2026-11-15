// M6 风险/Agent 提案/投资计划 API（docs/risk-agent-rules.md §11）。
import { api } from "./client"

export interface RiskRule {
  id: string
  scope: string
  rule_type: string
  threshold: string
  severity: string
  enabled: boolean
  cooldown_minutes: number
  memo: string | null
}

export interface RiskEvent {
  id: string
  rule_id: string
  as_of: string
  scope: string
  subject: string
  rule_type: string
  severity: string
  trigger_value: string | null
  threshold: string
  message: string
  status: string
  dedup_key: string
  triggered_at: string
  resolved_at: string | null
  resolution_note: string | null
}

export interface ScanSkipped {
  rule_id: string
  rule_type: string
  subject: string
  reason: string
}

export interface ScanResult {
  as_of: string
  evaluated_rules: number
  created: RiskEvent[]
  skipped: ScanSkipped[]
}

export interface Proposal {
  id: string
  proposal_type: string
  status: string
  created_by: string
  payload: Record<string, unknown>
  impact_preview: Record<string, unknown>
  validation_snapshot: Record<string, unknown>
  expires_at: string
  resolved_at: string | null
  resolved_by: string | null
  resolution_note: string | null
  resulting_transaction_id: string | null
  created_at: string
  is_expired: boolean
}

export interface PlanAction {
  id: string
  plan_id: string
  title: string
  note: string | null
  target_amount: string | null
  sort_no: number
  created_at: string
}

export interface Plan {
  id: string
  name: string
  description: string | null
  status: string
  target_amount: string | null
  created_at: string
}

export interface PlanDetail extends Plan {
  actions: PlanAction[]
}

export const SCOPE_LABELS: Record<string, string> = {
  PORTFOLIO: "组合",
  ACCOUNT: "账户",
  INSTRUMENT: "品种",
}

export const RULE_TYPE_LABELS: Record<string, string> = {
  POSITION_WEIGHT: "单品种集中度",
  ACCOUNT_WEIGHT: "单账户集中度",
  PORTFOLIO_DRAWDOWN: "组合最大回撤",
  QUOTE_COVERAGE: "行情覆盖率",
}

export const SEVERITY_LABELS: Record<string, string> = {
  INFO: "提示",
  WARNING: "警告",
  CRITICAL: "严重",
}

export const EVENT_STATUS_LABELS: Record<string, string> = {
  OPEN: "待处理",
  ACKNOWLEDGED: "已确认",
  IGNORED: "已忽略",
}

export const PROPOSAL_STATUS_LABELS: Record<string, string> = {
  PENDING: "未处理",
  APPROVED: "已生成草稿",
  REJECTED: "已忽略",
  EXPIRED: "已过期",
}

export const TXN_LABELS: Record<string, string> = {
  DEPOSIT: "入金",
  WITHDRAW: "出金",
  ACCOUNT_TRANSFER: "转账",
}

// scope → 允许的规则类型（与后端 VALID_COMBINATIONS 一致）
export const SCOPE_RULE_TYPES: Record<string, string[]> = {
  PORTFOLIO: ["PORTFOLIO_DRAWDOWN", "QUOTE_COVERAGE"],
  ACCOUNT: ["ACCOUNT_WEIGHT"],
  INSTRUMENT: ["POSITION_WEIGHT"],
}

export const riskApi = {
  rules: () => api<RiskRule[]>("/api/v1/risk/rules"),
  createRule: (payload: Record<string, unknown>) =>
    api<RiskRule>("/api/v1/risk/rules", { method: "POST", body: JSON.stringify(payload) }),
  updateRule: (id: string, payload: Record<string, unknown>) =>
    api<RiskRule>(`/api/v1/risk/rules/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  scan: (as_of: string) =>
    api<ScanResult>("/api/v1/risk/scan", { method: "POST", body: JSON.stringify({ as_of }) }),
  events: (params?: { status?: string; severity?: string }) => {
    const q = new URLSearchParams()
    if (params?.status) q.set("status", params.status)
    if (params?.severity) q.set("severity", params.severity)
    const qs = q.toString()
    return api<RiskEvent[]>(qs ? `/api/v1/risk/events?${qs}` : "/api/v1/risk/events")
  },
  acknowledge: (id: string, note: string | null) =>
    api<RiskEvent>(`/api/v1/risk/events/${id}/acknowledge`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  ignore: (id: string, note: string | null) =>
    api<RiskEvent>(`/api/v1/risk/events/${id}/ignore`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
}

export const plansApi = {
  proposals: (status?: string) => {
    const qs = status ? `?status_filter=${status}` : ""
    return api<Proposal[]>(`/api/v1/plans/proposals${qs}`)
  },
  createDraft: (id: string, note: string | null) =>
    api<Proposal>(`/api/v1/plans/proposals/${id}/create-draft`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  rejectProposal: (id: string, note: string | null) =>
    api<Proposal>(`/api/v1/plans/proposals/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  plans: (status?: string) => {
    const qs = status ? `?status_filter=${status}` : ""
    return api<Plan[]>(`/api/v1/plans${qs}`)
  },
  plan: (id: string) => api<PlanDetail>(`/api/v1/plans/${id}`),
  createPlan: (payload: Record<string, unknown>) =>
    api<Plan>("/api/v1/plans", { method: "POST", body: JSON.stringify(payload) }),
  addAction: (planId: string, payload: Record<string, unknown>) =>
    api<PlanAction>(`/api/v1/plans/${planId}/actions`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  archivePlan: (id: string) =>
    api<Plan>(`/api/v1/plans/${id}/archive`, { method: "POST" }),
}
