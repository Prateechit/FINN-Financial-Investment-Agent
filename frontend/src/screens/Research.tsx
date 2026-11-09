import { useEffect, useState } from 'react'
import { Card, Icon, SectionTitle } from '../components/ui'
import { api } from '../lib/api'
import { ago } from '../lib/format'
import { useApi } from '../lib/hooks'

const SUGGESTED = [
  { symbol: 'DIXON', why: 'Revenue +47%, profit −45% — what did management promise?' },
  { symbol: 'ASIANPAINT', why: 'Three flat years — is the recovery story landing?' },
  { symbol: 'PIDILITIND', why: 'Outside the portfolio: a clean compounder' },
  { symbol: 'KPITTECH', why: 'Outside the portfolio: guidance-heavy IT services' },
  { symbol: 'HDFCBANK', why: 'Bank format: NII, provisions, NPAs' },
]

type Hit = { symbol: string; name: string }
const lookup = (query: string) => api<Hit[]>(`/api/search?q=${encodeURIComponent(query)}`)

export default function Research({ go }: { go: (r: string) => void }) {
  const [q, setQ] = useState('')
  // Results are tagged with the exact text they were fetched for, so a slow or out-of-order response can never be
  // shown or opened for different text than what is in the box.
  const [results, setResults] = useState<{ for: string; hits: Hit[] }>({ for: '', hits: [] })
  const [resolving, setResolving] = useState(false)
  const [noMatch, setNoMatch] = useState<string | null>(null)
  const { data: recent } = useApi<{ symbol: string; name?: string; status: string; updated: string; verdicts?: Record<string, number> }[]>('/api/research')
  const query = q.trim()
  const hits = results.for === query ? results.hits : []

  useEffect(() => {
    setNoMatch(null)
    if (!query) { setResults({ for: '', hits: [] }); return }
    const t = setTimeout(() => lookup(query).then((h) => setResults({ for: query, hits: h })).catch(() => setResults({ for: query, hits: [] })), 180)
    return () => clearTimeout(t)
  }, [query])

  // Enter opens the top match for the text as typed — waiting for the search if it hasn't answered yet — and never
  // opens a memo for free text that matched nothing.
  const openTopMatch = async () => {
    if (!query || resolving) return
    let list = results.for === query ? results.hits : null
    if (list === null) {
      setResolving(true)
      try {
        list = await lookup(query)
        setResults({ for: query, hits: list })
      } catch {
        list = []
      } finally {
        setResolving(false)
      }
    }
    if (list[0]) go(`memo/${list[0].symbol}`)
    else setNoMatch(query)
  }

  return (
    <div className="mx-auto max-w-xl px-4 pt-[calc(env(safe-area-inset-top)+16px)]">
      <h1 className="font-serif text-[30px] leading-tight">Research</h1>
      <p className="mt-1 text-[13px] text-ink2">Any NSE company. Built only from its filings, statements and earnings-call transcripts — every claim links to its source.</p>

      <div className="relative mt-4">
        <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-ink3" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Company or NSE symbol"
          onKeyDown={(e) => { if (e.key === 'Enter') openTopMatch() }}
          aria-busy={resolving}
          className="h-12 w-full rounded-xl border border-line bg-card pl-10 pr-3 text-[16px] outline-none placeholder:text-ink3 focus:border-ink3"
          autoCapitalize="characters" autoCorrect="off" spellCheck={false} />
        {hits.length > 0 && (
          <Card className="absolute inset-x-0 top-14 z-20 max-h-80 overflow-y-auto shadow-lg">
            {hits.map((h) => (
              <button key={h.symbol} onClick={() => go(`memo/${h.symbol}`)} className="flex w-full items-baseline gap-3 border-t border-line px-4 py-2.5 text-left first:border-t-0 active:bg-sunk">
                <span className="w-24 shrink-0 text-[13px] font-bold">{h.symbol}</span>
                <span className="truncate text-[13px] text-ink2">{h.name}</span>
              </button>
            ))}
          </Card>
        )}
      </div>
      {resolving && <p className="mt-2 px-1 text-[12.5px] text-ink3">Finding the NSE symbol…</p>}
      {noMatch && !resolving && (
        <p className="mt-2 px-1 text-[12.5px] text-down" role="alert">
          No NSE-listed company matches “{noMatch}”. Try the ticker symbol, e.g. TATATECH.
        </p>
      )}

      {!!recent?.length && (
        <>
          <SectionTitle>Your memos</SectionTitle>
          <Card>
            {recent.map((r) => (
              <button key={r.symbol} onClick={() => go(`memo/${r.symbol}`)} className="flex w-full items-center gap-3 border-t border-line px-4 py-3 text-left first:border-t-0 active:bg-sunk">
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-semibold">{r.symbol} <span className="font-normal text-ink3">· {r.name}</span></div>
                  {r.verdicts && (
                    <div className="num mt-0.5 text-[12px] text-ink2">
                      {r.verdicts.delivered ?? 0} delivered · {(r.verdicts.missed ?? 0) + (r.verdicts.goalposts_moved ?? 0) + (r.verdicts.dropped ?? 0)} missed, moved or dropped
                    </div>
                  )}
                </div>
                <span className="text-[12px] text-ink3">{r.status === 'running' ? 'building…' : ago(r.updated)}</span>
                <Icon name="chev" className="size-4 text-ink3" />
              </button>
            ))}
          </Card>
        </>
      )}

      <SectionTitle>Start here</SectionTitle>
      <Card>
        {SUGGESTED.map((s) => (
          <button key={s.symbol} onClick={() => go(`memo/${s.symbol}`)} className="flex w-full items-center gap-3 border-t border-line px-4 py-3 text-left first:border-t-0 active:bg-sunk">
            <div className="flex-1">
              <div className="text-[14px] font-semibold">{s.symbol}</div>
              <div className="text-[12.5px] text-ink2">{s.why}</div>
            </div>
            <Icon name="chev" className="size-4 text-ink3" />
          </button>
        ))}
      </Card>
      <div className="h-24" />
    </div>
  )
}
