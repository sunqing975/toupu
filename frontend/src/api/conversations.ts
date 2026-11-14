// Agent 历史会话 API（用户反馈 m05823：历史会话也要存）。
// 会话列表 / 详情（含消息）/ 改名 / 删除；/chat 会自动把每轮问答落库。
import { api } from "./client"

export interface ConversationMessage {
  id: string
  role: "user" | "assistant"
  content: string
  agent_name: string | null
  model_name: string | null
  model_id: string | null
  created_at: string
}

export interface Conversation {
  id: string
  title: string
  agent_id: string | null
  model_id: string | null
  created_at: string
  updated_at: string
  message_count: number
}

export interface ConversationDetail extends Conversation {
  messages: ConversationMessage[]
}

export const conversationsApi = {
  list: () => api<Conversation[]>("/api/v1/agent/conversations"),
  get: (id: string) => api<ConversationDetail>(`/api/v1/agent/conversations/${id}`),
  create: () =>
    api<Conversation>("/api/v1/agent/conversations", { method: "POST" }),
  rename: (id: string, title: string) =>
    api<Conversation>(`/api/v1/agent/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  remove: (id: string) =>
    api<void>(`/api/v1/agent/conversations/${id}`, { method: "DELETE" }),
}
