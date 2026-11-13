import { useEffect, useState } from "react"
import { Bot, Plus, Settings2, Trash2 } from "lucide-react"
import { modelsApi, type AgentModel } from "../api/models"
import { chatApi } from "../api/chat"
import { Dialog } from "../components/Dialog"
import { Skeleton } from "../components/Skeleton"
import { useToast } from "../components/Toast"

interface ModelForm {
  name: string
  display_name: string
  base_url: string
  model: string
  api_key: string
  is_default: boolean
}

const EMPTY_FORM: ModelForm = {
  name: "",
  display_name: "",
  base_url: "https://api.openai.com/v1",
  model: "",
  api_key: "",
  is_default: false,
}

interface ChatMessage {
  role: "user" | "assistant"
  content: string
  modelName?: string | null
  asOf?: string | null
  createdAt: string
}

const SUGGESTIONS = [
  "我当前组合的整体风险如何？",
  "有哪些持仓占比偏高？",
  "帮我拟一份本月的调仓计划草案。",
  "对比一下两个账户的投资表现。",
]

function now(): string {
  return new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
}

function fmtDate(v: string | null | undefined) {
  return v || "今天"
}

export function Agent() {
  const toast = useToast()
  const [models, setModels] = useState<AgentModel[] | null>(null)
  const [modelError, setModelError] = useState<string | null>(null)

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [typing, setTyping] = useState(false)
  const [question, setQuestion] = useState("")
  const [asOf, setAsOf] = useState("")
  const [modelId, setModelId] = useState<string>("")

  // 模型管理（抽屉 / 弹窗）
  const [manageOpen, setManageOpen] = useState(false)
  const [showModelForm, setShowModelForm] = useState(false)
  const [form, setForm] = useState<ModelForm>(EMPTY_FORM)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const loadModels = () => {
    setModels(null)
    modelsApi
      .list()
      .then(setModels)
      .catch((e) => setModelError(e instanceof Error ? e.message : String(e)))
  }

  useEffect(() => {
    if (manageOpen) loadModels()
  }, [manageOpen])

  const openCreate = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setShowModelForm(true)
  }

  const openEdit = (m: AgentModel) => {
    setEditingId(m.id)
    setForm({
      name: m.name,
      display_name: m.display_name ?? "",
      base_url: m.base_url,
      model: m.model,
      api_key: "",
      is_default: m.is_default,
    })
    setShowModelForm(true)
  }

  const saveModel = async () => {
    if (!form.name.trim() || !form.base_url.trim() || !form.model.trim()) {
      toast("error", "请填写名称、接口地址与模型名")
      return
    }
    setBusy(true)
    try {
      const payload: Record<string, unknown> = {
        name: form.name.trim(),
        display_name: form.display_name.trim() || null,
        base_url: form.base_url.trim(),
        model: form.model.trim(),
        is_default: form.is_default,
      }
      // 仅在用户填写了密钥时才提交（空串表示不修改）。
      if (form.api_key) payload.api_key = form.api_key
      if (editingId) {
        await modelsApi.update(editingId, payload as never)
        toast("success", "模型配置已更新")
      } else {
        await modelsApi.create(payload as never)
        toast("success", "模型配置已创建")
      }
      setShowModelForm(false)
      loadModels()
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const removeModel = async (m: AgentModel) => {
    if (!confirm(`确定删除模型配置「${m.name}」？`)) return
    try {
      await modelsApi.remove(m.id)
      toast("success", "已删除")
      loadModels()
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    }
  }

  const ask = async () => {
    if (!question.trim()) {
      toast("error", "请输入问题")
      return
    }
    if (!models || models.length === 0) {
      toast("error", "请先在「管理模型」中配置并选择一个模型")
      return
    }
    const q = question.trim()
    setMessages((m) => [...m, { role: "user", content: q, createdAt: now() }])
    setQuestion("")
    setTyping(true)
    try {
      const res = await chatApi.ask({
        question: q,
        as_of: asOf || null,
        model_id: modelId || null,
      })
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: res.answer,
          modelName: res.model_name,
          asOf: res.as_of ?? null,
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
          <h2 className="page__title">Agent 分析</h2>
          <p className="page__sub">
            专用会话：模型只看到只读数据快照与你的提问，无法直接改动账本；可执行的操作需你在网页端确认。
          </p>
        </div>
        <button className="btn btn--secondary" onClick={() => setManageOpen(true)}>
          <Settings2 size={14} aria-hidden /> 管理模型
        </button>
      </div>

      <div className="card">
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
              <div
                key={i}
                className={`msg ${m.role === "user" ? "msg--user" : "msg--bot"}`}
              >
                <div
                  className={`msg__avatar ${m.role === "user" ? "" : "msg__avatar--bot"}`}
                >
                  {m.role === "user" ? "你" : <Bot size={16} aria-hidden />}
                </div>
                <div className="msg__body">
                  <div
                    className={`msg__bubble ${
                      m.role === "user" ? "msg__bubble--user" : "msg__bubble--bot"
                    }`}
                  >
                    {m.content}
                  </div>
                  {m.role === "assistant" && (
                    <details className="evidence">
                      <summary>分析依据</summary>
                      <div className="evidence__body">
                        <span>模型：{m.modelName || "默认模型"}</span>
                        <span>数据截止：{fmtDate(m.asOf)}</span>
                        <span>
                          数据范围：账户 / 持仓 / 收益 / 风险事件 / 投资计划的只读快照
                        </span>
                        <span>
                          说明：本次仅基于只读数据快照，未改动账本；可执行操作需你在网页端确认。
                        </span>
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
                    <span className="typing">
                      <span />
                      <span />
                      <span />
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        <div className="chat__composer">
          <div className="composer__row">
            <select
              className="input"
              style={{ width: 200 }}
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
            >
              <option value="">默认模型</option>
              {(models ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.display_name?.trim() || m.name}
                  {m.is_default ? "（默认）" : ""}
                </option>
              ))}
            </select>
            <input
              className="input"
              type="date"
              style={{ width: 180 }}
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              title="数据截止日期（留空为今天）"
            />
          </div>
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
            <button className="btn btn--primary" onClick={ask} disabled={typing}>
              {typing ? "分析中…" : "分析"}
            </button>
          </div>
        </div>
      </div>

      {/* 模型管理弹窗 */}
      <Dialog
        open={manageOpen}
        title="模型配置"
        onClose={() => {
          setManageOpen(false)
          setShowModelForm(false)
        }}
      >
        {modelError && <div className="alert alert--error">{modelError}</div>}

        {showModelForm ? (
          <div className="stack">
            <label className="field">
              <span className="field__label">名称</span>
              <input
                className="input"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="例如：GPT-5 分析助手"
              />
            </label>
            <label className="field">
              <span className="field__label">中文别名（可选，用于界面友好展示）</span>
              <input
                className="input"
                value={form.display_name}
                onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
                placeholder="例如：主力分析模型"
              />
            </label>
            <label className="field">
              <span className="field__label">接口地址（OpenAI 兼容）</span>
              <input
                className="input"
                value={form.base_url}
                onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
                placeholder="https://api.openai.com/v1"
              />
            </label>
            <label className="field">
              <span className="field__label">模型名</span>
              <input
                className="input"
                value={form.model}
                onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
                placeholder="例如：gpt-5"
              />
            </label>
            <label className="field">
              <span className="field__label">
                API Key{editingId ? "（留空表示不修改）" : ""}
              </span>
              <input
                className="input"
                type="password"
                value={form.api_key}
                onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
                placeholder={editingId ? "不修改请留空" : "sk-..."}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={form.is_default}
                onChange={(e) => setForm((f) => ({ ...f, is_default: e.target.checked }))}
              />
              <span>设为默认模型</span>
            </label>
            <div className="dialog__foot">
              <button
                className="btn btn--ghost"
                onClick={() => setShowModelForm(false)}
              >
                返回
              </button>
              <button className="btn btn--primary" onClick={saveModel} disabled={busy}>
                {busy ? "保存中…" : "保存"}
              </button>
            </div>
          </div>
        ) : (
          <div className="stack">
            <div className="toolbar" style={{ justifyContent: "flex-end" }}>
              <button className="btn btn--primary" onClick={openCreate}>
                <Plus size={14} aria-hidden /> 新建模型
              </button>
            </div>
            {models === null ? (
              <Skeleton rows={4} />
            ) : models.length === 0 ? (
              <p className="muted">还没有模型配置，点击右上角新建。</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>名称</th>
                    <th>接口地址</th>
                    <th>模型</th>
                    <th>默认</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {models.map((m) => (
                    <tr key={m.id}>
                      <td>
                        {m.display_name?.trim() || m.name}
                        {m.display_name?.trim() &&
                        m.display_name.trim() !== m.name ? (
                          <span className="muted">（{m.name}）</span>
                        ) : null}
                      </td>
                      <td className="muted">{m.base_url}</td>
                      <td>{m.model}</td>
                      <td>{m.is_default ? "是" : "—"}</td>
                      <td className="cell--actions">
                        <button
                          className="btn btn--ghost"
                          onClick={() => openEdit(m)}
                        >
                          编辑
                        </button>
                        <button
                          className="btn btn--ghost"
                          onClick={() => removeModel(m)}
                        >
                          <Trash2 size={14} aria-hidden /> 删除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </Dialog>
    </div>
  )
}
