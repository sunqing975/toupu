import { useEffect, useRef, useState } from "react"
import {
  AlertTriangle,
  Check,
  Download,
  Eye,
  FileSpreadsheet,
  Info,
  Send,
  Upload,
  X,
} from "lucide-react"
import {
  BATCH_STATUS_LABELS,
  COLUMN_LABELS,
  RECORD_STATUS_LABELS,
  sampleCsv,
  TEMPLATE_COLUMNS,
  importsApi,
  type BatchDetail,
  type ImportBatch,
  type ImportRecord,
  type ImportTemplate,
} from "../api/imports"
import { Dialog } from "../components/Dialog"
import { EmptyState } from "../components/EmptyState"
import { Skeleton } from "../components/Skeleton"
import { StatusBadge } from "../components/StatusBadge"
import { useToast } from "../components/Toast"

const STATUS_OPTIONS = ["", "DRAFT", "CONFIRMED", "CANCELLED"] as const

// 行状态 → 颜色（用现有 badge--* 语义色，避免新增 CSS）。
const RECORD_TONE: Record<string, string> = {
  VALID: "green",
  ERROR: "orange",
  DUPLICATE: "yellow",
  IMPORTED: "blue",
  SKIPPED: "gray",
}

function RecordBadge({ status }: { status: string }) {
  const tone = RECORD_TONE[status] ?? "gray"
  return (
    <span className={`badge badge--${tone}`}>{RECORD_STATUS_LABELS[status] ?? status}</span>
  )
}

// 把后端定位错误（row_no / field / message）渲染成可读的一行。
function rowErrors(r: ImportRecord) {
  return r.errors.map((e, i) => (
    <div key={i} style={{ color: "var(--color-destructive)", fontSize: 12, lineHeight: 1.6 }}>
      第 {e.row_no} 行 · {e.field}：{e.message}
    </div>
  ))
}

// normalized 里挑几个关键字段做预览摘要（其余在 raw 里仍可追溯）。
function rowSummary(r: ImportRecord) {
  const n = r.normalized
  if (!n) return "—"
  const kind = String(n.row_kind ?? "")
  if (kind === "CASH") {
    return `期初现金 ${String(n.amount ?? "")} ${String(n.currency ?? "")}`
  }
  if (kind === "POSITION") {
    return `期初持仓 ${String(n.quantity ?? "")} × ${String(n.code ?? "")}（成本 ${String(n.total_cost ?? "")}）`
  }
  return `${kind}`
}

