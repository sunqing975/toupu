import { chatApi, type ChatRequest } from "./chat"

export interface ChatMessage {
  role: "user" | "assistant"
  content: string
  agentName?: string | null
  modelName?: string | null
  createdAt: string
  reasoning?: string
  tools?: { id: string; name: string; done: boolean; arguments?: string; result?: string; approvalId?: string; approved?: boolean }[]
  status?: string
}

// Application-owned state: route unmount only removes subscribers, never cancels work.
export function createChatSession(stream = chatApi.stream) {
  const storage = {
    get: () => { try { return window.localStorage.getItem("toupu.activeRun") } catch { return null } },
    set: (id: string) => { try { window.localStorage.setItem("toupu.activeRun", id) } catch { /* storage disabled */ } },
    clear: () => { try { window.localStorage.removeItem("toupu.activeRun") } catch { /* storage disabled */ } },
  }
  let state = { messages: [] as ChatMessage[], activeConvId: null as string | null,
    selectedId: null as string | null, modelId: "", question: "", typing: false }
  let controller: AbortController | null = null
  let runId: string | null = null
  const listeners = new Set<() => void>()
  const publish = (patch: Partial<typeof state>) => {
    state = { ...state, ...patch }
    listeners.forEach(listener => listener())
  }
  const update = (fn: (message: ChatMessage) => ChatMessage) => publish({
    messages: state.messages.map((m, i) => i === state.messages.length - 1 ? fn(m) : m),
  })
  return {
    getSnapshot: () => state,
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } },
    set<K extends keyof typeof state>(key: K, value: typeof state[K] | ((old: typeof state[K]) => typeof state[K])) {
      publish({ [key]: typeof value === "function" ? value(state[key]) : value })
    },
    stop: () => {
      if (runId) void chatApi.cancel(runId).catch(() => update(m => ({ ...m, status: "取消请求失败，服务端可能仍在运行，请重试" })))
      else controller?.abort()
    },
    decide: async (id: string, approve: boolean) => {
      if (!runId) return
      await chatApi.decide(runId, id, approve)
    },
    async restore() {
      const saved = storage.get()
      if (!saved || controller) return
      try {
        const run = await chatApi.run(saved)
        publish({ activeConvId: run.meta.conversation_id, selectedId: run.meta.agent_id, modelId: run.meta.model_id ?? "", messages: [] })
        await this.start({ question: run.question }, saved)
      } catch { storage.clear() }
    },
    async start(payload: ChatRequest, resumeId?: string) {
      if (controller) return
      const current = new AbortController()
      controller = current
      runId = resumeId ?? null
      publish({ typing: true, question: "", messages: [...state.messages,
        { role: "user", content: payload.question, createdAt: "现在" },
        { role: "assistant", content: "", createdAt: "现在", status: "等待模型响应…", tools: [] }] })
      let lastSeq = 0
      let terminal = false
      try {
        const receive = (event: import("./chat").ChatEvent) => {
          if (event.seq && event.seq <= lastSeq) return
          lastSeq = event.seq ?? lastSeq
          if (event.type === "error") {
            terminal = true
            storage.clear()
            update(m => ({ ...m, status: event.message ?? "任务中断" }))
          } else if (event.type === "meta") {
            runId = event.run_id ?? runId
            if (runId) storage.set(runId)
            publish({ activeConvId: event.conversation_id ?? null })
            update(m => ({ ...m, agentName: event.agent_name, modelName: event.model_name }))
          } else if (event.type === "content") {
            update(m => ({ ...m, content: m.content + (event.text ?? ""), status: "正在回复…" }))
          } else if (event.type === "reasoning") {
            update(m => ({ ...m, reasoning: (m.reasoning ?? "") + (event.text ?? ""), status: "正在思考…" }))
          } else if (event.type === "tool_start") {
            update(m => ({ ...m, status: "正在调用工具…", tools: [...(m.tools ?? []),
              { id: event.id!, name: event.name!, done: false, arguments: event.arguments }] }))
          } else if (event.type === "tool_end") {
            update(m => ({ ...m, status: "等待模型继续…", tools: m.tools?.map(t =>
              t.id === event.id ? { ...t, done: true, result: event.result } : t) }))
          } else if (event.type === "approval_required") {
            update(m => ({ ...m, status: "等待你的审批，确认前不会执行", tools: m.tools?.map(t => t.id === event.id ? { ...t, approvalId: event.approval_id } : t) }))
          } else if (event.type === "approval_decided") {
            update(m => ({ ...m, status: "审批已记录", tools: m.tools?.map(t => t.approvalId === event.approval_id ? { ...t, approved: event.approved } : t) }))
          } else if (event.type === "done") {
            terminal = true
            storage.clear()
            update(m => ({ ...m, status: undefined }))
          }
        }
        let reconnect = !!resumeId
        const request = { ...payload, request_key: payload.request_key ?? crypto.randomUUID() }
        for (let attempt = 0; ; attempt++) {
          try {
            if (reconnect && runId) await chatApi.resume(runId, receive, current.signal, lastSeq)
            else await stream(request, receive, current.signal)
            break
          } catch (error) {
            if (current.signal.aborted || terminal || !runId || attempt >= 4) throw error
            reconnect = true
            update(m => ({ ...m, status: "连接中断，正在恢复服务端任务…" }))
            await new Promise(resolve => setTimeout(resolve, Math.min(500 * 2 ** attempt, 4000)))
          }
        }
      } catch (error) {
        update(m => ({ ...m, status: current.signal.aborted ? "已停止，当前回答可能不完整" :
          error instanceof Error ? error.message : String(error) }))
      } finally {
        controller = null
        publish({ typing: false })
      }
    },
  }
}

export const chatSession = createChatSession()
if (typeof window !== "undefined") void chatSession.restore()
