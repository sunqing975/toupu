// Agent 分析/对话会话 API（M7 对齐 WeKnora）：模型按指定 Agent 的
// system_prompt + 启用技能在工具循环里工作；不再有 as_of / model_id 请求参数。
import { api } from "./client"

export interface ChatRequest {
  question: string
  agent_id?: string | null
}

export interface ChatResponse {
  answer: string
  agent_id: string | null
  agent_name: string | null
  model_id: string | null
  model_name: string | null
}

export const chatApi = {
  ask: (payload: ChatRequest) =>
    api<ChatResponse>("/api/v1/agent/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
}
