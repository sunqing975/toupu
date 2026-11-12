import { api } from "./client"
import type { PositionOut } from "./types"

const BASE = "/api/v1/positions"

export const positionsApi = {
  list: (accountId?: string) =>
    api<PositionOut[]>(accountId ? `${BASE}?account_id=${accountId}` : BASE),
}
