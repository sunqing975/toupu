import { FlaskConical } from "lucide-react"
import { EmptyState } from "../components/EmptyState"

// 占位：诚实说明，不伪装功能。后端能力可能已就绪，但此前端页面尚未实现。
export function Placeholder({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <div className="page">
      <div className="page__head">
        <div>
          <p className="page__sub">{description}</p>
        </div>
      </div>
      <div className="card">
        <EmptyState
          icon={<FlaskConical size={40} aria-hidden />}
          title={title}
          description="此前端页面尚未实现，相关功能可从其它入口或 API 访问。"
        />
      </div>
    </div>
  )
}
