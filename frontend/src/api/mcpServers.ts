// 外部 MCP 服务挂载管理 API（M7 Phase 4）。
// 管理员登记 stdio / http 型外部 MCP，专用会话会只读地拉取其资源注入分析提示词。
import { api } from "./client"

export type McpTransport = "stdio" | "http"

export interface McpServer {
  id: string
  name: string
  transport: McpTransport
  command: string | null
  url: string | null
  config: Record<string, unknown> | null
  enabled: boolean
  created_at: string
}

export interface McpServerIn {
  name: string
  transport: McpTransport
  command?: string | null
  url?: string | null
  config?: Record<string, unknown> | null
  enabled?: boolean
}

export interface McpTestResult {
  ok: boolean
  detail: string
}

export const mcpServersApi = {
  list: () => api<McpServer[]>("/api/v1/agent/mcp-servers"),
  create: (payload: McpServerIn) =>
    api<McpServer>("/api/v1/agent/mcp-servers", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  update: (id: string, payload: Partial<McpServerIn>) =>
    api<McpServer>(`/api/v1/agent/mcp-servers/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  remove: (id: string) =>
    api<void>(`/api/v1/agent/mcp-servers/${id}`, { method: "DELETE" }),
  test: (id: string) =>
    api<McpTestResult>(`/api/v1/agent/mcp-servers/${id}/test`, {
      method: "POST",
    }),
}
