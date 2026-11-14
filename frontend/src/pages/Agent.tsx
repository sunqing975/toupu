import { useEffect, useMemo, useState } from "react"
import { Bot, Check, KeyRound, MessageSquare, Plus, Settings2, Sparkles, Trash2, Wrench, X } from "lucide-react"
import { agentsApi, SKILL_CATEGORY_LABELS, type AgentDefinition, type AgentDefinitionIn, type AgentSkill } from "../api/agents"
import { modelsApi, type AgentModel } from "../api/models"
import { chatApi } from "../api/chat"
import { Dialog } from "../components/Dialog"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"
import { useToast } from "../components/Toast"

// —— 对齐 WeKnora：Agent 是一等实体（列表卡片 + 编辑器），技能是可勾选目录。——
// 一个对话页同时容纳：选中的 Agent、其启用的技能、以及基于该 Agent 的会话。

interface ChatMessage {
  role: "user" | "assistant"
  content: string
  agentName?: string | null
  modelName?: string | null
  createdAt: string
}

const SUGGESTIONS = [
  "我当前组合的整体风险如何？",
  "有哪些持仓占比偏高？",
  "帮我拟一份本月的调仓计划草案。",
  "对比一下两个账户的投资表现。",
]

const AVATAR_COLORS = ["#1e40af", "#059669", "#b45309", "#7c3aed", "#be123c", "#0e7490"]

function now(): string {
  return new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
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
}

