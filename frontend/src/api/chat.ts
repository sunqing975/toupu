// Agent 分析/对话会话 API（M7 对齐 WeKnora）。
// 模型按指定 Agent 的 system_prompt + 启用技能在工具循环里工作。
// 用户反馈 m05823：支持会话续聊（conversation_id）+ 对话框临时换模型（model_id）。
import { api } from "./client"

export interface ChatRequest {
  question: string
  agent_id?: string | null
  conversation_id?: string | null
  model_id?: string | null
  request_key?: string
}

export interface ChatResponse {
  answer: string
  agent_id: string | null
  agent_name: string | null
  model_id: string | null
  model_name: string | null
  conversation_id: string
  title: string
}

export type ChatEvent = {
  type: "meta" | "content" | "reasoning" | "tool_start" | "tool_end" | "done" | "error" | "approval_required" | "approval_decided"
  run_id?: string; seq?: number; approval_id?: string; approved?: boolean
  text?: string; id?: string; name?: string; message?: string; arguments?: string; result?: string
} & Partial<ChatResponse>

export const chatApi = {
  stream: async (payload: ChatRequest, onEvent: (event: ChatEvent) => void, signal: AbortSignal) => {
    const response = await fetch("/api/v1/agent/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload), signal,
    })
    await consume(response, onEvent, signal)
  },
  resume: async (runId: string, onEvent: (event: ChatEvent) => void, signal: AbortSignal, after = 0) => {
    await consume(await fetch(`/api/v1/agent/runs/${runId}/events?after=${after}`, { signal }), onEvent, signal)
  },
  cancel: (id: string) => api(`/api/v1/agent/runs/${id}/cancel`, { method: "POST" }),
  decide: (runId: string, id: string, approve: boolean) => api(`/api/v1/agent/runs/${runId}/approvals/${id}`, { method: "POST", body: JSON.stringify({ approve }) }),
  run: (id: string) => api<{ id: string; status: string; question: string; meta: ChatResponse }>(`/api/v1/agent/runs/${id}`),
}

async function consume(response: Response, onEvent: (event: ChatEvent) => void, signal: AbortSignal) {
    if (!response.ok) throw new Error("对话请求失败（" + response.status + "）")
    if (!response.body) throw new Error("浏览器不支持流式响应")
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = "", done = false
    try {
      while (!signal.aborted) {
        const part = await reader.read()
        buffer += decoder.decode(part.value, { stream: !part.done })
        buffer = buffer.replace(/\r\n/g, "\n")
        let boundary: number
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2)
          const data = frame.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n")
          if (!data) continue
          const event: ChatEvent = JSON.parse(data)
          if (event.type === "error" || event.type === "done") done = true
          onEvent(event)
        }
        if (part.done) break
      }
      if (!done) throw new Error("连接已中断，回答可能不完整")
    } finally { await reader.cancel().catch(() => {}); reader.releaseLock() }
}
