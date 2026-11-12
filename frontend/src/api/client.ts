// 后端错误统一格式 {"error":{code,message}} —— 所有请求经此封装。
export class ApiError extends Error {
  code: string

  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  })
  if (!resp.ok) {
    let code = "HTTP_ERROR"
    let message = `请求失败（${resp.status}）`
    try {
      const body = (await resp.json()) as { error?: { code?: string; message?: string } }
      if (body.error) {
        code = body.error.code ?? code
        message = body.error.message ?? message
      }
    } catch {
      // 非 JSON 响应，保留默认错误信息
    }
    throw new ApiError(code, message)
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}