// 分类分组，供编辑器里按组勾选
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
  const [models, setModels] = useState<AgentModel[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  // 会话
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [typing, setTyping] = useState(false)
  const [question, setQuestion] = useState("")

  // 编辑器
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<AgentDefinition | null>(null)
  const [form, setForm] = useState<AgentForm>(EMPTY_FORM)
  const [busy, setBusy] = useState(false)

  const loadAll = () => {
    setAgents(null)
    setLoadError(null)
    Promise.all([agentsApi.list(), agentsApi.skills(), modelsApi.list()])
      .then(([ags, sks, mds]) => {
        setAgents(ags)
        setSkills(sks)
        setModels(mds)
        setSelectedId((cur) => cur ?? ags.find((a) => a.is_builtin)?.id ?? ags[0]?.id ?? null)
      })
      .catch((e) => setLoadError(e instanceof Error ? e.message : String(e)))
  }

  useEffect(loadAll, [])

  // 切换 Agent 时清空会话（不同人格不共用历史）
  useEffect(() => {
    setMessages([])
  }, [selectedId])

  const selected = useMemo(
    () => (agents ?? []).find((a) => a.id === selectedId) ?? null,
    [agents, selectedId],
  )

  const skillsByCat = useMemo(() => groupSkills(skills ?? []), [skills])

  const openCreate = () => {
    setEditing(null)
    setForm({
      ...EMPTY_FORM,
      avatar_color: AVATAR_COLORS[(agents?.length ?? 0) % AVATAR_COLORS.length],
      // 新建默认给一组常用只读/分析技能，避免开箱零工具
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
        mcp_server_ids: editing ? editing.mcp_server_ids : [],
      }
      if (editing) {
        // PATCH 不含 key（后端不允许改 key）
        const { key: _key, ...patch } = payload
        void _key
        await agentsApi.update(editing.id, patch)
        toast("success", "Agent 已更新")
      } else {
        await agentsApi.create(payload)
        toast("success", "Agent 已创建")
      }
      setEditorOpen(false)
      loadAll()
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
      toast("success", "已删除")
      if (selectedId === a.id) setSelectedId(null)
      loadAll()
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
    setMessages((m) => [...m, { role: "user", content: q, createdAt: now() }])
    setQuestion("")
    setTyping(true)
    try {
      const res = await chatApi.ask({ question: q, agent_id: selected.id })
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: res.answer,
          agentName: res.agent_name,
          modelName: res.model_name,
          createdAt: now(),
        },
      ])
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    } finally {
      setTyping(false)
    }
  }

  const useSuggestion = (text: string) => setQuestion(text)

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h2 className="page__title">助手</h2>
          <p className="page__sub">
            Agent 是一等实体：每个助手绑定模型、系统提示词与一组可调用的技能。模型只在工具循环里使用这些技能，不直接改动账本。
          </p>
        </div>
        <button className="btn btn--primary" onClick={openCreate}>
          <Plus size={14} aria-hidden /> 新建 Agent
        </button>
      </div>

      {loadError && <div className="alert alert--error">{loadError}</div>}

      {/* —— Agent 卡片列表（对齐 WeKnora AgentList）—— */}
      <div className="agent-grid">
        {agents === null ? (
          <Skeleton rows={3} />
        ) : agents.length === 0 ? (
          <EmptyState
            icon={<Bot size={40} aria-hidden />}
            title="还没有 Agent"
            description="创建一个绑定模型与技能的助手。"
            action={<button className="btn btn--primary" onClick={openCreate}>新建 Agent</button>}
          />
        ) : (
          agents.map((a) => (
            <button
              key={a.id}
              type="button"
              className={`agent-card${selectedId === a.id ? " agent-card--active" : ""}`}
              onClick={() => setSelectedId(a.id)}
            >
              <span
                className="agent-card__avatar"
                style={{ backgroundColor: a.avatar_color ?? AVATAR_COLORS[0] }}
                aria-hidden
              >
                <Bot size={20} />
              </span>
              <span className="agent-card__body">
                <span className="agent-card__title">
                  {a.name}
                  {a.is_builtin && <span className="tag">内置</span>}
                </span>
                <span className="agent-card__desc">{a.description || "暂无描述"}</span>
                <span className="agent-card__meta">
                  <Wrench size={12} aria-hidden /> {a.enabled_skill_keys.length} 项技能
                  {a.model_id && <> · 指定模型</>}
                </span>
              </span>
              <span className="agent-card__actions">
                <span
                  role="button"
                  tabIndex={0}
                  className="btn btn--ghost agent-card__edit"
                  onClick={(e) => {
                    e.stopPropagation()
                    openEdit(a)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.stopPropagation()
                      openEdit(a)
                    }
                  }}
                >
                  <Settings2 size={14} aria-hidden />
                </span>
                {!a.is_builtin && (
                  <span
                    role="button"
                    tabIndex={0}
                    className="btn btn--ghost agent-card__edit"
                    onClick={(e) => {
                      e.stopPropagation()
                      removeAgent(a)
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.stopPropagation()
                        removeAgent(a)
                      }
                    }}
                  >
                    <Trash2 size={14} aria-hidden />
                  </span>
                )}
              </span>
            </button>
          ))
        )}
      </div>

      {/* —— 选中 Agent 的能力摘要 —— */}
      {selected && (
        <section className="card">
          <div className="card__head">
            <div>
              <h3 className="card__title">
                <Sparkles size={16} aria-hidden /> {selected.name} · 已启用技能
              </h3>
              <p className="page__sub">
                模型在本会话中只能调用下列技能；{selected.model_id ? "已指定专属模型" : "使用默认模型"}。
              </p>
            </div>
            <button className="btn btn--ghost" onClick={() => openEdit(selected)}>
              <Settings2 size={14} aria-hidden /> 编辑配置
            </button>
          </div>
          <div className="skill-pills">
            {selected.enabled_skill_keys.length === 0 ? (
              <p className="muted">尚未启用任何技能，该 Agent 只能做纯文本问答。</p>
            ) : (
              selected.enabled_skill_keys.map((k) => {
                const sk = (skills ?? []).find((s) => s.key === k)
                return (
                  <span key={k} className="tag" title={sk?.description}>
                    {sk?.name ?? k}
                  </span>
                )
              })
            )}
          </div>
        </section>
      )}

      {/* —— 会话（基于选中 Agent，无 as_of / 模型选择）—— */}
      <section className="card">
        <div className="card__head">
          <div>
            <h3 className="card__title">
              <MessageSquare size={16} aria-hidden /> 分析会话
            </h3>
            <p className="page__sub">
              {selected ? `当前助手：${selected.name}` : "请先在上方选择一个 Agent"} · 模型按需调用已启用技能；写入类操作只生成待审批草稿。
            </p>
          </div>
        </div>

        {messages.length === 0 && !typing ? (
          <div className="chat__empty">
            <Bot size={40} aria-hidden />
            <div>
              <p style={{ color: "var(--color-foreground)", fontWeight: 600 }}>开始一次分析对话</p>
              <p className="page__sub">提出关于持仓、收益、风险或投资计划的问题。</p>
            </div>
            <div className="chips">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="chip" onClick={() => useSuggestion(s)}>
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
                    {m.content}
                  </div>
                  {m.role === "assistant" && (
                    <details className="evidence">
                      <summary>分析依据</summary>
                      <div className="evidence__body">
                        <span>助手：{m.agentName || "—"}</span>
                        <span>模型：{m.modelName || "默认模型"}</span>
                        <span>数据范围：由该助手启用的只读/分析技能按需拉取</span>
                        <span>说明：会话未改动账本；可执行操作需你在网页端确认。</span>
                      </div>
                    </details>
                  )}
                  <span className="msg__meta">{m.createdAt}</span>
                </div>
              </div>
            ))}
            {typing && (
              <div className="msg msg--bot">
                <div className="msg__avatar msg__avatar--bot">
                  <Bot size={16} aria-hidden />
                </div>
                <div className="msg__body">
                  <div className="msg__bubble msg__bubble--bot">
                    <span className="typing"><span /><span /><span /></span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        <div className="chat__composer">
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
          <div className="composer__row" style={{ justifyContent: "flex-end" }}>
            <button className="btn btn--primary" onClick={ask} disabled={typing || !selected}>
              {typing ? "分析中…" : "分析"}
            </button>
          </div>
        </div>
      </section>

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
              <input
                className="input"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="例如：价值投资分析师"
              />
            </label>
            <label className="field">
              <span className="field__label">唯一标识 key</span>
              <input
                className="input"
                value={form.key}
                disabled={!!editing}
                onChange={(e) => setForm((f) => ({ ...f, key: e.target.value }))}
                placeholder="例如：value-analyst"
              />
            </label>
          </div>
          <label className="field">
            <span className="field__label">描述</span>
            <input
              className="input"
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              placeholder="一句话说明这个助手擅长什么"
            />
          </label>
          <label className="field">
            <span className="field__label">系统提示词</span>
            <textarea
              className="textarea"
              rows={4}
              value={form.system_prompt}
              onChange={(e) => setForm((f) => ({ ...f, system_prompt: e.target.value }))}
              placeholder="定义角色、边界与回答风格。留空则使用内置保守提示词。"
            />
          </label>
          <div className="grid-2">
            <label className="field">
              <span className="field__label">模型</span>
              <select
                className="select"
                value={form.model_id}
                onChange={(e) => setForm((f) => ({ ...f, model_id: e.target.value }))}
              >
                <option value="">默认模型（设置里维护）</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name?.trim() || m.name}
                  </option>
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

          {/* 技能目录：按分类分组勾选 */}
          <div className="field">
            <span className="field__label">
              技能（{form.enabled_skill_keys.length} 项已启用）
            </span>
            {skills === null ? (
              <Skeleton rows={3} />
            ) : (
              <div className="skill-picker">
                {Object.entries(skillsByCat).map(([cat, items]) => (
                  <div key={cat} className="skill-group">
                    <div className="skill-group__title">
                      {SKILL_CATEGORY_LABELS[cat] ?? cat}
                    </div>
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

          <div className="dialog__foot">
            <button className="btn btn--ghost" onClick={() => setEditorOpen(false)}>
              <X size={14} aria-hidden /> 取消
            </button>
            <button className="btn btn--primary" onClick={saveAgent} disabled={busy}>
              {busy ? "保存中…" : "保存"}
            </button>
          </div>
        </div>
      </Dialog>

      {/* 模型配置的入口提示：模型管理已迁入设置 */}
      {models.length === 0 && (
        <div className="alert alert--info" style={{ marginTop: 16 }}>
          <KeyRound size={14} aria-hidden /> 还没有配置模型。请到「设置 → 模型配置」添加 OpenAI 兼容端点后，助手才能进行分析。
        </div>
      )}
    </div>
  )
}
