import { FlaskConical } from "lucide-react"
import { EmptyState } from "../components/EmptyState"

// 未到里程碑的页面占位：诚实说明，不伪装功能。
export function Placeholder({ milestone, description }: { milestone: string; description: string }) {
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
          title={`随 ${milestone} 里程碑上线`}
          description="后端能力就绪后此页面开放使用，界面不会伪装已有数据。"
        />
      </div>
    </div>
  )
}
