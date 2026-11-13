import { api, ApiError } from "./client"

// M4 导入与期初资产：上传（预览）→ 人工确认（过账）/ 取消。
// 导入阶段绝不写正式账本，只有 confirm 才建 OPENING_BALANCE 并过账（agent.md §7 / §16）。
export interface ImportTemplate {
  code: string
  name: string
  description: string | null
  columns: string[]
}

export interface ImportBatch {
  id: string
  template_code: string
  file_name: string
  file_hash: string
  status: string
  row_count: number
  error_count: number
  duplicate_count: number
  memo: string | null
  created_at: string
  confirmed_at: string | null
}

export interface RowError {
  row_no: number
  field: string
  message: string
}

export interface ImportRecord {
  id: string
  row_no: number
  status: string
  dedup_key: string | null
  normalized: Record<string, unknown> | null
  raw: Record<string, unknown>
  errors: RowError[]
}

export interface BatchDetail extends ImportBatch {
  raw_headers: string[] | null
  records: ImportRecord[]
}

const BASE = "/api/v1/imports"

// 批次与行状态标签（后端固定枚举，见 imports/service.py）。
export const BATCH_STATUS_LABELS: Record<string, string> = {
  DRAFT: "草稿",
  CONFIRMED: "已确认入账",
  CANCELLED: "已取消",
}

export const RECORD_STATUS_LABELS: Record<string, string> = {
  VALID: "可导入",
  ERROR: "错误",
  DUPLICATE: "重复",
  IMPORTED: "已入账",
  SKIPPED: "已跳过",
}

// 模板内置列说明（对齐 0007 种子 import_field_mappings 的 13 列），用于上传页提示。
export const COLUMN_LABELS: Record<string, string> = {
  row_kind: "行类型（CASH / POSITION，或 现金 / 持仓）",
  account_name: "账户名称（必填，需已存在）",
  business_date: "业务日期（必填，YYYY-MM-DD）",
  amount: "期初现金金额（CASH 行必填）",
  market: "市场（POSITION 行必填，如 CN）",
  code: "品种代码（POSITION 行必填）",
  quantity: "持仓数量（POSITION 行必填）",
  total_cost: "账面成本（POSITION 行必填）",
  currency: "币种（默认 CNY）",
  cost_source: "成本来源 / 可信度",
  valuation_date: "估值日期",
  external_id: "外部成交编号（去重优先键）",
  memo: "备注",
}

export const TEMPLATE_COLUMNS = [
  "row_kind",
  "account_name",
  "business_date",
  "amount",
  "market",
  "code",
  "quantity",
  "total_cost",
  "currency",
  "cost_source",
  "valuation_date",
  "external_id",
  "memo",
] as const

// 生成示例 CSV 内容，供用户下载参照（表头即模板列名）。
export function sampleCsv(): string {
  const header = TEMPLATE_COLUMNS.join(",")
  const cash = "CASH,我的券商账户,2026-01-01,100000,,,,,CNY,银行流水,2026-01-01,,期初现金"
  const pos =
    "POSITION,我的券商账户,2026-01-01,,CN,600519,1000,25000,CNY,券商对账单,2026-01-01,,期初持仓"
  return `${header}\n${cash}\n${pos}\n`
}

export const importsApi = {
  template: () => api<ImportTemplate>(`${BASE}/template`),

  // multipart 上传：不能用 api()（它会强制 Content-Type: application/json），
  // 改用原生 fetch，让浏览器自动带 boundary；错误体仍按 {error:{code,message}} 解析。
  upload: async (file: File, memo?: string): Promise<BatchDetail> => {
    const form = new FormData()
    form.append("file", file)
    const qs = memo ? `?memo=${encodeURIComponent(memo)}` : ""
    const resp = await fetch(`${BASE}/batches${qs}`, { method: "POST", body: form })
    if (!resp.ok) {
      let code = "HTTP_ERROR"
      let message = `上传失败（${resp.status}）`
      try {
        const body = (await resp.json()) as { error?: { code?: string; message?: string }; detail?: string }
        if (body.error) {
          code = body.error.code ?? code
          message = body.error.message ?? message
        } else if (body.detail) {
          message = body.detail
        }
      } catch {
        // 非 JSON 响应，保留默认信息
      }
      throw new ApiError(code, message)
    }
    return (await resp.json()) as BatchDetail
  },

  list: (status?: string) => {
    const qs = status ? `?status=${encodeURIComponent(status)}` : ""
    return api<ImportBatch[]>(`${BASE}/batches${qs}`)
  },
  get: (id: string) => api<BatchDetail>(`${BASE}/batches/${id}`),
  confirm: (id: string) => api<BatchDetail>(`${BASE}/batches/${id}/confirm`, { method: "POST" }),
  cancel: (id: string) => api<BatchDetail>(`${BASE}/batches/${id}/cancel`, { method: "POST" }),
}
