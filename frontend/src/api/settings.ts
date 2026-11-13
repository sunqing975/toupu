// 设置相关 API：Agent Token 管理（M6 已落地，M7 配置入口的种子）。
// 模型配置 / 通知渠道 / 知识库等后续里程碑接入。
import { api } from "./client"

export interface AgentToken {
  id: string
  name: string
  scopes: string[]
  active: boolean
  revoked_at: string | null
  last_used_at: string | null
  created_at: string
}

export interface AgentTokenCreated {
  token: string
  id: string
  name: string
  scopes: string[]
}

export const ALL_SCOPES = [
  "read:accounts",
  "read:positions",
  "read:transactions",
  "read:market",
  "read:performance",
  "read:risk",
  "read:plans",
  "read:proposals",
  "write:proposals",
]

export const SCOPE_LABELS: Record<string, string> = {
  "read:accounts": "账户（只读）",
  "read:positions": "持仓（只读）",
  "read:transactions": "交易（只读）",
  "read:market": "行情（只读）",
  "read:performance": "收益（只读）",
  "read:risk": "风险（只读）",
  "read:plans": "投资计划（只读）",
  "read:proposals": "提案（只读）",
  "write:proposals": "创建提案（写入）",
}

export const settingsApi = {
  tokens: () => api<AgentToken[]>("/api/v1/agent/tokens"),
  createToken: (payload: { name: string; scopes: string[] }) =>
    api<AgentTokenCreated>("/api/v1/agent/tokens", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  revokeToken: (id: string) =>
    api<AgentToken>(`/api/v1/agent/tokens/${id}/revoke`, { method: "POST" }),
}
