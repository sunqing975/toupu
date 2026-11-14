// 技能管理界面（用户反馈 m05823：还需要一个技能的管理界面）。
// 技能 = 工具循环里可调用的能力；停用后对「所有 Agent」都不再注入该工具（全局总开关）。
// 每个 Agent 自己挂载哪些技能在「助手」页的编辑器里按分组勾选。
import { useEffect, useMemo, useState } from "react"
import { Blocks, Power, PowerOff, ShieldAlert } from "lucide-react"
import { agentsApi, SKILL_CATEGORY_LABELS, type AgentSkill } from "../api/agents"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"
import { useToast } from "../components/Toast"

const CATEGORY_ORDER = ["data", "analysis", "knowledge", "action"]

export function Skills() {
  const toast = useToast()
  const [skills, setSkills] = useState<AgentSkill[] | null>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setSkills(null)
    setError(null)
    agentsApi
      .skills()
      .then(setSkills)
      .catch((e: unknown) => {
        setSkills([])
        setError((e as Error).message)
      })
  }

  useEffect(load, [])

  const groups = useMemo(() => {
    const out: { category: string; items: AgentSkill[] }[] = []
    for (const cat of CATEGORY_ORDER) {
      const items = (skills ?? []).filter((s) => s.category === cat)
      if (items.length > 0) out.push({ category: cat, items })
    }
    for (const s of skills ?? []) {
      if (!CATEGORY_ORDER.includes(s.category) && !out.some((g) => g.category === s.category)) {
        out.push({ category: s.category, items: (skills ?? []).filter((x) => x.category === s.category) })
      }
    }
    return out
  }, [skills])

  const enabledCount = (skills ?? []).filter((s) => s.enabled).length

  const toggle = async (skill: AgentSkill) => {
    setBusyKey(skill.key)
    try {
      await agentsApi.toggleSkill(skill.key, !skill.enabled)
      setSkills((prev) =>
        (prev ?? []).map((s) => (s.key === skill.key ? { ...s, enabled: !skill.enabled } : s)),
      )
      toast("success", `已${skill.enabled ? "停用" : "启用"}「${skill.name}」`)
    } catch (e) {
      toast("error", (e as Error).message)
    } finally {
      setBusyKey(null)
    }
  }

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h2 className="page__title">技能</h2>
          <p className="page__sub">
            技能是助手在工具循环里可调用的能力。这里管的是全局总开关：停用某个技能后，所有 Agent 的对话都不会再注入该工具。
          </p>
        </div>
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      <div className="alert alert--info" style={{ marginBottom: 16 }}>
        <ShieldAlert size={14} aria-hidden /> 只读/分析技能不改变账本；「写入（受控）」类技能（create_draft_proposal）只会生成待审批草稿，绝不直接入账。
      </div>

      {skills === null ? (
        <div className="card" style={{ padding: "var(--space-4)" }}>
          <Skeleton rows={3} />
        </div>
      ) : skills.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={<Blocks size={40} aria-hidden />}
            title="没有技能"
            description="内置技能会在首次访问助手时自动注册。"
          />
        </div>
      ) : (
        <>
          <div className="skills-summary">
            <span>共 <strong>{skills.length}</strong> 项技能</span>
            <span><Power size={13} aria-hidden /> 已启用 <strong>{enabledCount}</strong></span>
            <span><PowerOff size={13} aria-hidden /> 已停用 <strong>{skills.length - enabledCount}</strong></span>
          </div>

          {groups.map((g) => (
            <section key={g.category} className="skills-group">
              <h3 className="skills-group__title">
                {SKILL_CATEGORY_LABELS[g.category] ?? g.category}
                <span className="muted">（{g.items.length}）</span>
              </h3>
              <div className="skill-cards">
                {g.items.map((s) => (
                  <article
                    key={s.key}
                    className={`skill-card${s.enabled ? "" : " skill-card--off"}`}
                  >
                    <div className="skill-card__head">
                      <span className="skill-card__icon" aria-hidden>
                        <Blocks size={18} />
                      </span>
                      <div className="skill-card__title">
                        <strong>{s.name}</strong>
                        {s.builtin && <span className="tag">内置</span>}
                      </div>
                    </div>
                    <code className="code-inline">{s.key}</code>
                    <p className="skill-card__desc">{s.description}</p>
                    <div className="skill-card__foot">
                      <span className={s.enabled ? "skill-card__state skill-card__state--on" : "skill-card__state"}>
                        {s.enabled ? "已启用" : "已停用"}
                      </span>
                      <button
                        className={s.enabled ? "btn btn--ghost" : "btn btn--secondary"}
                        disabled={busyKey === s.key}
                        onClick={() => toggle(s)}
                      >
                        {busyKey === s.key ? "处理中…" : s.enabled ? "停用" : "启用"}
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          ))}
        </>
      )}
    </div>
  )
}
