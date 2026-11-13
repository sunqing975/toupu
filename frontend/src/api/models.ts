// Agent 模型配置 API（M7 §模型配置）：密钥只写不读，列表/详情均不回显。
import { api } from "./client"

export interface AgentModel {
  id: string
  name: string
  display_name?: string | null
  provider: string
  base_url: string
  model: string
  is_default: boolean
  created_at: string
}

export interface AgentModelIn {
  name: string
  display_name?: string | null
  provider?: string
  base_url: string
  model: string
  api_key?: string | null
  is_default?: boolean
}

export interface AgentModelPatch {
  name?: string
  display_name?: string | null
  provider?: string
  base_url?: string
  model?: string
  api_key?: string | null
  is_default?: boolean
}

export const modelsApi = {
  list: () => api<AgentModel[]>("/api/v1/agent/models"),
  create: (payload: AgentModelIn) =>
    api<AgentModel>("/api/v1/agent/models", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  update: (id: string, payload: AgentModelPatch) =>
    api<AgentModel>(`/api/v1/agent/models/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  remove: (id: string) =>
    api<void>(`/api/v1/agent/models/${id}`, { method: "DELETE" }),
}
