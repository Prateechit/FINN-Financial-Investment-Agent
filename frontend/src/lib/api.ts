const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!r.ok) throw new Error(`${r.status} ${await r.text().catch(() => '')}`.slice(0, 200))
  return r.json() as Promise<T>
}

export type Tier = 'critical' | 'notable' | 'routine'

export interface ResultsRow { key: string; label: string; cur: number | null; prev: number | null; yoy: number | null; qoq_pct: number | null; yoy_pct: number | null }
export interface MarginRow { label: string; cur: number | null; prev: number | null; yoy: number | null; qoq_bps: number | null; yoy_bps: number | null }
export interface ResultsCard {
  kind: 'industrial' | 'bank' | 'lender'; basis: string; source: string; links: string[]; notes: string[]
  checks: { name: string; ok: boolean; detail: string }[]
  quarter: { label: string; end: string }; prev_label: string; yoy_label: string
  rows: ResultsRow[]; margins: MarginRow[]; headline: string
}
export interface MgmtChange {
  person: string; role: string; change: string; effective_date?: string | null; reason?: string | null
  profile?: string | null; highlights?: string[]; profile_verified?: boolean; page?: number | null
}
export interface Enrichment {
  type: string; status: string; card?: ResultsCard; changes?: MgmtChange[]; line?: string
  expected_quarter?: string; note?: string; source?: { url: string; pages: number }
}
export interface Story {
  id: string; symbol: string; name: string; category: string; tier: Tier; materiality: number; reasons: string[]
  ts: string; title: string; subject?: string | null; summary?: string | null; text: string; exch_category: string
  pdf_url?: string | null; enrichment?: Enrichment | null; reaction?: { date: string; pct: number } | null
  related: { id: string; ts: string; exch_category: string; text: string; pdf_url?: string | null }[]
}
export interface Digest {
  window_hours: number; since: string; generated: string
  counts: { filings: number; stories: number; critical: number; notable: number; routine: number }
  stories: Story[]; routine: { category: string; count: number; items: Story[] }[]
}
export interface Holding {
  symbol: string; name: string; sector: string; weight: number; close: number | null; date: string | null
  change_pct: number | null; spark: number[]; material_7d: number
}
export interface Alert {
  id: string; kind: 'price' | 'volume' | 'announcement'; symbol: string; date: string; title: string
  ret_pct?: number; sigma?: number | null; vol_mult?: number | null; close?: number; threshold?: number
  linked?: { id: string; category: string; ts: string; text: string }; category?: string; materiality?: number
  text?: string; announcement_id?: string; ts?: string
}
export interface Settings {
  window_hours: number; price_move_pct: number; price_move_sigma: number; volume_multiple: number
  volume_lookback_days: number; alert_categories: string[]; min_alert_materiality: number
}
export interface Fact { id: string; label: string; value: number; unit: string; period: string; source: string; url: string }
export interface Guidance {
  id: string; metric: string; subject?: string; statement: string; target?: string; horizon?: string; kind?: string
  speaker?: string; page: number; call: string; call_label: string; url: string
}
export type Verdict = 'delivered' | 'missed' | 'on_track' | 'at_risk' | 'goalposts_moved' | 'dropped' | 'too_early' | 'unverifiable'
export interface LedgerRow {
  subject: string; metric: string; promise: string; guidance_ids: string[]; delivered: string; fact_ids: string[]
  verdict: Verdict; why: string; grounded: boolean; downgraded_from?: string
  timeline: { call: string; stance: string; guidance_id?: string }[]; evidence: Guidance[]; facts: Fact[]
}
export interface ThesisPoint { point: string; refs: string[]; grounded: boolean; evidence: (Record<string, unknown> & { type: string })[] }
export interface Research {
  symbol: string; status: 'running' | 'done' | 'partial' | 'error'; stage: string; updated: string; errors: string[]
  usage?: { calls: number; cache_hits: number; tokens_in: number; tokens_out: number; models: string[] }
  sections: {
    snapshot?: {
      name: string; symbol: string; sector: string; basis: string; lender: boolean; market_cap?: string; price?: string
      pe?: string; roce?: string; roe?: string; dividend_yield?: string; book_value?: string; high_low?: string
      ttm_revenue?: number; ttm_pat?: number; ttm_margin?: number | null; about?: string; url: string
    }
    trajectory?: {
      annual: { period: string; col: string; revenue: number | null; op_profit: number | null; margin: number | null; pat: number | null }[]
      quarterly: { period: string; revenue: number | null; revenue_yoy: number | null; margin: number | null; pat: number | null; pat_yoy: number | null }[]
      cagr: Record<string, number | null>; ytd: { label: string; revenue: number; prior: number; growth: number } | null; margin_label: string
    }
    balance_sheet?: {
      rows: { period: string; net_worth: number; debt: number | null; de: number | null; deposits: number | null }[]
      working_capital: { period: string; debtor_days: number | null; inventory_days: number | null; payable_days: number | null; ccc: number | null; wc_days: number | null; roce: number | null }[]
      borrow_label: string
    }
    cash?: { rows: { period: string; cfo: number | null; fcf: number | null; capex: number | null; pat: number | null; cfo_pat: number | null }[]; cfo_pat_5y: number | null }
    signals?: { tone: 'good' | 'bad' | 'neutral'; text: string; facts: string[]; evidence?: Fact[] }[]
    guidance?: { calls: { call: string; label: string; url: string; pages?: number; n: number; dropped_unverified?: number; error?: string }[]; items: Guidance[] }
    business?: {
      from_transcript?: { summary?: string; segments?: { name: string; detail: string }[] } | null
      source_call?: string; source_url?: string
      analyst_focus?: { topic: string; quote: string; page: number; url: string; call: string }[]
    }
    ledger?: { status: string; rows: LedgerRow[]; credibility?: string; counts?: Record<Verdict, number>; calls?: string[]; warnings?: string[]; note?: string }
    thesis?: { bull: ThesisPoint[]; bear: ThesisPoint[]; watch: ThesisPoint | null }
    sources?: { statements: string; annual_reports: { year: number; url: string }[]; concalls: { label: string; transcript: string; ppt?: string }[] }
  }
}
export interface CompanyView {
  symbol: string; name: string | null; in_portfolio: boolean; weight: number | null; results: ResultsCard | null
  prices: { d: string; c: number; v: number }[]
  announcements: { id: string; ts: string; category: string; tier: Tier; materiality: number; title: string; pdf_url?: string }[]
}
