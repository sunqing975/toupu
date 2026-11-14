// Agent 分析/对话会话 API（M7 对齐 WeKnora）。
// 模型按指定 Agent 的 system_prompt + 启用技能在工具循环里工作。
// 用户反馈 m05823：支持会话续聊（conversation_id）+ 对话框临时换模型（model_id）。
import { api } from "./client"

export interface ChatRequest {
  question: string
  agent_id?: string | null
  conversation_id?: string | null
  model_id?: string | null
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

export const chatApi = {
  ask: (payload: ChatRequest) =>
    api<ChatResponse>("/api/v1/agent/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
}
