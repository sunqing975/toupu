import { useEffect, useRef, useState } from "react"
import { api } from "../api/client"
import { Dialog } from "../components/Dialog"
import { useToast } from "../components/Toast"

type SkillPackage = { id: string; name: string; description: string; content: string; enabled: boolean; builtin: boolean }
const BASE = "/api/v1/agent/skill-packages"
const EXAMPLE = `---\nname: investment-review\ndescription: 用户需要投资分析时使用。\n---\n# 投资分析\n\n1. 先读取真实持仓与行情覆盖。\n2. 标明风险、数据来源与缺失项。\n3. 不自动交易，不直接入账。\n`

export function Skills() {
  const toast = useToast()
  const [items, setItems] = useState<SkillPackage[]>([])
  const [editing, setEditing] = useState<SkillPackage | null>(null)
  const [open, setOpen] = useState(false)
  const [content, setContent] = useState(EXAMPLE)
  const file = useRef<HTMLInputElement>(null)
  const load = () => { api<SkillPackage[]>(BASE).then(setItems).catch(e => toast("error", e.message)) }
  useEffect(load, [])
  const save = async () => {
    try {
      await api(editing ? `${BASE}/${editing.id}` : BASE, { method: editing ? "PATCH" : "POST", body: JSON.stringify({ content }) })
      setOpen(false); load(); toast("success", "技能已保存")
    } catch (e) { toast("error", (e as Error).message) }
  }
  const toggle = async (item: SkillPackage) => {
    try {
      await api(`${BASE}/${item.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !item.enabled }) })
      load()
    } catch (e) { toast("error", (e as Error).message) }
  }
  return <div className="page">
    <header className="page__head">
      <div><h2 className="page__title">技能</h2><p className="page__sub">以 SKILL.md 定义专业知识与工作流程，而不是把 API 工具叫作技能。</p></div>
      <div className="toolbar">
        <button className="btn btn--secondary" onClick={() => file.current?.click()}>导入 SKILL.md</button>
        <button className="btn btn--primary" onClick={() => { setEditing(null); setContent(EXAMPLE); setOpen(true) }}>新建技能</button>
      </div>
    </header>
    <input ref={file} type="file" accept=".md" hidden onChange={async e => {
      const f = e.target.files?.[0]; if (!f) return
      if (f.size > 100000) { toast("error", "文件不能超过100KB"); return }
      setEditing(null); setContent(await f.text()); setOpen(true); e.target.value = ""
    }} />
    <p className="alert alert--info">助手先读取技能名称与描述，需要时通过 load_skill 加载完整步骤。技能不会扩大工具权限，也不执行上传的脚本。</p>
    <div className="skill-cards">{items.map(item => <article key={item.id} className={`skill-card${item.enabled ? "" : " skill-card--off"}`}>
      <div className="skill-card__head"><strong>{item.name}</strong><span className="tag">{item.builtin ? "内置" : "自定义"}</span></div>
      <code className="code-inline">{item.name}/SKILL.md</code>
      <p className="skill-card__desc">{item.description}</p>
      <div className="skill-card__foot"><span>{item.enabled ? "已启用" : "已停用"}</span><div>
        <button className="btn btn--ghost" onClick={() => { setEditing(item); setContent(item.content); setOpen(true) }}>查看 / 编辑</button>
        <button className="btn btn--secondary" onClick={() => toggle(item)}>{item.enabled ? "停用" : "启用"}</button>
      </div></div>
    </article>)}</div>
    <Dialog open={open} onClose={() => setOpen(false)} title={editing ? "编辑 SKILL.md" : "添加 SKILL.md"}>
      <label className="field">技能文件内容<textarea className="textarea" style={{ minHeight: 340, fontFamily: "var(--font-mono)" }} value={content} onChange={e => setContent(e.target.value)} /></label>
      <p className="muted">需要 YAML name、description 和 Markdown 正文。本版支持单文件，不支持脚本执行或附件安装。</p>
      <div className="dialog__foot"><button className="btn btn--primary" onClick={save}>保存技能</button></div>
    </Dialog>
  </div>
}
