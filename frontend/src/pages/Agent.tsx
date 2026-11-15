import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import {
  Bot,
  Check,
  KeyRound,
  MessageSquare,
  Plus,
  Send,
  Settings2,
  Trash2,
  Archive,
  ArchiveRestore,
  X,
} from "lucide-react"
import {
  agentsApi,
  SKILL_CATEGORY_LABELS,
  type AgentDefinition,
  type AgentDefinitionIn,
  type AgentSkill,
} from "../api/agents"
import { mcpServersApi, type McpServer } from "../api/mcpServers"
import { modelsApi, type AgentModel } from "../api/models"
import { chatSession, type ChatMessage } from "../api/chatSession"
import { conversationsApi, type Conversation, type ConversationMessage } from "../api/conversations"
import { Dialog } from "../components/Dialog"
import { Skeleton } from "../components/Skeleton"
import { useToast } from "../components/Toast"

// 用户反馈 (m05823)：正经的对话框 = 左侧历史会话 + 右侧消息区（顶部标题栏/模型选择 + 底部输入）。
// 历史会话存库、可回看续聊；模型可在对话框顶部直接切换。


const SUGGESTIONS = [
  "我当前组合的整体风险如何？",
  "有哪些持仓占比偏高？",
  "帮我拟一份本月的调仓计划草案。",
  "对比一下两个账户的投资表现。",
]

const AVATAR_COLORS = ["#1e40af", "#059669", "#b45309", "#7c3aed", "#be123c", "#0e7490"]

function fmtTime(v: string): string {
  return new Date(v).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
}

interface AgentForm {
  key: string
  name: string
  description: string
  icon: string
  avatar_color: string
  system_prompt: string
  model_id: string
  enabled_skill_keys: string[]
  skill_package_keys: string[]
  mcp_server_ids: string[]
}

const EMPTY_FORM: AgentForm = {
  key: "",
  name: "",
  description: "",
  icon: "Sparkles",
  avatar_color: AVATAR_COLORS[3],
  system_prompt: "",
  model_id: "",
  enabled_skill_keys: [],
  skill_package_keys: [],
  mcp_server_ids: [],
}

function groupSkills(skills: AgentSkill[]): Record<string, AgentSkill[]> {
  const out: Record<string, AgentSkill[]> = {}
  for (const s of skills) {
    ;(out[s.category] ??= []).push(s)
  }
  return out
}

