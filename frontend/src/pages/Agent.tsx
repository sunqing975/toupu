import { useEffect, useState } from "react"
import { Bot, KeyRound, Plus, Trash2 } from "lucide-react"
import { modelsApi, type AgentModel } from "../api/models"
import { chatApi } from "../api/chat"
import { Dialog } from "../components/Dialog"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"
import { StatusBadge } from "../components/StatusBadge"
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

function fmtTime(v: string | null) {
  return v ? new Date(v).toLocaleString("zh-CN") : "—"
}

export function Agent() {
  const toast = useToast()
  const [models, setModels] = useState<AgentModel[] | null>(null)
  const [modelError, setModelError] = useState<string | null>(null)
  const [modelDialogOpen, setModelDialogOpen] = useState(false)
  const [form, setForm] = useState<ModelForm>(EMPTY_FORM)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [question, setQuestion] = useState("")
  const [asOf, setAsOf] = useState("")
  const [modelId, setModelId] = useState<string>("")
  const [answer, setAnswer] = useState<string | null>(null)
  const [chatModelName, setChatModelName] = useState<string | null>(null)
  const [chatBusy, setChatBusy] = useState(false)

  const loadModels = () => {
    setModels(null)
    modelsApi
      .list()
      .then(setModels)
      .catch((e) => setModelError(e instanceof Error ? e.message : String(e)))
  }

  useEffect(loadModels, [])

  const openCreate = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setModelDialogOpen(true)
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
    setModelDialogOpen(true)
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
      setModelDialogOpen(false)
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
      toast("error", "请先在下方配置并选择一个模型")
      return
    }
    setChatBusy(true)
    try {
      const res = await chatApi.ask({
        question: question.trim(),
        as_of: asOf || null,
        model_id: modelId || null,
      })
      setAnswer(res.answer)
      setChatModelName(res.model_name)
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    } finally {
      setChatBusy(false)
    }
  }

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h2 className="page__title">Agent 分析</h2>
          <p className="page__sub">
            专用会话：模型只看到只读数据快照与你的提问，无法直接改动账本；可执行的操作需你在网页端确认。
          </p>
        </div>
      </div>

      {/* 对话 */}
      <section className="card">
        <div className="card__head">
          <div>
            <h3 className="card__title">
              <Bot size={16} aria-hidden /> 数据分析会话
            </h3>
            <p className="page__sub">提问当前持仓、收益、风险或投资计划建议。</p>
          </div>
        </div>

        <div className="stack">
          <div className="field">
            <span className="field__label">选择模型（默认使用标记为默认的模型）</span>
            <select
              className="input"
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
          </div>

          <div className="field">
            <span className="field__label">数据截止日期（留空为今天）</span>
            <input
              className="input"
              type="date"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
            />
          </div>

          <textarea
            className="input"
            rows={4}
            value={question}
            placeholder="例如：我当前组合的整体风险如何？有哪些持仓占比偏高？"
            onChange={(e) => setQuestion(e.target.value)}
          />

          <div className="dialog__foot">
            <button className="btn btn--primary" onClick={ask} disabled={chatBusy}>
              {chatBusy ? "分析中…" : "分析"}
            </button>
          </div>

          {answer !== null && (
            <div className="alert alert--info">
              <p className="muted">{chatModelName ? `由 ${chatModelName} 生成` : ""}</p>
              <p style={{ whiteSpace: "pre-wrap" }}>{answer}</p>
            </div>
          )}
        </div>
      </section>

      {/* 模型配置 */}
      <section className="card">
        <div className="card__head">
          <div>
            <h3 className="card__title">
              <KeyRound size={16} aria-hidden /> 模型配置
            </h3>
            <p className="page__sub">
              接入 OpenAI 兼容端点。密钥只写不读，列表与详情均不回显。
            </p>
          </div>
          <button className="btn btn--primary" onClick={openCreate}>
            <Plus size={14} aria-hidden /> 新建模型
          </button>
        </div>

        {modelError && <div className="alert alert--error">{modelError}</div>}

        {models === null ? (
          <Skeleton rows={4} />
        ) : models.length === 0 ? (
          <EmptyState
            icon={<KeyRound size={40} aria-hidden />}
            title="还没有模型配置"
            description="配置一个 OpenAI 兼容的接口地址与模型名后，即可在上方会话中分析当前投资组合。"
          />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>名称</th>
                <th>接口地址</th>
                <th>模型</th>
                <th>默认</th>
                <th>创建时间</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.id}>
                  <td>
                    {m.display_name?.trim() || m.name}
                    {m.display_name?.trim() && m.display_name.trim() !== m.name ? (
                      <span className="muted">（{m.name}）</span>
                    ) : null}
                  </td>
                  <td className="muted">{m.base_url}</td>
                  <td>{m.model}</td>
                  <td>
                    {m.is_default ? (
                      <StatusBadge status="ACTIVE" />
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className="num">{fmtTime(m.created_at)}</td>
                  <td className="cell--actions">
                    <button className="btn btn--ghost" onClick={() => openEdit(m)}>
                      编辑
                    </button>
                    <button className="btn btn--ghost" onClick={() => removeModel(m)}>
                      <Trash2 size={14} aria-hidden /> 删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* 新建 / 编辑模型弹窗 */}
      <Dialog
        open={modelDialogOpen}
        title={editingId ? "编辑模型配置" : "新建模型配置"}
        onClose={() => setModelDialogOpen(false)}
      >
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
            <button className="btn btn--ghost" onClick={() => setModelDialogOpen(false)}>
              取消
            </button>
            <button className="btn btn--primary" onClick={saveModel} disabled={busy}>
              {busy ? "保存中…" : "保存"}
            </button>
          </div>
        </div>
      </Dialog>
    </div>
  )
}
