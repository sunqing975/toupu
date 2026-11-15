// Display only. Never round stored ledger facts or API payloads.
function display(v: string | null | undefined, minimum: number, maximum: number): string {
  if (v == null || v.trim() === "") return "—"
  const n = Number(v)
  if (!Number.isFinite(n)) return "—"
  return new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: minimum, maximumFractionDigits: maximum,
  }).format(Object.is(n, -0) || Math.abs(n) < 0.5 * 10 ** -maximum ? 0 : n)
}
export const fmtMoney = (v: string | null | undefined) => display(v, 2, 2)
export const fmtNav = (v: string | null | undefined) => display(v, 4, 4)
export const fmtQuantity = (v: string | null | undefined) => display(v, 0, 2)
