import { useEffect, useState } from "react"
import { Copy, Cpu, KeyRound, Plug, Plus, Server, Trash2 } from "lucide-react"
import {
  ALL_SCOPES,
  SCOPE_LABELS,
  settingsApi,
  type AgentToken,
  type AgentTokenCreated,
} from "../api/settings"
import {
  mcpServersApi,
  type McpServer,
  type McpServerIn,
} from "../api/mcpServers"
import { modelsApi, type AgentModel, type AgentModelIn } from "../api/models"
import { Dialog } from "../components/Dialog"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"
import { StatusBadge } from "../components/StatusBadge"
import { useToast } from "../components/Toast"

function fmtTime(v: string | null) {
  return v ? new Date(v).toLocaleString("zh-CN") : "—"
}

interface ModelForm {
  name: string
  display_name: string
  base_url: string
  model: string
  api_key: string
  is_default: boolean
}

const EMPTY_MODEL: ModelForm = {
  name: "",
  display_name: "",
  base_url: "https://api.openai.com/v1",
  model: "",
  api_key: "",
  is_default: false,
}

export function Settings() {
  const toast = useToast()

  // —— 对外 MCP 访问凭证（原「Agent Token」，语义：别人连本系统 /mcp 时用的 key）——
  const [tokens, setTokens] = useState<AgentToken[] | null>(null)
  const [tokenError, setTokenError] = useState<string | null>(null)
  const [tokenDialogOpen, setTokenDialogOpen] = useState(false)
  const [tokenName, setTokenName] = useState("")
  const [scopes, setScopes] = useState<Set<string>>(new Set(["read:accounts"]))
  const [tokenBusy, setTokenBusy] = useState(false)
  const [created, setCreated] = useState<AgentTokenCreated | null>(null)

  // —— 挂载外部 MCP 服务（本系统作为客户端去连 weknora 等）——
  const [servers, setServers] = useState<McpServer[] | null>(null)
  const [serverError, setServerError] = useState<string | null>(null)
  const [serverDialogOpen, setServerDialogOpen] = useState(false)
  const [serverBusy, setServerBusy] = useState(false)
  const [editing, setEditing] = useState<McpServer | null>(null)
  const [srvForm, setSrvForm] = useState<McpServerIn>({
    name: "",
    transport: "http",
    command: "",
    url: "",
    enabled: true,
  })
  const [srvTest, setSrvTest] = useState<string | null>(null)

  // —— 模型配置（从 Agent 页迁入设置）——
  const [models, setModels] = useState<AgentModel[] | null>(null)
  const [modelError, setModelError] = useState<string | null>(null)
  const [modelDialogOpen, setModelDialogOpen] = useState(false)
  const [modelBusy, setModelBusy] = useState(false)
  const [editingModel, setEditingModel] = useState<AgentModel | null>(null)
  const [modelForm, setModelForm] = useState<ModelForm>(EMPTY_MODEL)

  const loadTokens = () => {
    setTokens(null)
    settingsApi
      .tokens()
      .then(setTokens)
      .catch((e) => setTokenError(e instanceof Error ? e.message : String(e)))
  }

  const loadServers = () => {
    setServers(null)
    mcpServersApi
      .list()
      .then(setServers)
      .catch((e) => setServerError(e instanceof Error ? e.message : String(e)))
  }

  const loadModels = () => {
    setModels(null)
    modelsApi
      .list()
      .then(setModels)
      .catch((e) => setModelError(e instanceof Error ? e.message : String(e)))
  }

  useEffect(() => {
    loadTokens()
    loadServers()
    loadModels()
  }, [])

  // —— 凭证 ——
  const toggleScope = (s: string) => {
    setScopes((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s)
      else next.add(s)
      return next
    })
  }

  const createToken = async () => {
    if (!tokenName.trim()) {
      toast("error", "请填写凭证名称")
      return
    }
    if (scopes.size === 0) {
      toast("error", "请至少选择一个权限范围")
      return
    }
    setTokenBusy(true)
    try {
      const res = await settingsApi.createToken({ name: tokenName.trim(), scopes: [...scopes] })
      setCreated(res)
      setTokenName("")
      setScopes(new Set(["read:accounts"]))
      toast("success", `已创建访问凭证「${res.name}」`)
      loadTokens()
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    } finally {
      setTokenBusy(false)
    }
  }

  const revoke = async (t: AgentToken) => {
    try {
      await settingsApi.revokeToken(t.id)
      toast("success", `已吊销 ${t.name}`)
      loadTokens()
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    }
  }

  const copy = (text: string) => {
    navigator.clipboard?.writeText(text)
    toast("success", "凭证已复制到剪贴板（仅此一次可见）")
  }

  // —— 外部 MCP 服务 ——
  const openNewServer = () => {
    setEditing(null)
    setSrvForm({ name: "", transport: "http", command: "", url: "", enabled: true })
    setSrvTest(null)
    setServerDialogOpen(true)
  }

  const openEditServer = (s: McpServer) => {
    setEditing(s)
    setSrvForm({
      name: s.name,
      transport: s.transport,
      command: s.command ?? "",
      url: s.url ?? "",
      enabled: s.enabled,
    })
    setSrvTest(null)
    setServerDialogOpen(true)
  }

  const saveServer = async () => {
    if (!srvForm.name.trim()) {
      toast("error", "请填写服务名称")
      return
    }
    setServerBusy(true)
    try {
      const payload = {
        ...srvForm,
        command: srvForm.command ? srvForm.command : null,
        url: srvForm.url ? srvForm.url : null,
      }
      if (editing) {
        await mcpServersApi.update(editing.id, payload)
        toast("success", "已更新外部 MCP 服务")
      } else {
        await mcpServersApi.create(payload)
        toast("success", "已添加外部 MCP 服务")
      }
      setServerDialogOpen(false)
      loadServers()
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    } finally {
      setServerBusy(false)
    }
  }

  const deleteServer = async (s: McpServer) => {
    try {
      await mcpServersApi.remove(s.id)
      toast("success", `已删除 ${s.name}`)
      loadServers()
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    }
  }

  const testServer = async (s: McpServer) => {
    try {
      const res = await mcpServersApi.test(s.id)
      setSrvTest(res.detail)
    } catch (e) {
      setSrvTest(e instanceof Error ? e.message : String(e))
    }
  }

  // —— 模型配置 ——
  const openNewModel = () => {
    setEditingModel(null)
    setModelForm(EMPTY_MODEL)
    setModelDialogOpen(true)
  }

  const openEditModel = (m: AgentModel) => {
    setEditingModel(m)
    setModelForm({
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
    if (!modelForm.name.trim() || !modelForm.base_url.trim() || !modelForm.model.trim()) {
      toast("error", "请填写名称、接口地址与模型名")
      return
    }
    setModelBusy(true)
    try {
      const payload: AgentModelIn = {
        name: modelForm.name.trim(),
        display_name: modelForm.display_name.trim() || null,
        base_url: modelForm.base_url.trim(),
        model: modelForm.model.trim(),
        is_default: modelForm.is_default,
      }
      // 仅在用户填写了密钥时才提交（空串表示不修改）。
      if (modelForm.api_key) payload.api_key = modelForm.api_key
      if (editingModel) {
        await modelsApi.update(editingModel.id, payload)
        toast("success", "模型配置已更新")
      } else {
        await modelsApi.create(payload)
        toast("success", "模型配置已创建")
      }
      setModelDialogOpen(false)
      loadModels()
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    } finally {
      setModelBusy(false)
    }
  }

  const deleteModel = async (m: AgentModel) => {
    if (!confirm(`确定删除模型配置「${m.name}」？`)) return
    try {
      await modelsApi.remove(m.id)
      toast("success", "已删除")
      loadModels()
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h2 className="page__title">设置</h2>
          <p className="page__sub">模型配置、对外 MCP 访问凭证、以及挂载到本系统的外部 MCP 服务。</p>
        </div>
      </div>

      {/* —— 1. 模型配置 —— */}
      <section className="card">
        <div className="card__head">
          <div>
            <h3 className="card__title">
              <Cpu size={16} aria-hidden /> 模型配置
            </h3>
            <p className="page__sub">
              OpenAI 兼容端点（base_url / api_key / model）。密钥只写不读，列表与详情均不回显；留空表示不修改。
            </p>
          </div>
          <button className="btn btn--primary" onClick={openNewModel}>
            <Plus size={14} aria-hidden /> 新建模型
          </button>
        </div>
        {modelError && <div className="alert alert--error">{modelError}</div>}
        {models === null ? (
          <Skeleton rows={4} />
        ) : models.length === 0 ? (
          <EmptyState
            icon={<Cpu size={40} aria-hidden />}
            title="还没有模型配置"
            description="添加后，助手页的 Agent 即可选择该模型进行分析。"
          />
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
                    {m.display_name?.trim() && m.display_name.trim() !== m.name ? (
                      <span className="muted">（{m.name}）</span>
                    ) : null}
                  </td>
                  <td className="muted">{m.base_url}</td>
                  <td>{m.model}</td>
                  <td>{m.is_default ? "是" : "—"}</td>
                  <td className="cell--actions">
                    <button className="btn btn--ghost" onClick={() => openEditModel(m)}>
                      编辑
                    </button>
                    <button className="btn btn--ghost" onClick={() => deleteModel(m)}>
                      <Trash2 size={14} aria-hidden /> 删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* —— 2. 对外 MCP 服务与访问凭证（别人连本系统 /mcp 用）—— */}
      <section className="card">
        <div className="card__head">
          <div>
            <h3 className="card__title">
              <KeyRound size={16} aria-hidden /> 对外 MCP 访问凭证
            </h3>
            <p className="page__sub">
              本系统对外提供 MCP 服务（<code className="code-inline">/mcp/</code>）。其他 Agent 生成 MCP client 连接时，需在请求头携带
              <code className="code-inline">X-Agent-Token</code>；凭证的 scope 决定它可调用哪些只读资源与受控工具。明文仅创建时返回一次，库内只存哈希。
            </p>
          </div>
          <button className="btn btn--primary" onClick={() => { setCreated(null); setTokenDialogOpen(true) }}>
            <Plus size={14} aria-hidden /> 新建凭证
          </button>
        </div>

        {tokenError && <div className="alert alert--error">{tokenError}</div>}

        {tokens === null ? (
          <Skeleton rows={4} />
        ) : tokens.length === 0 ? (
          <EmptyState
            icon={<KeyRound size={40} aria-hidden />}
            title="还没有访问凭证"
            description="创建后，外部 Agent 才能按 scope 连接本系统的 MCP 服务与只读网关。"
          />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>名称</th>
                <th>权限范围</th>
                <th>状态</th>
                <th>最近使用</th>
                <th>创建时间</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {tokens.map((t) => (
                <tr key={t.id}>
                  <td>{t.name}</td>
                  <td className="tags">
                    {t.scopes.map((s) => (
                      <span key={s} className="tag">{SCOPE_LABELS[s] ?? s}</span>
                    ))}
                  </td>
                  <td>
                    <StatusBadge status={t.active && !t.revoked_at ? "ACTIVE" : "CLOSED"} />
                    <span className="muted">{t.active && !t.revoked_at ? "有效" : "已吊销"}</span>
                  </td>
                  <td className="num">{fmtTime(t.last_used_at)}</td>
                  <td className="num">{fmtTime(t.created_at)}</td>
                  <td className="cell--actions">
                    {t.active && !t.revoked_at && (
                      <button className="btn btn--ghost" onClick={() => revoke(t)}>
                        吊销
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* —— 3. 挂载外部 MCP 服务（本系统作为客户端）—— */}
      <section className="card">
        <div className="card__head">
          <div>
            <h3 className="card__title">
              <Plug size={16} aria-hidden /> 挂载外部 MCP 服务
            </h3>
            <p className="page__sub">
              本系统作为客户端去连外部 MCP（如 weknora 等知识库）。登记后，助手会话中的「查询外部知识库」技能可只读拉取其资源；不调用会修改外部系统的工具。
            </p>
          </div>
          <button className="btn btn--primary" onClick={openNewServer}>
            <Plus size={14} aria-hidden /> 添加服务
          </button>
        </div>

        {serverError && <div className="alert alert--error">{serverError}</div>}

        {servers === null ? (
          <Skeleton rows={3} />
        ) : servers.length === 0 ? (
          <EmptyState
            icon={<Server size={40} aria-hidden />}
            title="还没有挂载的外部 MCP 服务"
            description="添加 stdio 或 http 型 MCP 服务，让分析会话能结合外部知识库。"
          />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>名称</th>
                <th>传输</th>
                <th>地址 / 命令</th>
                <th>状态</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {servers.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td>
                    <span className="tag">{s.transport === "http" ? "HTTP" : "stdio"}</span>
                  </td>
                  <td className="muted">
                    {s.transport === "http" ? s.url ?? "—" : s.command ?? "—"}
                  </td>
                  <td>
                    <StatusBadge status={s.enabled ? "ACTIVE" : "CLOSED"} />
                    <span className="muted">{s.enabled ? "已启用" : "已停用"}</span>
                  </td>
                  <td className="cell--actions">
                    <button className="btn btn--ghost" onClick={() => testServer(s)}>
                      测试
                    </button>
                    <button className="btn btn--ghost" onClick={() => openEditServer(s)}>
                      编辑
                    </button>
                    <button className="btn btn--ghost" onClick={() => deleteServer(s)}>
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* —— 弹窗：模型配置 —— */}
      <Dialog open={modelDialogOpen} title={editingModel ? "编辑模型配置" : "新建模型配置"} onClose={() => setModelDialogOpen(false)}>
        <div className="stack">
          <label className="field">
            <span className="field__label">名称</span>
            <input
              className="input"
              value={modelForm.name}
              onChange={(e) => setModelForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="例如：GPT-5 分析助手"
            />
          </label>
          <label className="field">
            <span className="field__label">中文别名（可选，用于界面友好展示）</span>
            <input
              className="input"
              value={modelForm.display_name}
              onChange={(e) => setModelForm((f) => ({ ...f, display_name: e.target.value }))}
              placeholder="例如：主力分析模型"
            />
          </label>
          <label className="field">
            <span className="field__label">接口地址（OpenAI 兼容）</span>
            <input
              className="input"
              value={modelForm.base_url}
              onChange={(e) => setModelForm((f) => ({ ...f, base_url: e.target.value }))}
              placeholder="https://api.openai.com/v1"
            />
          </label>
          <label className="field">
            <span className="field__label">模型名</span>
            <input
              className="input"
              value={modelForm.model}
              onChange={(e) => setModelForm((f) => ({ ...f, model: e.target.value }))}
              placeholder="例如：gpt-5"
            />
          </label>
          <label className="field">
            <span className="field__label">
              API Key{editingModel ? "（留空表示不修改）" : ""}
            </span>
            <input
              className="input"
              type="password"
              value={modelForm.api_key}
              onChange={(e) => setModelForm((f) => ({ ...f, api_key: e.target.value }))}
              placeholder={editingModel ? "不修改请留空" : "sk-..."}
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={modelForm.is_default}
              onChange={(e) => setModelForm((f) => ({ ...f, is_default: e.target.checked }))}
            />
            <span>设为默认模型</span>
          </label>
          <div className="dialog__foot">
            <button className="btn btn--ghost" onClick={() => setModelDialogOpen(false)}>取消</button>
            <button className="btn btn--primary" onClick={saveModel} disabled={modelBusy}>
              {modelBusy ? "保存中…" : "保存"}
            </button>
          </div>
        </div>
      </Dialog>

      {/* —— 弹窗：外部 MCP 服务 —— */}
      <Dialog open={serverDialogOpen} title={editing ? "编辑外部 MCP 服务" : "添加外部 MCP 服务"} onClose={() => setServerDialogOpen(false)}>
        <div className="stack">
          <label className="field">
            <span className="field__label">名称</span>
            <input
              className="input"
              value={srvForm.name}
              onChange={(e) => setSrvForm((p) => ({ ...p, name: e.target.value }))}
              placeholder="例如：weknora 知识库"
            />
          </label>
          <label className="field">
            <span className="field__label">传输方式</span>
            <select
              className="input"
              value={srvForm.transport}
              onChange={(e) =>
                setSrvForm((p) => ({ ...p, transport: e.target.value as "stdio" | "http" }))
              }
            >
              <option value="http">HTTP（Streamable MCP）</option>
              <option value="stdio">stdio（本地命令）</option>
            </select>
          </label>
          {srvForm.transport === "http" ? (
            <label className="field">
              <span className="field__label">URL</span>
              <input
                className="input"
                value={srvForm.url ?? ""}
                onChange={(e) => setSrvForm((p) => ({ ...p, url: e.target.value }))}
                placeholder="http://host:port/mcp/"
              />
            </label>
          ) : (
            <label className="field">
              <span className="field__label">命令</span>
              <input
                className="input"
                value={srvForm.command ?? ""}
                onChange={(e) => setSrvForm((p) => ({ ...p, command: e.target.value }))}
                placeholder="例如：npx -y @weknora/mcp"
              />
            </label>
          )}
          <label className="check">
            <input
              type="checkbox"
              checked={srvForm.enabled ?? true}
              onChange={(e) => setSrvForm((p) => ({ ...p, enabled: e.target.checked }))}
            />
            <span>启用（启用后分析会话可拉取该服务的资源）</span>
          </label>
          {srvTest && <div className="alert alert--info">{srvTest}</div>}
          <div className="dialog__foot">
            {editing && (
              <button className="btn btn--ghost" onClick={() => testServer(editing)} disabled={serverBusy}>
                测试连接
              </button>
            )}
            <button className="btn btn--ghost" onClick={() => setServerDialogOpen(false)}>取消</button>
            <button className="btn btn--primary" onClick={saveServer} disabled={serverBusy}>
              {serverBusy ? "保存中…" : "保存"}
            </button>
          </div>
        </div>
      </Dialog>

      {/* —— 弹窗：访问凭证 —— */}
      <Dialog open={tokenDialogOpen} title="新建对外 MCP 访问凭证" onClose={() => setTokenDialogOpen(false)}>
        {created ? (
          <div className="stack">
            <div className="alert alert--success">
              <p>凭证已创建。明文仅此一次可见，请立即复制保存：</p>
              <code className="code-block">{created.token}</code>
              <button className="btn btn--secondary" onClick={() => copy(created.token)}>
                <Copy size={14} aria-hidden /> 复制
              </button>
            </div>
            <button className="btn btn--ghost" onClick={() => setTokenDialogOpen(false)}>
              关闭
            </button>
          </div>
        ) : (
          <div className="stack">
            <label className="field">
              <span className="field__label">名称</span>
              <input
                className="input"
                value={tokenName}
                onChange={(e) => setTokenName(e.target.value)}
                placeholder="例如：外部分析助手"
              />
            </label>
            <div className="field">
              <span className="field__label">权限范围（scope）：决定该 MCP client 可调用哪些工具/资源</span>
              <div className="check-group">
                {ALL_SCOPES.map((s) => (
                  <label key={s} className="check">
                    <input
                      type="checkbox"
                      checked={scopes.has(s)}
                      onChange={() => toggleScope(s)}
                    />
                    <span>{SCOPE_LABELS[s] ?? s}</span>
                  </label>
                ))}
              </div>
            </div>
            <div className="dialog__foot">
              <button className="btn btn--ghost" onClick={() => setTokenDialogOpen(false)}>取消</button>
              <button className="btn btn--primary" onClick={createToken} disabled={tokenBusy}>
                {tokenBusy ? "创建中…" : "创建"}
              </button>
            </div>
          </div>
        )}
      </Dialog>
    </div>
  )
}
