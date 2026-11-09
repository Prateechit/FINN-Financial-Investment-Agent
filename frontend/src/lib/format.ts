export const CATEGORY_LABEL: Record<string, string> = {
  results: 'Results', 'M&A': 'M&A', fund_raise: 'Fund raise', management_change: 'Management',
  litigation: 'Legal & regulatory', insider_trading: 'Insider trade', earnings_call: 'Earnings call',
  investor_meetings: 'Investor meets', credit_rating: 'Credit rating', dividend: 'Dividend',
  bonus_split: 'Bonus / split', capex: 'Capex', press_release: 'Company news', postal_ballot: 'Postal ballot',
  agm_egm: 'AGM / EGM', pledging: 'Pledging', unclassified: 'Routine paperwork',
}

export const cat = (c: string) => CATEGORY_LABEL[c] ?? c.replace(/_/g, ' ')

export function crore(v: number | null | undefined): string {
  if (v == null) return '—'
  const a = Math.abs(v)
  if (a >= 100000) return `${(v / 100000).toFixed(2)}L Cr`
  if (a >= 1000) return `${Math.round(v).toLocaleString('en-IN')} Cr`
  return `${v.toFixed(a < 10 ? 1 : 0)} Cr`
}

export function pct(v: number | null | undefined, digits = 1, sign = true): string {
  if (v == null || Number.isNaN(v)) return '—'
  const r = Number(v.toFixed(digits))
  return `${sign && r > 0 ? '+' : ''}${(r === 0 ? 0 : r).toFixed(digits)}%`
}

export function bps(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${v > 0 ? '+' : ''}${v} bps`
}

export function rupee(v: number | null | undefined): string {
  if (v == null) return '—'
  return `₹${v.toLocaleString('en-IN', { maximumFractionDigits: v < 100 ? 2 : 1 })}`
}

export function ago(iso: string): string {
  const t = new Date(iso).getTime()
  const m = Math.round((Date.now() - t) / 60000)
  if (m < 1) return 'now'
  if (m < 60) return `${m}m`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h`
  const d = Math.round(h / 24)
  return d < 7 ? `${d}d` : new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

export function clock(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
}

export const tone = (v: number | null | undefined) => (v == null ? 'text-ink3' : v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-ink2')

export function pageLink(url: string, page?: number | null) {
  return page ? `${url}#page=${page}` : url
}