export function Agent() {
  const toast = useToast()
  // 数据
  const [agents, setAgents] = useState<AgentDefinition[] | null>(null)
  const [skills, setSkills] = useState<AgentSkill[] | null>(null)
  const [servers, setServers] = useState<McpServer[]>([])
  const [models, setModels] = useState<AgentModel[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)


  // 历史会话
  const [conversations, setConversations] = useState<Conversation[] | null>(null)
  const [showArchived, setShowArchived] = useState(false)
  const { activeConvId, messages, typing, question, modelId, selectedId } = useSyncExternalStore(
    chatSession.subscribe, chatSession.getSnapshot)
  const setActiveConvId = (value: string | null) => chatSession.set("activeConvId", value)
  const setMessages = (value: ChatMessage[]) => chatSession.set("messages", value)
  const setQuestion = (value: string) => chatSession.set("question", value)
  const setModelId = (value: string) => chatSession.set("modelId", value)
  const setSelectedId = (value: string | null | ((old: string | null) => string | null)) => chatSession.set("selectedId", value)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  // 编辑器
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<AgentDefinition | null>(null)
  const [form, setForm] = useState<AgentForm>(EMPTY_FORM)
  const [busy, setBusy] = useState(false)

  const loadAgents = () => {
    setAgents(null)
    setLoadError(null)
    Promise.all([agentsApi.list(), agentsApi.skills(), modelsApi.list(), mcpServersApi.list()])
      .then(([ags, sks, mds, srvs]) => {
        setServers(srvs)
        setAgents(ags)
        setSkills(sks)
        setModels(mds)
        setSelectedId((cur) => cur ?? ags.find((a) => a.is_builtin)?.id ?? ags[0]?.id ?? null)
      })
      .catch((e) => setLoadError(e instanceof Error ? e.message : String(e)))
  }

  const loadConversations = () => {
    conversationsApi
      .list(showArchived)
      .then(setConversations)
      .catch(() => setConversations([]))
  }

  useEffect(() => {
    loadAgents()
  }, [])

  useEffect(() => {
    loadConversations()
  }, [showArchived, typing])

  const openConversation = async (id: string) => {
    if (chatSession.getSnapshot().typing) return
    if (activeConvId === id && messages.length) return
    setActiveConvId(id)
    setMessages([])
    try {
      const detail = await conversationsApi.get(id)
      if (chatSession.getSnapshot().activeConvId !== id || chatSession.getSnapshot().typing) return
      setMessages(
        detail.messages.map((m: ConversationMessage) => ({
          role: m.role,
          content: m.content,
          agentName: m.agent_name,
          modelName: m.model_name,
          createdAt: fmtTime(m.created_at),
        })),
      )
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    }
  }

  const newConversation = () => {
    if (chatSession.getSnapshot().typing) return
    setActiveConvId(null)
    setMessages([])
    setQuestion("")
  }

  const archiveConversation = async (c: Conversation) => {
    try {
      if (c.archived_at) await conversationsApi.restore(c.id)
      else await conversationsApi.archive(c.id)
      if (activeConvId === c.id) newConversation()
      loadConversations()
      toast("success", c.archived_at ? "会话已恢复" : "会话已归档，历史消息保留")
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, typing])

  const selected = useMemo(
    () => (agents ?? []).find((a) => a.id === selectedId) ?? null,
    [agents, selectedId],
  )

  const skillsByCat = useMemo(() => groupSkills((skills ?? []).filter(s => s.category !== "instruction" && s.category !== "knowledge")), [skills])

  const openCreate = () => {
    setEditing(null)
    setForm({
      ...EMPTY_FORM,
      avatar_color: AVATAR_COLORS[(agents?.length ?? 0) % AVATAR_COLORS.length],
      enabled_skill_keys: (skills ?? [])
        .filter((s) => s.category === "data" || s.category === "analysis")
        .map((s) => s.key),
    })
    setEditorOpen(true)
  }

  const openEdit = (a: AgentDefinition) => {
    setEditing(a)
    setForm({
      key: a.key,
      name: a.name,
      description: a.description,
      icon: a.icon ?? "Sparkles",
      avatar_color: a.avatar_color ?? AVATAR_COLORS[0],
      system_prompt: a.system_prompt,
      model_id: a.model_id ?? "",
      enabled_skill_keys: [...a.enabled_skill_keys],
      skill_package_keys: [...(a.skill_package_keys ?? [])],
      mcp_server_ids: [...a.mcp_server_ids],
    })
    setEditorOpen(true)
  }

  const toggleSkill = (key: string) => {
    setForm((f) => {
      const has = f.enabled_skill_keys.includes(key)
      return {
        ...f,
        enabled_skill_keys: has
          ? f.enabled_skill_keys.filter((k) => k !== key)
          : [...f.enabled_skill_keys, key],
      }
    })
  }

  const saveAgent = async () => {
    if (!form.name.trim()) {
      toast("error", "请填写 Agent 名称")
      return
    }
    if (!editing && !form.key.trim()) {
      toast("error", "请填写唯一标识 key")
      return
    }
    setBusy(true)
    try {
      const payload: AgentDefinitionIn = {
        key: form.key.trim(),
        name: form.name.trim(),
        description: form.description.trim(),
        icon: form.icon,
        avatar_color: form.avatar_color,
        system_prompt: form.system_prompt,
        model_id: form.model_id || null,
        enabled_skill_keys: form.enabled_skill_keys,
        mcp_server_ids: form.mcp_server_ids,
        skill_package_keys: form.skill_package_keys,
      }
      if (editing) {
        const { key: _key, ...patch } = payload
        void _key
        await agentsApi.update(editing.id, patch)
        toast("success", "Agent 已更新")
      } else {
        await agentsApi.create(payload)
        toast("success", "Agent 已创建")
      }
      setEditorOpen(false)
      loadAgents()
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const removeAgent = async (a: AgentDefinition) => {
    if (a.is_builtin) return
    if (!confirm(`确定删除 Agent「${a.name}」？此操作不可恢复。`)) return
    try {
      await agentsApi.remove(a.id)
      if (selectedId === a.id) setSelectedId(null)
      loadAgents()
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    }
  }

  const ask = async () => {
    if (!question.trim()) {
      toast("error", "请输入问题")
      return
    }
    if (!selected) {
      toast("error", "请先选择一个 Agent")
      return
    }
    if (models.length === 0) {
      toast("error", "请先在「设置 → 模型配置」中添加一个模型")
      return
    }
    const q = question.trim()
    await chatSession.start({ question: q, agent_id: selected.id,
      conversation_id: activeConvId, model_id: modelId || null })
  }

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h2 className="page__title">助手</h2>
          <p className="page__sub">
            助手绑定模型与可用工具，专业工作流程在技能页通过 SKILL.md 管理。历史会话自动保存，可回看、续聊或归档。
          </p>
        </div>
        <button className="btn btn--primary" onClick={openCreate}>
          <Plus size={14} aria-hidden /> 新建 Agent
        </button>
      </div>

      {loadError && <div className="alert alert--error">{loadError}</div>}

      {/* —— Agent 选择器（紧凑，不再是主视觉）—— */}
      <div className="agent-strip">
        {agents === null ? (
          <Skeleton rows={1} />
        ) : (
          agents.map((a) => (
            <button
              key={a.id}
              type="button"
              className={`agent-chip${selectedId === a.id ? " agent-chip--active" : ""}`}
              onClick={() => setSelectedId(a.id)}
            >
              <span
                className="agent-chip__dot"
                style={{ backgroundColor: a.avatar_color ?? AVATAR_COLORS[0] }}
                aria-hidden
              />
              {a.name}
              {a.is_builtin && <span className="tag">内置</span>}
              <span
                role="button"
                tabIndex={0}
                className="agent-chip__edit"
                aria-label={`编辑 ${a.name}`}
                onClick={(e) => { e.stopPropagation(); openEdit(a) }}
                onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); openEdit(a) } }}
              >
                <Settings2 size={12} aria-hidden />
              </span>
              {!a.is_builtin && (
                <span
                  role="button"
                  tabIndex={0}
                  className="agent-chip__edit"
                  aria-label={`删除 ${a.name}`}
                  onClick={(e) => { e.stopPropagation(); removeAgent(a) }}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); removeAgent(a) } }}
                >
                  <Trash2 size={12} aria-hidden />
                </span>
              )}
            </button>
          ))
        )}
      </div>

      {models.length === 0 && (
        <div className="alert alert--info" style={{ marginBottom: 16 }}>
          <KeyRound size={14} aria-hidden /> 还没有配置模型。请到「设置 → 模型配置」添加 OpenAI 兼容端点后，助手才能进行分析。
        </div>
      )}

      {/* —— 正经对话框：左历史会话 + 右消息区 —— */}
      <div className="chat-workspace">
        <aside className="chat-sidebar">
          <div className="chat-sidebar__head">
            <button className="btn btn--ghost" onClick={() => setShowArchived(!showArchived)}>
              <MessageSquare size={14} aria-hidden /> {showArchived ? "已归档 · 返回历史" : "历史会话 · 查看归档"}
            </button>
            <button className="btn btn--ghost btn--icon" onClick={newConversation} title="新建会话" aria-label="新建会话">
              <Plus size={14} aria-hidden />
            </button>
          </div>
          {conversations === null ? (
            <Skeleton rows={3} />
          ) : conversations.length === 0 ? (
            <p className="chat-sidebar__empty muted">暂无历史会话</p>
          ) : (
            <div className="chat-sidebar__list">
              {conversations.map((c) => (
                <div
                  key={c.id}
                  className={`chat-session${activeConvId === c.id ? " chat-session--active" : ""}`}
                  onClick={() => openConversation(c.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === "Enter") openConversation(c.id) }}
                >
                  <span className="chat-session__title">{c.title || "未命名会话"}</span>
                  <span className="chat-session__meta">
                    {c.message_count} 条 · {fmtTime(c.updated_at)}
                  </span>
                  <button
                    className="btn btn--ghost btn--icon chat-session__del"
                    aria-label={c.archived_at ? "恢复会话" : "归档会话"}
                    title={c.archived_at ? "恢复会话" : "归档，保留历史消息"}
                    onClick={(e) => { e.stopPropagation(); archiveConversation(c) }}
                  >
                    {c.archived_at ? <ArchiveRestore size={12} aria-hidden /> : <Archive size={12} aria-hidden />}
                  </button>
                </div>
              ))}
            </div>
          )}
        </aside>

        <section className="chat-panel">
          {/* 标题栏：Agent 名 + 已启用技能 + 模型下拉（对话框内直接换模型） */}
          <header className="chat-panel__head">
            <div className="chat-panel__who">
              <Bot size={18} aria-hidden />
              <div>
                <strong>{selected ? selected.name : "请选择助手"}</strong>
                <span className="muted">
                  {selected ? `${selected.enabled_skill_keys.length} 项工具 · 写入仅生成草稿` : "—"}
                </span>
              </div>
            </div>
            <label className="chat-panel__model">
              <span className="muted">模型</span>
              <select
                className="select"
                value={modelId}
                onChange={(e) => setModelId(e.target.value)}
                title="本会话临时使用的模型（覆盖助手默认）"
              >
                <option value="">跟随助手 / 默认</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name?.trim() || m.name}
                  </option>
                ))}
              </select>
            </label>
          </header>

          {/* 消息区 */}
          <div className="chat-panel__body">
            {messages.length === 0 && !typing ? (
              <div className="chat__empty">
                <Bot size={40} aria-hidden />
                <div>
                  <p style={{ color: "var(--color-foreground)", fontWeight: 600 }}>开始一次分析对话</p>
                  <p className="page__sub">选择助手，按需提问或处理程序内的操作。对话历史会自动保存。</p>
                </div>
                <div className="chips">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} className="chip" onClick={() => setQuestion(s)}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="chat__messages">
                {messages.map((m, i) => (
                  <div key={i} className={`msg ${m.role === "user" ? "msg--user" : "msg--bot"}`}>
                    <div className={`msg__avatar ${m.role === "user" ? "" : "msg__avatar--bot"}`}>
                      {m.role === "user" ? "你" : <Bot size={16} aria-hidden />}
                    </div>
                    <div className="msg__body">
                      <div className={`msg__bubble ${m.role === "user" ? "msg__bubble--user" : "msg__bubble--bot"}`}>
                        {m.reasoning && <details className="chat-reasoning" open={typing && i === messages.length - 1}>
                          <summary>思考 · 模型提供</summary>
                          <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>{m.reasoning}</ReactMarkdown></div>
                        </details>}
                        {!!m.tools?.length && <div className="chat-tools" aria-label="工具调用">
                          {m.tools.map(t => <details key={t.id}><summary>{t.done ? "✓" : "◌"} <code>{t.name}</code> · {t.done ? "已返回" : "调用中"}</summary><pre>参数：{t.arguments}</pre>{t.approvalId && t.approved === undefined && !t.done && <div><p>该操作需要你的确认。请核对工具名称和上述参数；确认后由服务端执行，不代表资金交易入账。</p><button type="button" onClick={() => void chatSession.decide(t.approvalId!, true).catch(e => alert(String(e)))}>确认执行</button> <button type="button" onClick={() => void chatSession.decide(t.approvalId!, false).catch(e => alert(String(e)))}>拒绝</button></div>}{t.approved !== undefined && <p>{t.approved ? "用户已确认" : "用户已拒绝"}</p>}{t.result && <pre>返回（最多 12000 字符）：{t.result}</pre>}</details>)}
                        </div>}
                        <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>{m.content}</ReactMarkdown></div>
                        {m.status && <p className="muted" role="status">{m.status}</p>}
                      </div>
                      {m.role === "assistant" && (
                        <details className="evidence">
                          <summary>分析依据</summary>
                          <div className="evidence__body">
                            <span>助手：{m.agentName || "—"}</span>
                            <span>模型：{m.modelName || "默认模型"}</span>
                            <span>数据范围：由该助手启用的只读/分析工具按需拉取</span>
                            <span>说明：建议仅供参考，计划和草稿不改变持仓；实际交易由你自行操作后核实记账。</span>
                          </div>
                        </details>
                      )}
                      <span className="msg__meta">{m.createdAt}</span>
                    </div>
                  </div>
                ))}
                {typing && !messages.length && (
                  <div className="msg msg--bot">
                    <div className="msg__avatar msg__avatar--bot"><Bot size={16} aria-hidden /></div>
                    <div className="msg__body">
                      <div className="msg__bubble msg__bubble--bot">
                        <span className="typing"><span /><span /><span /></span>
                      </div>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>
            )}
          </div>

          {/* 输入区 */}
          <div className="chat__composer">
            {typing && <button className="btn btn--secondary" onClick={() => chatSession.stop()}>停止生成</button>}
            <textarea
              className="input"
              rows={3}
              value={question}
              placeholder="例如：我当前组合的整体风险如何？有哪些持仓占比偏高？"
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault()
                  ask()
                }
              }}
            />
            <div className="composer__row" style={{ justifyContent: "space-between" }}>
              <span className="muted" style={{ fontSize: 12 }}>Ctrl/⌘ + Enter 发送 · 历史自动保存到左侧</span>
              <button className="btn btn--primary" onClick={ask} disabled={typing || !selected}>
                <Send size={14} aria-hidden /> {typing ? "分析中…" : "发送"}
              </button>
            </div>
          </div>
        </section>
      </div>

      {/* —— Agent 编辑器（对齐 WeKnora AgentEditorModal）—— */}
      <Dialog
        open={editorOpen}
        title={editing ? `编辑 Agent · ${editing.name}` : "新建 Agent"}
        onClose={() => setEditorOpen(false)}
      >
        <div className="stack">
          <div className="grid-2">
            <label className="field">
              <span className="field__label">名称</span>
              <input className="input" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="例如：价值投资分析师" />
            </label>
            <label className="field">
              <span className="field__label">唯一标识 key</span>
              <input className="input" value={form.key} disabled={!!editing} onChange={(e) => setForm((f) => ({ ...f, key: e.target.value }))} placeholder="例如：value-analyst" />
            </label>
          </div>
          <label className="field">
            <span className="field__label">描述</span>
            <input className="input" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} placeholder="一句话说明这个助手擅长什么" />
          </label>
          <label className="field">
            <span className="field__label">系统提示词</span>
            <textarea className="textarea" rows={4} value={form.system_prompt} onChange={(e) => setForm((f) => ({ ...f, system_prompt: e.target.value }))} placeholder="定义角色、边界与回答风格。留空则使用内置保守提示词。" />
          </label>
          <div className="grid-2">
            <label className="field">
              <span className="field__label">模型</span>
              <select className="select" value={form.model_id} onChange={(e) => setForm((f) => ({ ...f, model_id: e.target.value }))}>
                <option value="">默认模型（设置里维护）</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>{m.display_name?.trim() || m.name}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field__label">头像颜色</span>
              <div className="color-row">
                {AVATAR_COLORS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    className={`color-dot${form.avatar_color === c ? " color-dot--active" : ""}`}
                    style={{ backgroundColor: c }}
                    aria-label={`颜色 ${c}`}
                    onClick={() => setForm((f) => ({ ...f, avatar_color: c }))}
                  >
                    {form.avatar_color === c && <Check size={12} />}
                  </button>
                ))}
              </div>
            </label>
          </div>

          <div className="field">
            <span className="field__label">内置工具（{(skills ?? []).filter(s => s.category !== "instruction" && s.category !== "knowledge" && form.enabled_skill_keys.includes(s.key)).length} 项已启用）</span>
            {skills === null ? (
              <Skeleton rows={3} />
            ) : (
              <div className="skill-picker">
                {Object.entries(skillsByCat).map(([cat, items]) => (
                  <div key={cat} className="skill-group">
                    <div className="skill-group__title">{SKILL_CATEGORY_LABELS[cat] ?? cat}</div>
                    <div className="skill-group__items">
                      {items.map((s) => {
                        const on = form.enabled_skill_keys.includes(s.key)
                        return (
                          <button
                            key={s.key}
                            type="button"
                            className={`skill-item${on ? " skill-item--on" : ""}`}
                            onClick={() => toggleSkill(s.key)}
                            title={s.description}
                          >
                            {on ? <Check size={13} aria-hidden /> : <Plus size={13} aria-hidden />}
                            <span>{s.name}</span>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {([
            { field: "skill_package_keys" as const, label: "技能目录", items: (skills ?? []).filter(s => s.category === "instruction").map(s => ({ key: s.key, name: s.name, enabled: s.enabled })) },
          ]).map(({ field, label, items }) => (
            <div className="field" key={field}>
              <span className="field__label">{label}（{form[field].length} 项已挂载）</span>
              <div className="skill-group__items">
                {items.map(item => <label key={item.key} className="skill-item">
                  <input type="checkbox" checked={form[field].includes(item.key)} onChange={() => setForm(f => ({ ...f, [field]: f[field].includes(item.key) ? f[field].filter(k => k !== item.key) : [...f[field], item.key] }))} />
                  {item.name}{!item.enabled && "（全局已停用）"}
                </label>)}
                {!items.length && <span className="text-muted">尚未配置，请到设置中添加。</span>}
              </div>
            </div>
          ))}
          <fieldset className="field" style={{ border: "none", padding: 0, margin: 0 }}>
            <legend className="field__label">MCP（{form.mcp_server_ids.length} 项已挂载）</legend>
            <p className="text-muted">选择此 Agent 可访问的 MCP 服务。资源读取与工具调用统一由 MCP 提供，服务在设置中管理。</p>
            <div className="skill-group__items">
              {servers.map(server => <label key={server.id} className="skill-item">
                <input type="checkbox" checked={form.mcp_server_ids.includes(server.id)} onChange={() => setForm(f => ({ ...f, mcp_server_ids: f.mcp_server_ids.includes(server.id) ? f.mcp_server_ids.filter(id => id !== server.id) : [...f.mcp_server_ids, server.id] }))} />
                {server.name}{!server.enabled && "（全局已停用）"}
              </label>)}
              {!servers.length && <span className="text-muted">尚未配置 MCP 服务，请到设置 → 外部 MCP 中添加。</span>}
            </div>
            {(skills ?? []).filter(s => s.category === "knowledge").map(skill => <label key={skill.key} className="skill-item" title={skill.description}>
              <input type="checkbox" checked={form.enabled_skill_keys.includes(skill.key)} onChange={() => toggleSkill(skill.key)} />
              允许读取 MCP 资源{!skill.enabled && "（全局已停用）"}
            </label>)}
          </fieldset>
          <div className="dialog__foot">
            <button className="btn btn--ghost" onClick={() => setEditorOpen(false)}><X size={14} aria-hidden /> 取消</button>
            <button className="btn btn--primary" onClick={saveAgent} disabled={busy}>{busy ? "保存中…" : "保存"}</button>
          </div>
        </div>
      </Dialog>
    </div>
  )
}
