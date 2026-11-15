// Agent 一等实体 + 技能目录（M7 对齐 WeKnora 的 CustomAgent / Skill catalog）。
// Agent = 模型 + 系统提示词 + 启用的技能 + 挂载的外部 MCP；技能 = 工具循环里可调用的能力。
import { api } from "./client"

export interface AgentSkill {
  id: string
  key: string
  name: string
  description: string
  icon: string | null
  category: string
  builtin: boolean
  enabled: boolean
}

export interface AgentDefinition {
  id: string
  key: string
  name: string
  description: string
  icon: string | null
  is_builtin: boolean
  avatar_color: string | null
  system_prompt: string
  model_id: string | null
  enabled_skill_keys: string[]
  skill_package_keys: string[]
  mcp_server_ids: string[]
  created_at: string
  updated_at: string
}

export interface AgentDefinitionIn {
  key: string
  name: string
  description?: string
  icon?: string | null
  avatar_color?: string | null
  system_prompt?: string
  model_id?: string | null
  enabled_skill_keys?: string[]
  skill_package_keys?: string[]
  mcp_server_ids?: string[]
}

export interface AgentDefinitionPatch {
  name?: string
  description?: string
  icon?: string | null
  avatar_color?: string | null
  system_prompt?: string
  model_id?: string | null
  enabled_skill_keys?: string[]
  skill_package_keys?: string[]
  mcp_server_ids?: string[]
}

export const SKILL_CATEGORY_LABELS: Record<string, string> = {
  data: "数据查询",
  analysis: "分析诊断",
  knowledge: "外部知识",
  action: "写入（受控）",
}

export const agentsApi = {
  list: () => api<AgentDefinition[]>("/api/v1/agent/definitions"),
  get: (id: string) => api<AgentDefinition>(`/api/v1/agent/definitions/${id}`),
  skills: () => api<AgentSkill[]>("/api/v1/agent/definitions/skills"),
  create: (payload: AgentDefinitionIn) =>
    api<AgentDefinition>("/api/v1/agent/definitions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  update: (id: string, payload: AgentDefinitionPatch) =>
    api<AgentDefinition>(`/api/v1/agent/definitions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  remove: (id: string) =>
    api<void>(`/api/v1/agent/definitions/${id}`, { method: "DELETE" }),
  // 技能管理：停用后对所有 Agent 都不再注入该工具。
  toggleSkill: (key: string, enabled: boolean) =>
    api<AgentSkill>(`/api/v1/agent/definitions/skills/${key}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }),
}