export function Imports() {
  const toast = useToast()
  const [template, setTemplate] = useState<ImportTemplate | null>(null)
  const [batches, setBatches] = useState<ImportBatch[] | null>(null)
  const [statusFilter, setStatusFilter] = useState("")
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [memo, setMemo] = useState("")
  const fileRef = useRef<HTMLInputElement>(null)

  const [detail, setDetail] = useState<BatchDetail | null>(null)
  const [confirmTarget, setConfirmTarget] = useState<ImportBatch | null>(null)
  const [cancelTarget, setCancelTarget] = useState<ImportBatch | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)

  useEffect(() => {
    importsApi.template().then(setTemplate).catch(() => setTemplate(null))
  }, [])

  const load = () => {
    importsApi
      .list(statusFilter || undefined)
      .then(setBatches)
      .catch((e: unknown) => setError(String((e as Error).message)))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter])

  const openUpload = () => {
    setFile(null)
    setMemo("")
    setUploadOpen(true)
  }

  const submitUpload = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const result = await importsApi.upload(file, memo || undefined)
      toast("success", "文件已上传并生成预览，确认后才会正式入账")
      setUploadOpen(false)
      setDetail(result)
      load()
    } catch (err) {
      toast("error", (err as Error).message)
    } finally {
      setUploading(false)
    }
  }

  const showDetail = async (id: string) => {
    try {
      setDetail(await importsApi.get(id))
    } catch (err) {
      toast("error", (err as Error).message)
    }
  }

  const doConfirm = async () => {
    if (!confirmTarget) return
    setBusy(true)
    try {
      const result = await importsApi.confirm(confirmTarget.id)
      toast("success", `批次已确认入账：${result.records.filter((r) => r.status === "IMPORTED").length} 行`)
      setConfirmTarget(null)
      setDetail(result)
      load()
    } catch (err) {
      toast("error", (err as Error).message)
      setConfirmTarget(null)
    } finally {
      setBusy(false)
    }
  }

  const doCancel = async () => {
    if (!cancelTarget) return
    setBusy(true)
    try {
      const result = await importsApi.cancel(cancelTarget.id)
      toast("success", "批次已取消，未产生任何账务影响")
      setCancelTarget(null)
      setDetail(result)
      load()
    } catch (err) {
      toast("error", (err as Error).message)
      setCancelTarget(null)
    } finally {
      setBusy(false)
    }
  }

  const downloadSample = () => {
    const blob = new Blob([`\uFEFF${sampleCsv()}`], { type: "text/csv;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = "toupu-opening-balance-template.csv"
    a.click()
    URL.revokeObjectURL(url)
  }

  const detailCounts = (d: BatchDetail) => {
    const valid = d.records.filter((r) => r.status === "VALID").length
    const dup = d.records.filter((r) => r.status === "DUPLICATE").length
    return { valid, dup }
  }

  const canConfirm = (d: BatchDetail) => d.status === "DRAFT" && d.error_count === 0 && detailCounts(d).valid > 0

  const actions = (b: ImportBatch) => (
    <span className="cell--actions" style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
      {b.status === "DRAFT" && (
        <button className="btn btn--primary" disabled={busy} onClick={() => setConfirmTarget(b)}>
          <Send size={14} aria-hidden /> 确认入账
        </button>
      )}
      {b.status === "DRAFT" && (
        <button className="btn btn--secondary" disabled={busy} onClick={() => setCancelTarget(b)}>
          <X size={14} aria-hidden /> 取消
        </button>
      )}
      <button className="btn btn--secondary" onClick={() => showDetail(b.id)} aria-label={`查看批次 ${b.id}`}>
        <Eye size={14} aria-hidden />
      </button>
    </span>
  )

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <p className="page__sub">
            导入期初资产：上传 CSV / Excel 生成预览，核对无误后人工确认才会正式入账
          </p>
        </div>
        <button className="btn btn--primary" onClick={openUpload}>
          <Upload size={16} aria-hidden />
          上传文件
        </button>
      </div>

      {/* 上传前说明：状态机 + 模板列，避免用户误以为上传即入账 */}
      <div className="banner" style={{ display: "block", marginBottom: "var(--space-4)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginBottom: 6 }}>
          <Info size={15} aria-hidden />
          <strong>导入不会立即记账</strong>
        </div>
        <p style={{ lineHeight: 1.7, margin: 0 }}>
          上传后只保存原始行并做校验 / 去重，生成预览；只有在批次详情点击「确认入账」，系统才会按期初余额事件建立分录与期初汇总批次（不伪造历史成交）。整批确认是单事务：任一行失败全部回滚。
        </p>
        {template && (
          <details style={{ marginTop: "var(--space-3)" }}>
            <summary style={{ cursor: "pointer", fontSize: 13 }}>
              模板：{template.name}（{template.code}）· {template.columns.length} 列 ·{" "}
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  downloadSample()
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") downloadSample()
                }}
                style={{ color: "var(--color-primary)", textDecoration: "underline" }}
              >
                <Download size={13} aria-hidden /> 下载示例 CSV
              </span>
            </summary>
            <div style={{ marginTop: "var(--space-3)", display: "grid", gap: 4 }}>
              {TEMPLATE_COLUMNS.map((c) => (
                <div key={c} style={{ fontSize: 12, lineHeight: 1.6 }}>
                  <code className="num">{c}</code>
                  <span style={{ color: "var(--color-muted-foreground)" }}>
                    {" "}
                    — {COLUMN_LABELS[c]}
                  </span>
                </div>
              ))}
            </div>
            <p style={{ fontSize: 12, color: "var(--color-muted-foreground)", marginTop: "var(--space-2)" }}>
              必填列：<code>row_kind</code>、<code>account_name</code>、<code>business_date</code>。
              CASH 行需 <code>amount</code>；POSITION 行需 <code>market</code>/<code>code</code>/
              <code>quantity</code>/<code>total_cost</code>。重复行会被自动标记为「重复」并跳过。
            </p>
          </details>
        )}
      </div>

      {error && <div className="banner banner--error">{error}</div>}

      <div className="card table-scroll">
        <div
          style={{
            display: "flex",
            gap: "var(--space-2)",
            padding: "var(--space-2) var(--space-3)",
            borderBottom: "1px solid var(--color-border)",
          }}
        >
          <select
            className="select"
            aria-label="按状态筛选"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s ? BATCH_STATUS_LABELS[s] : "全部状态"}
              </option>
            ))}
          </select>
        </div>

        {batches === null ? (
          <div style={{ padding: "var(--space-4)", display: "grid", gap: "var(--space-3)" }}>
            <Skeleton />
            <Skeleton />
          </div>
        ) : batches.length === 0 ? (
          <EmptyState
            icon={<FileSpreadsheet size={40} aria-hidden />}
            title="还没有导入批次"
            description="上传一份期初资产清单（CSV / Excel），预览无误后再确认入账。"
            action={
              <button className="btn btn--primary" onClick={openUpload}>
                上传文件
              </button>
            }
          />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>文件</th>
                <th>状态</th>
                <th className="cell--num">行数</th>
                <th className="cell--num">错误</th>
                <th className="cell--num">重复</th>
                <th>上传时间</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {batches.map((b) => (
                <tr key={b.id}>
                  <td>
                    {b.file_name}
                    {b.memo && (
                      <div style={{ color: "var(--color-muted-foreground)", fontSize: 12 }}>
                        {b.memo}
                      </div>
                    )}
                  </td>
                  <td>
                    <StatusBadge status={b.status} />
                  </td>
                  <td className="cell--num num">{b.row_count}</td>
                  <td className="cell--num num" style={{ color: b.error_count > 0 ? "var(--color-destructive)" : undefined }}>
                    {b.error_count}
                  </td>
                  <td className="cell--num num">{b.duplicate_count}</td>
                  <td className="num" style={{ fontSize: 12 }}>
                    {b.created_at.replace("T", " ").slice(0, 16)}
                  </td>
                  <td className="cell--actions">{actions(b)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 上传 */}
      <Dialog open={uploadOpen} title="上传期初资产文件" onClose={() => setUploadOpen(false)}>
        <form onSubmit={submitUpload}>
          <div className="field">
            <label className="field__label" htmlFor="import-file" aria-required="true">
              选择文件（CSV / .txt / Excel .xlsx）
            </label>
            <input
              id="import-file"
              ref={fileRef}
              className="input"
              type="file"
              accept=".csv,.txt,.xlsx,.xlsm"
              required
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <p style={{ color: "var(--color-muted-foreground)", fontSize: 12, marginTop: "var(--space-1)" }}>
              表头第 1 行、首条数据第 2 行；列名见上方模板说明。相同文件内容不可重复导入。
            </p>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="import-memo">
              批次备注（选填）
            </label>
            <input
              id="import-memo"
              className="input"
              value={memo}
              onChange={(e) => setMemo(e.target.value)}
              placeholder="例如：2026 年期初对账"
            />
          </div>
          <div
            className="dialog__foot"
            style={{ margin: "0 calc(-1 * var(--space-5))", marginBottom: "calc(-1 * var(--space-5))" }}
          >
            <button type="button" className="btn btn--secondary" onClick={() => setUploadOpen(false)}>
              取消
            </button>
            <button type="submit" className="btn btn--primary" disabled={uploading || !file}>
              {uploading ? "上传中…" : "上传并预览"}
            </button>
          </div>
        </form>
      </Dialog>

      {/* 确认入账 */}
      <Dialog open={confirmTarget !== null} title="确认入账" onClose={() => setConfirmTarget(null)}>
        <p>确定将批次「{confirmTarget?.file_name}」正式入账？</p>
        <p style={{ color: "var(--color-muted-foreground)", marginTop: "var(--space-2)", lineHeight: 1.7 }}>
          系统会为每条有效行建立一条 OPENING_BALANCE 期初余额事件并过账（借现金 / 借证券，贷外部资金平衡），
          持仓行同时建立「期初汇总批次」。重复行会跳过，错误行会阻止整批确认。整批单事务，任一行失败全部回滚。
        </p>
        <div
          className="dialog__foot"
          style={{ margin: "var(--space-4) calc(-1 * var(--space-5)) calc(-1 * var(--space-5))" }}
        >
          <button className="btn btn--secondary" onClick={() => setConfirmTarget(null)}>
            返回
          </button>
          <button className="btn btn--primary" disabled={busy} onClick={doConfirm}>
            <Check size={14} aria-hidden /> 确认入账
          </button>
        </div>
      </Dialog>

      {/* 取消批次 */}
      <Dialog open={cancelTarget !== null} title="取消导入批次" onClose={() => setCancelTarget(null)}>
        <p>确定取消批次「{cancelTarget?.file_name}」？</p>
        <p style={{ color: "var(--color-muted-foreground)", marginTop: "var(--space-2)" }}>
          草稿批次置为已取消，有效行变为已跳过，不产生任何账务与持仓影响。取消后可用同一文件重新上传。
        </p>
        <div
          className="dialog__foot"
          style={{ margin: "var(--space-4) calc(-1 * var(--space-5)) calc(-1 * var(--space-5))" }}
        >
          <button className="btn btn--secondary" onClick={() => setCancelTarget(null)}>
            返回
          </button>
          <button className="btn btn--destructive" disabled={busy} onClick={doCancel}>
            确认取消
          </button>
        </div>
      </Dialog>

      {/* 批次详情 / 预览 */}
      <Dialog open={detail !== null} title="导入批次详情与预览" onClose={() => setDetail(null)}>
        {detail && (
          <>
            <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", marginBottom: "var(--space-3)" }}>
              <StatusBadge status={detail.status} />
              <span className="badge badge--gray">{detail.file_name}</span>
              <span className="badge badge--gray">共 {detail.row_count} 行</span>
              <span className="badge badge--green">可导入 {detailCounts(detail).valid}</span>
              {detail.error_count > 0 && (
                <span className="badge badge--orange">错误 {detail.error_count}</span>
              )}
              {detail.duplicate_count > 0 && (
                <span className="badge badge--yellow">重复 {detail.duplicate_count}</span>
              )}
            </div>

            {detail.error_count > 0 && (
              <div className="banner banner--error" style={{ display: "block" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                  <AlertTriangle size={14} aria-hidden />
                  <strong>存在错误行，无法确认入账</strong>
                </div>
                <p style={{ margin: 0, lineHeight: 1.7 }}>
                  请按下方定位（行号 / 字段 / 原因）修正文件后重新上传。错误行不会被记账。
                </p>
              </div>
            )}

            {detail.status === "DRAFT" && detail.error_count === 0 && detailCounts(detail).valid > 0 && (
              <div className="banner" style={{ display: "block" }}>
                预览通过：{detailCounts(detail).valid} 行可导入
                {detailCounts(detail).dup > 0 && `，${detailCounts(detail).dup} 行重复将跳过`}。确认入账后才会写正式账本。
              </div>
            )}

            {detail.raw_headers && (
              <p style={{ fontSize: 12, color: "var(--color-muted-foreground)", marginBottom: "var(--space-2)" }}>
                原始表头：{detail.raw_headers.join(" · ")}
              </p>
            )}

            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th className="cell--num">行</th>
                    <th>状态</th>
                    <th>内容 / 校验结果</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.records.map((r) => (
                    <tr key={r.id}>
                      <td className="cell--num num">{r.row_no}</td>
                      <td>
                        <RecordBadge status={r.status} />
                      </td>
                      <td>
                        <div className="num" style={{ fontSize: 13 }}>
                          {rowSummary(r)}
                        </div>
                        {rowErrors(r)}
                        {r.status === "DUPLICATE" && (
                          <div style={{ color: "var(--color-muted-foreground)", fontSize: 12, marginTop: 2 }}>
                            与已有记录的业务键重复，确认时自动跳过
                          </div>
                        )}
                        {r.dedup_key && r.status !== "DUPLICATE" && (
                          <div style={{ color: "var(--color-muted-foreground)", fontSize: 11, marginTop: 2 }}>
                            去重键：{r.dedup_key}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div
              className="dialog__foot"
              style={{ margin: "var(--space-4) calc(-1 * var(--space-5)) calc(-1 * var(--space-5))" }}
            >
              <button className="btn btn--secondary" onClick={() => setDetail(null)}>
                关闭
              </button>
              {canConfirm(detail) && (
                <button
                  className="btn btn--primary"
                  disabled={busy}
                  onClick={() => {
                    setConfirmTarget(detail)
                    setDetail(null)
                  }}
                >
                  <Send size={14} aria-hidden /> 确认入账
                </button>
              )}
            </div>
          </>
        )}
      </Dialog>
    </div>
  )
}
