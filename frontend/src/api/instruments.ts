import { api } from "./client"
import type { Instrument } from "./types"

const BASE = "/api/v1/instruments"

export const instrumentsApi = {
  list: (instrumentType?: string) =>
    api<Instrument[]>(instrumentType ? `${BASE}?instrument_type=${instrumentType}` : BASE),
  create: (payload: {
    instrument_type: string
    market: string
    exchange?: string | null
    code: string
    name: string
    currency: string
  }) => api<Instrument>(BASE, { method: "POST", body: JSON.stringify(payload) }),
}
