import { api } from "./client"
import type { InvestmentAccount } from "./types"

const BASE = "/api/v1/accounts"

export const accountsApi = {
  list: () => api<InvestmentAccount[]>(BASE),
  create: (payload: { name: string; account_type: string; currency: string; notes?: string | null }) =>
    api<InvestmentAccount>(BASE, { method: "POST", body: JSON.stringify(payload) }),
  update: (
    id: string,
    payload: { name?: string; status?: string; notes?: string | null },
  ) => api<InvestmentAccount>(`${BASE}/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  remove: (id: string) => api<void>(`${BASE}/${id}`, { method: "DELETE" }),
}
