const LABELS: Record<string, { text: string; tone: string }> = {
  // 账户
  ACTIVE: { text: "正常", tone: "green" },
  FROZEN: { text: "冻结", tone: "yellow" },
  CLOSED: { text: "已关闭", tone: "gray" },
  // 交易状态
  DRAFT: { text: "草稿", tone: "gray" },
  CONFIRMED: { text: "已确认", tone: "blue" },
  PARTIAL: { text: "部分成交", tone: "yellow" },
  POSTED: { text: "已入账", tone: "green" },
  REVERSED: { text: "已冲正", tone: "orange" },
  CANCELLED: { text: "已取消", tone: "gray" },
  // 标的
  DELISTED: { text: "已退市", tone: "gray" },
  // 风险事件状态
  OPEN: { text: "待处理", tone: "yellow" },
  ACKNOWLEDGED: { text: "已确认", tone: "blue" },
  IGNORED: { text: "已忽略", tone: "gray" },
  // 风险级别
  INFO: { text: "提示", tone: "blue" },
  WARNING: { text: "警告", tone: "yellow" },
  CRITICAL: { text: "严重", tone: "orange" },
  // 提案状态
  PENDING: { text: "待审批", tone: "yellow" },
  APPROVED: { text: "已批准", tone: "green" },
  REJECTED: { text: "已拒绝", tone: "gray" },
  EXPIRED: { text: "已过期", tone: "gray" },
  // 计划
  ARCHIVED: { text: "已归档", tone: "gray" },
}

export function StatusBadge({ status }: { status: string }) {
  const meta = LABELS[status] ?? { text: status, tone: "gray" }
  const strike = status === "CANCELLED" ? " badge--strikethrough" : ""
  return <span className={`badge badge--${meta.tone}${strike}`}>{meta.text}</span>
}
