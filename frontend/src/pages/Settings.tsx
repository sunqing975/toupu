import { useEffect, useState } from "react"
import { Copy, KeyRound, Plus, ShieldCheck } from "lucide-react"
import {
  ALL_SCOPES,
  SCOPE_LABELS,
  settingsApi,
  type AgentToken,
  type AgentTokenCreated,
} from "../api/settings"
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

  const load = () => {
    setTokens(null)
    settingsApi
      .tokens()
      .then(setTokens)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }

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

      {/* 后续里程碑占位：诚实空态，不伪装已在规划中的能力 */}
      <section className="card">
        <div className="card__head">
          <div>
            <h3 className="card__title">
              <ShieldCheck size={16} aria-hidden /> 知识库 / 外部 MCP
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
