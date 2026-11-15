import { useEffect, useRef, useState } from "react"
import { api } from "../api/client"
import { Dialog } from "../components/Dialog"
import { useToast } from "../components/Toast"

type SkillFile = { path: string; size: number; readable: boolean }
type SkillPackage = { id: string; name: string; description: string; content: string; enabled: boolean; builtin: boolean; files: SkillFile[] }
function normalizePackage(item: SkillPackage): SkillPackage {
  return { ...item, files: item.files ?? [{ path: "SKILL.md", size: new TextEncoder().encode(item.content).length, readable: true }] }
}
const BASE = "/api/v1/agent/skill-packages"
const EXAMPLE = "---\nname: investment-review\ndescription: 用户需要投资分析时使用。\n---\n# 投资分析\n\n1. 先读取真实持仓与行情覆盖。\n2. 标明风险、数据来源与缺失项。\n3. 不自动交易，不直接入账。\n"

export function Skills() {
  const toast = useToast()
  const [items, setItems] = useState<SkillPackage[]>([])
  const [editing, setEditing] = useState<SkillPackage | null>(null)
  const [open, setOpen] = useState(false)
  const [content, setContent] = useState(EXAMPLE)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState("SKILL.md")
  const [preview, setPreview] = useState<string | null>("")
  const [previewBusy, setPreviewBusy] = useState(false)
  const file = useRef<HTMLInputElement>(null)
  const previewRequest = useRef(0)
  const load = () => { setLoading(true); api<SkillPackage[]>(BASE).then(rows => setItems(rows.map(normalizePackage))).catch(e => toast("error", e.message)).finally(() => setLoading(false)) }
  useEffect(load, [])
  const show = (item: SkillPackage | null) => {
    previewRequest.current++; setPreviewBusy(false); setSelected("SKILL.md"); setEditing(item); setContent(item?.content ?? EXAMPLE); setOpen(true)
  }
  const save = async () => {
    setBusy(true)
    try {
      await api(editing ? BASE + "/" + editing.id : BASE, { method: editing ? "PATCH" : "POST", body: JSON.stringify({ content }) })
      setOpen(false); load(); toast("success", "技能已保存，其他目录文件保持不变")
    } catch (e) { toast("error", (e as Error).message) }
    finally { setBusy(false) }
  }
  const toggle = async (item: SkillPackage) => {
    setBusy(true)
    try {
      await api(BASE + "/" + item.id, { method: "PATCH", body: JSON.stringify({ enabled: !item.enabled }) })
      load()
    } catch (e) { toast("error", (e as Error).message) }
    finally { setBusy(false) }
  }
  const selectFile = async (path: string) => {
    setSelected(path)
    const request = ++previewRequest.current
    if (path === "SKILL.md" || !editing) { setPreviewBusy(false); return }
    setPreviewBusy(true); setPreview(null)
    try {
      const result = await api<{ content: string | null }>(BASE + "/" + editing.id + "/files?path=" + encodeURIComponent(path))
      if (request === previewRequest.current) setPreview(result.content)
    } catch (e) { toast("error", (e as Error).message) }
    finally { if (request === previewRequest.current) setPreviewBusy(false) }
  }
  return <section className="stack" aria-label="技能管理">
    <header className="page__head">
      <div><h2 className="page__title">技能</h2><p className="page__sub">一个技能是一个目录：SKILL.md 作为入口，引用资料、脚本与资源随包保存。</p></div>
      <div className="toolbar">
        <button className="btn btn--secondary" disabled={busy} onClick={() => file.current?.click()}>{busy ? "处理中…" : "导入技能 ZIP"}</button>
        <button className="btn btn--primary" disabled={busy} onClick={() => show(null)}>新建技能</button>
      </div>
    </header>
    <input ref={file} type="file" accept=".zip,.md" hidden onChange={async e => {
      const f = e.target.files?.[0]; e.target.value = ""; if (!f) return
      const zip = f.name.toLowerCase().endsWith(".zip")
      if (f.size > (zip ? 10 * 1024 * 1024 : 100000)) { toast("error", zip ? "ZIP 不能超过10MiB" : "入口文件不能超过100KB"); return }
      setBusy(true)
      try {
        if (zip) {
          const body = new FormData(); body.append("file", f)
          const result = await api<SkillPackage>(BASE + "/import", { method: "POST", headers: {}, body })
          load(); show(result); toast("success", "技能目录已导入，共 " + result.files.length + " 个文件")
        } else { show(null); setContent(await f.text()) }
      } catch (error) { toast("error", (error as Error).message) }
      finally { setBusy(false) }
    }} />
    <p className="alert alert--info">ZIP 可直接包含 SKILL.md，或包含一层技能目录。支持 references / scripts / assets 等文件；脚本仅保存和阅读，不执行。助手按需加载入口和引用文件，不扩大工具权限。</p>
    {loading && <p className="muted" role="status">正在加载技能目录…</p>}
    {!loading && items.length === 0 && <p className="muted">暂无技能，请导入技能 ZIP 或新建技能。</p>}
    <div className="skill-cards">{items.map(item => <article key={item.id} className={"skill-card" + (item.enabled ? "" : " skill-card--off")}>
      <div className="skill-card__head"><strong>{item.name}</strong><span className="tag">{item.builtin ? "内置" : "自定义"}</span></div>
      <code className="code-inline">{item.name}/</code>
      <p className="skill-card__desc">{item.description}</p>
      <p className="muted">{item.files.length} 个文件 · 入口 SKILL.md</p>
      <div className="skill-card__foot"><span>{item.enabled ? "已启用" : "已停用"}</span><div>
        <button className="btn btn--ghost" onClick={() => show(item)}>查看目录 / 编辑</button>
        <button className="btn btn--secondary" disabled={busy} onClick={() => toggle(item)}>{item.enabled ? "停用" : "启用"}</button>
      </div></div>
    </article>)}</div>
    <Dialog open={open} onClose={() => { if (!busy) setOpen(false) }} title={editing ? editing.name + "/" : "新建技能目录"}>
      {editing && <label className="field">目录文件<select className="select" value={selected} onChange={e => selectFile(e.target.value)}>
        {editing.files.map(f => <option key={f.path} value={f.path}>{f.path} · {f.size.toLocaleString()} B{f.readable ? "" : " · 下载查看"}</option>)}
      </select></label>}
      {selected === "SKILL.md" ? <label className="field">SKILL.md · 入口文件<textarea className="textarea" style={{ minHeight: 340, fontFamily: "var(--font-mono)" }} value={content} onChange={e => setContent(e.target.value)} /></label>
        : previewBusy ? <p role="status">正在读取文件…</p>
        : preview !== null ? <label className="field">{selected} · 只读<textarea className="textarea" style={{ minHeight: 340, fontFamily: "var(--font-mono)" }} readOnly value={preview} /></label>
        : <p className="muted">二进制或超过100KB的文件不提供文本预览，请下载查看。</p>}
      <p className="muted">入口需要 YAML name、description 和 Markdown 正文。保存入口不会移除其他文件。ZIP 最多512个条目，解压总计20MiB，单文件5MiB。同名技能不覆盖。</p>
      <div className="dialog__foot">
        {editing && <a className="btn btn--secondary" href={BASE + "/" + editing.id + "/download?path=" + encodeURIComponent(selected)} download>下载当前文件</a>}
        <button className="btn btn--primary" disabled={busy} onClick={save}>{busy ? "保存中…" : "保存入口文件"}</button>
      </div>
    </Dialog>
  </section>
}
