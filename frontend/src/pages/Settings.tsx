import { useEffect, useState } from "react"
import { Copy, KeyRound, Plus, ShieldCheck, Server } from "lucide-react"
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
import { Dialog } from "../components/Dialog"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"
import { StatusBadge } from "../components/StatusBadge"
import { useToast } from "../components/Toast"

function fmtTime(v: string | null) {
  return v ? new Date(v).toLocaleString("zh-CN") : "—"
}

export function Settings() {
  const toast = useToast()
  const [tokens, setTokens] = useState<AgentToken[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [name, setName] = useState("")
  const [scopes, setScopes] = useState<Set<string>>(new Set(["read:accounts"]))
  const [busy, setBusy] = useState(false)
  const [created, setCreated] = useState<AgentTokenCreated | null>(null)

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

  const load = () => {
    setTokens(null)
    settingsApi
      .tokens()
      .then(setTokens)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }

  const loadServers = () => {
    setServers(null)
    mcpServersApi
      .list()
      .then(setServers)
      .catch((e) => setServerError(e instanceof Error ? e.message : String(e)))
  }

  useEffect(loadServers, [])

  useEffect(load, [])

  const toggleScope = (s: string) => {
    setScopes((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s)
      else next.add(s)
      return next
    })
  }

  const create = async () => {
    if (!name.trim()) {
      toast("error", "请填写 Token 名称")
      return
    }
    if (scopes.size === 0) {
      toast("error", "请至少选择一个权限范围")
      return
    }
    setBusy(true)
    try {
      const res = await settingsApi.createToken({ name: name.trim(), scopes: [...scopes] })
      setCreated(res)
      setName("")
      setScopes(new Set(["read:accounts"]))
      setDialogOpen(false)
      toast("success", `已创建 Agent Token「${res.name}」`)
      load()
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const revoke = async (t: AgentToken) => {
    try {
      await settingsApi.revokeToken(t.id)
      toast("success", `已吊销 ${t.name}`)
      load()
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e))
    }
  }

  const copy = (text: string) => {
    navigator.clipboard?.writeText(text)
    toast("success", "Token 已复制到剪贴板（仅此一次可见）")
  }

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

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h2 className="page__title">设置</h2>
          <p className="page__sub">Agent Token 与权限范围、模型配置、知识库等。</p>
        </div>
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {/* Agent Token 管理 */}
      <section className="card">
        <div className="card__head">
          <div>
            <h3 className="card__title">
              <KeyRound size={16} aria-hidden /> Agent Token
            </h3>
            <p className="page__sub">
              为外部 Agent 或 MCP 客户端签发只读/有限写入令牌。Token 明文仅在创建时返回一次，库内只存哈希。
            </p>
          </div>
          <button className="btn btn--primary" onClick={() => setDialogOpen(true)}>
            <Plus size={14} aria-hidden /> 新建 Token
          </button>
        </div>

        {tokens === null ? (
          <Skeleton rows={4} />
        ) : tokens.length === 0 ? (
          <EmptyState
            icon={<KeyRound size={40} aria-hidden />}
            title="还没有 Agent Token"
            description="创建后可用于本系统的只读网关或限范围写入提案（审批仍需人工确认）。"
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

      {/* 外部 MCP 服务挂载 */}
      <section className="card">
        <div className="card__head">
          <div>
            <h3 className="card__title">
              <Server size={16} aria-hidden /> 外部 MCP 服务
            </h3>
            <p className="page__sub">
              挂载外部 MCP（如 weknora 等知识库）。管理员登记后，Agent 专用会话会只读地拉取其资源并注入分析提示词；不调用任何会修改外部系统的工具。
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
            description="添加 stdio 或 http 型 MCP 服务，让分析会话能结合外部知识库（如 weknora）。"
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

      {/* 后续里程碑占位：诚实空态，不伪装已在规划中的能力 */}
      <section className="card">
        <div className="card__head">
          <div>
            <h3 className="card__title">
              <ShieldCheck size={16} aria-hidden /> 知识库
            </h3>
            <p className="page__sub">M7 Agent 框架的一部分，规划中。</p>
          </div>
        </div>
        <EmptyState
          icon={<ShieldCheck size={40} aria-hidden />}
          title="尚未实现"
          description="优先以 MCP 方式对接外部知识库（如 weknora 等）；本系统同时支持挂载外部 MCP 服务与对外提供 MCP 服务。"
        />
      </section>

      {/* 新建 / 编辑 外部 MCP 服务弹窗 */}
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
            <span>启用（启用后分析会话会拉取该服务的资源）</span>
          </label>
          {srvTest && (
            <div className="alert alert--info">{srvTest}</div>
          )}
          <div className="dialog__foot">
            {editing && (
              <button
                className="btn btn--ghost"
                onClick={() => testServer(editing)}
                disabled={serverBusy}
              >
                测试连接
              </button>
            )}
            <button className="btn btn--ghost" onClick={() => setServerDialogOpen(false)}>
              取消
            </button>
            <button className="btn btn--primary" onClick={saveServer} disabled={serverBusy}>
              {serverBusy ? "保存中…" : "保存"}
            </button>
          </div>
        </div>
      </Dialog>

      {/* 新建 Token 弹窗 */}
      <Dialog open={dialogOpen} title="新建 Agent Token" onClose={() => setDialogOpen(false)}>
        {created ? (
          <div className="stack">
            <div className="alert alert--success">
              <p>Token 已创建。明文仅此一次可见，请立即复制保存：</p>
              <code className="code-block">{created.token}</code>
              <button className="btn btn--secondary" onClick={() => copy(created.token)}>
                <Copy size={14} aria-hidden /> 复制
              </button>
            </div>
            <button className="btn btn--ghost" onClick={() => setCreated(null)}>
              关闭
            </button>
          </div>
        ) : (
          <div className="stack">
            <label className="field">
              <span className="field__label">名称</span>
              <input
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="例如：我的分析助手"
              />
            </label>
            <div className="field">
              <span className="field__label">权限范围（scope）</span>
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
              <button className="btn btn--ghost" onClick={() => setDialogOpen(false)}>
                取消
              </button>
              <button className="btn btn--primary" onClick={create} disabled={busy}>
                {busy ? "创建中…" : "创建"}
              </button>
            </div>
          </div>
        )}
      </Dialog>
    </div>
  )
}
