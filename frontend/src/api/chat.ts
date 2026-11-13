// Agent 分析/对话会话 API（M7 §专用会话）：模型只看到只读数据快照 + 问题。
import { api } from "./client"

export interface ChatRequest {
  question: string
  as_of?: string | null
  model_id?: string | null
}

export interface ChatResponse {
  answer: string
  model_id: string | null
  model_name: string | null
  as_of: string
}

export const chatApi = {
  ask: (payload: ChatRequest) =>
    api<ChatResponse>("/api/v1/agent/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
}
