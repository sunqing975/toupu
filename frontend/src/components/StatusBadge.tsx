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
}

export function StatusBadge({ status }: { status: string }) {
  const meta = LABELS[status] ?? { text: status, tone: "gray" }
  const strike = status === "CANCELLED" ? " badge--strikethrough" : ""
  return <span className={`badge badge--${meta.tone}${strike}`}>{meta.text}</span>
}
