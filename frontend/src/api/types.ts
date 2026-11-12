export interface InvestmentAccount {
  id: string
  name: string
  account_type: string
  currency: string
  status: string
  notes: string | null
}

export interface Instrument {
  id: string
  instrument_type: string
  market: string
  exchange: string | null
  code: string
  name: string
  currency: string
  status: string
}

export interface Health {
  status: string
  app: string
  version: string
}
