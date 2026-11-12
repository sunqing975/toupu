// API 访问统一走 /api 前缀，开发/生产都由代理转发到后端。
export type Health = { status: string; app: string }
export type ApiError = { error: { code: string; message: string } }

export async function getHealth(): Promise<Health> {
  const resp = await fetch('/api/health')
  if (!resp.ok) {
    const body = (await resp.json()) as ApiError
    throw new Error(`${body.error.code}: ${body.error.message}`)
  }
  return (await resp.json()) as Health
}
