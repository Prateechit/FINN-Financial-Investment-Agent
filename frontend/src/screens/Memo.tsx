import { useEffect, useState } from 'react'
import { BarLine, PairBars } from '../components/Charts'
import { Card, Chip, ExtLink, Icon, SectionTitle, Sheet, Skeleton } from '../components/ui'
import { api, type Fact, type LedgerRow, type Research, type ThesisPoint, type Verdict } from '../lib/api'
import { crore, pageLink, pct, tone } from '../lib/format'
import { useInterval } from '../lib/hooks'

const VERDICT: Record<Verdict, { label: string; cls: string; bar: string }> = {
  delivered: { label: 'Delivered', cls: 'bg-up/12 text-up', bar: 'var(--up)' },
  on_track: { label: 'On track', cls: 'bg-accent-soft text-accent', bar: 'var(--accent)' },
  at_risk: { label: 'At risk', cls: 'bg-note-soft text-note', bar: 'var(--note)' },
  goalposts_moved: { label: 'Goalposts moved', cls: 'bg-note-soft text-note', bar: '#d97706' },
  missed: { label: 'Missed', cls: 'bg-down/12 text-down', bar: 'var(--down)' },
  dropped: { label: 'Quietly dropped', cls: 'bg-crit-soft text-crit', bar: 'var(--crit)' },
  too_early: { label: 'Too early', cls: 'bg-sunk text-ink2', bar: 'var(--ink3)' },
  unverifiable: { label: 'Can’t verify', cls: 'bg-sunk text-ink3', bar: 'var(--line)' },
}

const STANCE: Record<string, { g: string; c: string; t: string }> = {
  set: { g: '●', c: 'text-ink', t: 'First guided' },
  reiterated: { g: '●', c: 'text-ink2', t: 'Reiterated' },
  raised: { g: '▲', c: 'text-up', t: 'Raised' },
  lowered: { g: '▼', c: 'text-down', t: 'Lowered' },
  softened: { g: '◐', c: 'text-note', t: 'Softened' },
  silent: { g: '○', c: 'text-ink3/50', t: 'Not mentioned' },
}

const shortCall = (c: string) => c.replace(' FY', "·")

function FactLine({ f }: { f: Fact }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-line py-2 text-[13px] first:border-t-0">
      <span className="text-ink2">{f.label} <span className="text-ink3">· {f.period}</span></span>
      <span className="num shrink-0 font-semibold">{f.unit === '₹ Cr' ? crore(f.value) : `${f.value}${f.unit === '%' ? '%' : f.unit === 'x' ? '×' : ` ${f.unit}`}`}</span>
    </div>
  )
}

function Quote({ text, call, page, url, speaker }: { text: string; call?: string; page?: number; url?: string; speaker?: string }) {
  return (
    <figure className="border-l-2 border-accent/60 pl-3">
      <blockquote className="font-serif text-[15.5px] leading-snug">“{text}”</blockquote>
      <figcaption className="mt-1 text-[12px] text-ink3">
        {[speaker, call && `${call} call`].filter(Boolean).join(' · ')}
        {url && <> · <ExtLink href={pageLink(url, page)}>transcript p.{page}</ExtLink></>}
      </figcaption>
    </figure>
  )
}

function LedgerSection({ r, open }: { r: Research; open: (row: LedgerRow) => void }) {
  const L = r.sections.ledger
  const g = r.sections.guidance
  if (!L) return null
  if (L.status !== 'ok') return <Card className="p-4 text-[13.5px] text-ink2">{L.note ?? 'Not enough verifiable guidance to audit.'}</Card>
  const counts = L.counts ?? ({} as Record<Verdict, number>)
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1
  const dropped = g?.calls.reduce((a, c) => a + (c.dropped_unverified ?? 0), 0) ?? 0
  const downgraded = L.rows.filter((x) => x.downgraded_from).length
  return (
    <>
      {L.credibility && <p className="px-1 font-serif text-[19px] leading-snug">{L.credibility}</p>}
      <div className="mt-3 flex h-2.5 overflow-hidden rounded-full bg-sunk">
        {(Object.keys(VERDICT) as Verdict[]).map((v) => counts[v] ? <div key={v} style={{ width: `${(counts[v] / total) * 100}%`, background: VERDICT[v].bar }} title={`${VERDICT[v].label}: ${counts[v]}`} /> : null)}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 px-1 text-[12px] text-ink2">
        {(Object.keys(VERDICT) as Verdict[]).filter((v) => counts[v]).map((v) => (
          <span key={v} className="num"><span className="mr-1 inline-block size-2 rounded-full align-middle" style={{ background: VERDICT[v].bar }} />{VERDICT[v].label} {counts[v]}</span>
        ))}
      </div>
      <div className="mt-3 space-y-2.5">
        {L.rows.map((row) => (
          <Card key={row.subject} className="p-3.5 active:bg-sunk" onClick={() => open(row)}>
            <div className="flex items-start justify-between gap-2">
              <div className="text-[14.5px] font-semibold leading-snug">{row.subject}</div>
              <span className={`shrink-0 rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${VERDICT[row.verdict].cls}`}>{VERDICT[row.verdict].label}</span>
            </div>
            <div className="mt-1 text-[13px] text-ink2"><span className="text-ink3">Promised:</span> {row.promise}</div>
            {row.delivered && <div className="mt-0.5 text-[13px] text-ink"><span className="text-ink3">Actual:</span> {row.delivered}</div>}
            <div className="mt-2.5 flex items-center gap-0.5">
              {row.timeline.map((t, i) => (
                <div key={t.call} className="flex flex-1 flex-col items-center" title={`${t.call}: ${STANCE[t.stance]?.t ?? t.stance}`}>
                  <div className="flex w-full items-center">
                    <span className={`h-px flex-1 ${i === 0 ? 'opacity-0' : 'bg-line'}`} />
                    <span className={`text-[13px] leading-none ${STANCE[t.stance]?.c ?? 'text-ink3'}`}>{STANCE[t.stance]?.g ?? '●'}</span>
                    <span className={`h-px flex-1 ${i === row.timeline.length - 1 ? 'opacity-0' : 'bg-line'}`} />
                  </div>
                  <span className="mt-1 text-[10px] text-ink3">{shortCall(t.call)}</span>
                </div>
              ))}
            </div>
            {!row.grounded && <div className="mt-2 text-[11.5px] text-note">⚠ Wording contains a figure FINN couldn’t trace to the sources — check the evidence.</div>}
          </Card>
        ))}
      </div>
      <p className="mt-3 px-1 text-[11.5px] leading-relaxed text-ink3">
        ● guided · ▲ raised · ▼ lowered · ◐ softened · ○ not mentioned on that call. Verdicts compare management’s verbatim guidance with reported figures only.
        {dropped > 0 && ` ${dropped} extracted statement${dropped > 1 ? 's were' : ' was'} discarded because the wording couldn’t be found verbatim in the transcript or wasn’t forward-looking.`}
        {downgraded > 0 && ` ${downgraded} model verdict${downgraded > 1 ? 's were' : ' was'} corrected by FINN’s evidence checks.`}
      </p>
    </>
  )
}

function ThesisCol({ title, points, cls, onRef }: { title: string; points: ThesisPoint[]; cls: string; onRef: (p: ThesisPoint) => void }) {
  return (
    <div>
      <div className={`mb-2 text-[12px] font-semibold uppercase tracking-wider ${cls}`}>{title}</div>
      <ol className="space-y-2.5">
        {points.map((p, i) => (
          <li key={i} className="flex gap-2.5 text-[14px] leading-snug">
            <span className={`num mt-px text-[12px] font-bold ${cls}`}>{i + 1}</span>
            <div>
              {p.point}
              <button onClick={() => onRef(p)} className="ml-1.5 inline-flex rounded bg-sunk px-1.5 text-[11px] font-medium text-ink2 active:bg-line">
                {p.refs.length} source{p.refs.length === 1 ? '' : 's'}
              </button>
              {!p.grounded && <span className="ml-1 text-[11px] text-note">⚠ unverified</span>}
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

function Evidence({ items }: { items: ThesisPoint['evidence'] }) {
  return (
    <div className="space-y-3">
      {items.map((e, i) => {
        const x = e as unknown as Record<string, string & number & undefined>
        if (e.type === 'guidance') return <Quote key={i} text={x.statement} call={x.call} page={x.page} url={x.url} speaker={x.speaker} />
        if (e.type === 'analyst') return <div key={i}><div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink3">Analyst question · {x.topic}</div><Quote text={x.quote} call={x.call} page={x.page} url={x.url} /></div>
        if (e.type === 'signal') return <div key={i} className="rounded-lg bg-sunk p-2.5 text-[13px]">{x.text}</div>
        if (e.type === 'ledger') return <div key={i} className="rounded-lg bg-sunk p-2.5 text-[13px]">Promise Ledger: <b>{x.subject}</b> — {VERDICT[x.verdict as Verdict]?.label}</div>
        if (e.type === 'fact') return <FactLine key={i} f={e as unknown as Fact} />
        return null
      })}
    </div>
  )
}

const NAV = [['ledger', 'Promise Ledger'], ['thesis', 'Bull / Bear'], ['snapshot', 'Snapshot'], ['trajectory', 'Trajectory'], ['balance', 'Balance sheet'], ['cash', 'Cash'], ['sources', 'Sources']]

export default function Memo({ symbol, go }: { symbol: string; go: (r: string) => void }) {
  const [r, setData] = useState<Research | undefined>()
  const [row, setRow] = useState<LedgerRow | null>(null)
  const [refs, setRefs] = useState<ThesisPoint | null>(null)
  const error = null

  useEffect(() => {
    setData(undefined)
    api<Research>(`/api/research/${symbol}`, { method: 'POST' }).then(setData)
      .catch((e) => setData({ symbol, status: 'error', stage: '', updated: '', errors: [String(e.message)], sections: {} }))
  }, [symbol])
  useInterval(() => {
    api<Research>(`/api/research/${symbol}`).then(setData).catch(() => {})
  }, r?.status === 'running' ? 2000 : null)

  const s = r?.sections ?? {}
  const snap = s.snapshot
  const traj = s.trajectory
  const running = r?.status === 'running'
  const refresh = () => api<Research>(`/api/research/${symbol}?force=true`, { method: 'POST' }).then(setData)

  return (
    <div className="mx-auto max-w-xl pt-[calc(env(safe-area-inset-top)+8px)]">
      <div className="flex items-center gap-1 px-2">
        <button onClick={() => history.length > 1 ? history.back() : go('research')} className="rounded-full p-2 text-ink2 active:bg-sunk" aria-label="Back"><Icon name="back" /></button>
        <div className="text-[13px] font-semibold text-ink2">{symbol}</div>
        {r && !running && <button onClick={refresh} className="ml-auto px-2 text-[12.5px] font-medium text-accent">Rebuild</button>}
      </div>

      <div className="px-4">
        {snap ? (
          <>
            <h1 className="font-serif text-[28px] leading-tight">{snap.name}</h1>
            <div className="mt-0.5 text-[13px] text-ink2">{snap.sector} · {snap.basis} · {snap.price}</div>
            <div className="num mt-3 grid grid-cols-4 gap-1.5 text-center">
              {[['Mkt cap', snap.market_cap ? `₹${crore(Number(snap.market_cap.replace(/[^\d.]/g, '')))}` : undefined], ['P/E', snap.pe], [snap.lender ? 'ROE' : 'ROCE', snap.lender ? snap.roe : snap.roce], ['Div yield', snap.dividend_yield]].map(([k, v]) => (
                <div key={k} className="rounded-lg bg-card px-1 py-2 ring-1 ring-line">
                  <div className="truncate text-[13px] font-semibold">{v ?? '—'}</div>
                  <div className="text-[10.5px] text-ink3">{k}</div>
                </div>
              ))}
            </div>
          </>
        ) : r?.status === 'error' ? (
          <Card className="mt-4 p-4 text-[14px]"><b>Couldn’t research {symbol}.</b><div className="mt-1 text-ink2">{r.errors[0]}</div></Card>
        ) : <><Skeleton className="mt-2 h-9 w-2/3" /><Skeleton className="mt-3 h-14" /></>}
        {error && <div className="mt-3 text-[13px] text-down">{error}</div>}

        {running && (
          <div className="mt-4 rounded-xl bg-accent-soft p-3">
            <div className="flex items-center gap-2 text-[13px] font-medium text-accent">
              <span className="size-2 animate-pulse rounded-full bg-accent" />{r?.stage || 'Working'}…
            </div>
            <div className="mt-1 text-[12px] text-ink2">Numbers appear first; the ledger needs every transcript read once (then it’s cached).</div>
          </div>
        )}
        {r?.status === 'partial' && r.errors.length > 0 && (
          <div className="mt-4 rounded-xl bg-note-soft p-3 text-[12.5px] text-ink">{r.errors.join(' ')}</div>
        )}
      </div>

      {snap && (
        <div className="no-scrollbar sticky top-0 z-30 mt-3 flex gap-1.5 overflow-x-auto border-b border-line bg-bg/90 px-4 py-2 backdrop-blur">
          {NAV.map(([id, label]) => <Chip key={id} onClick={() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })}>{label}</Chip>)}
        </div>
      )}

      <div className="px-4">
        <SectionTitle id="ledger" right={s.ledger?.calls && <span className="text-[11.5px] text-ink3">{s.ledger.calls.length} calls</span>}>Promise Ledger — said vs did</SectionTitle>
        {s.ledger ? <LedgerSection r={r!} open={setRow} /> : running ? <Skeleton className="h-48" /> : <Card className="p-4 text-[13px] text-ink2">Appears once transcripts are read.</Card>}

        <SectionTitle id="thesis">Bull vs bear</SectionTitle>
        {s.thesis ? (
          <Card className="space-y-5 p-4">
            <ThesisCol title="Bull" points={s.thesis.bull} cls="text-up" onRef={setRefs} />
            <ThesisCol title="Bear" points={s.thesis.bear} cls="text-down" onRef={setRefs} />
            {s.thesis.watch && (
              <div className="rounded-xl bg-sunk p-3">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-ink3">What settles it next quarter</div>
                <div className="mt-1 text-[14px]">{s.thesis.watch.point}</div>
              </div>
            )}
          </Card>
        ) : running ? <Skeleton className="h-40" /> : <Card className="p-4 text-[13px] text-ink2">Written after the ledger.</Card>}

        {s.signals && s.signals.length > 0 && (
          <>
            <SectionTitle>What the numbers say</SectionTitle>
            <Card className="divide-y divide-line">
              {s.signals.map((g) => (
                <div key={g.text} className="flex gap-2.5 px-4 py-3 text-[13.5px] leading-snug">
                  <span className={`mt-1.5 size-2 shrink-0 rounded-full ${g.tone === 'good' ? 'bg-up' : g.tone === 'bad' ? 'bg-down' : 'bg-ink3'}`} />
                  <span>{g.text}</span>
                </div>
              ))}
            </Card>
          </>
        )}

        <SectionTitle id="snapshot">Business snapshot</SectionTitle>
        {snap ? (
          <Card className="p-4">
            {s.business?.from_transcript?.summary ? (
              <>
                <p className="text-[14px] leading-relaxed">{s.business.from_transcript.summary}</p>
                {!!s.business.from_transcript.segments?.length && (
                  <div className="mt-3 space-y-1.5">
                    {s.business.from_transcript.segments.map((g) => (
                      <div key={g.name} className="text-[13px]"><span className="font-semibold">{g.name}</span> <span className="text-ink2">— {g.detail}</span></div>
                    ))}
                  </div>
                )}
                <div className="mt-2 text-[11.5px] text-ink3">In management’s framing, {s.business.source_call} call · {s.business.source_url && <ExtLink href={s.business.source_url}>transcript</ExtLink>}</div>
              </>
            ) : <p className="text-[13.5px] text-ink2">{snap.about}<span className="mt-1 block text-[11.5px] text-ink3">Profile from screener.in (management framing appears once transcripts are read).</span></p>}
            <div className="num mt-4 grid grid-cols-3 gap-2 border-t border-line pt-3 text-center">
              <div><div className="text-[15px] font-semibold">{crore(snap.ttm_revenue)}</div><div className="text-[11px] text-ink3">TTM revenue</div></div>
              <div><div className="text-[15px] font-semibold">{crore(snap.ttm_pat)}</div><div className="text-[11px] text-ink3">TTM profit</div></div>
              <div><div className="text-[15px] font-semibold">{snap.ttm_margin != null ? `${snap.ttm_margin}%` : snap.roe}</div><div className="text-[11px] text-ink3">{snap.ttm_margin != null ? 'Operating margin' : 'ROE'}</div></div>
            </div>
          </Card>
        ) : <Skeleton className="h-32" />}

        {traj && (
          <>
            <SectionTitle id="trajectory">Trajectory</SectionTitle>
            <Card className="p-4">
              <BarLine labels={traj.annual.map((a) => a.period)} bars={traj.annual.map((a) => a.revenue)} line={traj.annual.map((a) => a.margin)}
                barLabel="Revenue" lineLabel={traj.margin_label} />
              <div className="num mt-3 flex flex-wrap gap-1.5 text-[12px]">
                {[['3y', 'revenue_3y', 'pat_3y'], ['5y', 'revenue_5y', 'pat_5y'], ['10y', 'revenue_10y', 'pat_10y']].map(([l, a, b]) => traj.cagr[a] != null && (
                  <span key={l} className="rounded-lg bg-sunk px-2 py-1">{l} CAGR: sales <b className={tone(traj.cagr[a])}>{pct(traj.cagr[a], 1, false)}</b> · profit <b className={tone(traj.cagr[b])}>{pct(traj.cagr[b], 1, false)}</b></span>
                ))}
                {traj.ytd && <span className="rounded-lg bg-accent-soft px-2 py-1 text-accent">{traj.ytd.label}: sales {pct(traj.ytd.growth)}</span>}
              </div>
              <table className="num mt-4 w-full text-[12.5px]">
                <thead><tr className="text-[11px] text-ink3"><th className="text-left font-medium">Quarter</th><th className="text-right font-medium">Revenue</th><th className="text-right font-medium">YoY</th><th className="text-right font-medium">Margin</th><th className="text-right font-medium">PAT YoY</th></tr></thead>
                <tbody>
                  {traj.quarterly.slice(-6).map((q) => (
                    <tr key={q.period} className="border-t border-line/70">
                      <td className="py-1.5 text-ink2">{q.period}</td>
                      <td className="text-right">{q.revenue?.toLocaleString('en-IN') ?? '—'}</td>
                      <td className={`text-right ${tone(q.revenue_yoy)}`}>{pct(q.revenue_yoy, 0)}</td>
                      <td className="text-right">{q.margin != null ? `${q.margin}%` : '—'}</td>
                      <td className={`text-right font-medium ${tone(q.pat_yoy)}`}>{pct(q.pat_yoy, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </>
        )}

        {s.balance_sheet && s.balance_sheet.rows.length > 0 && (
          <>
            <SectionTitle id="balance">Balance sheet</SectionTitle>
            <Card className="p-4">
              <PairBars labels={s.balance_sheet.rows.slice(-6).map((b) => b.period.replace(/^\w+ /, "'").replace("'20", "'"))}
                a={s.balance_sheet.rows.slice(-6).map((b) => b.net_worth)} b={s.balance_sheet.rows.slice(-6).map((b) => b.debt)}
                aLabel="Net worth" bLabel={s.balance_sheet.borrow_label} />
              <div className="num mt-2 flex flex-wrap gap-1.5 text-[12px]">
                {s.balance_sheet.rows.slice(-3).map((b) => <span key={b.period} className="rounded-lg bg-sunk px-2 py-1">{b.period}: D/E <b>{b.de ?? '—'}×</b></span>)}
              </div>
              {s.balance_sheet.working_capital.some((w) => w.ccc != null) && (
                <table className="num mt-4 w-full text-[12.5px]">
                  <thead><tr className="text-[11px] text-ink3"><th className="text-left font-medium">Days</th>{s.balance_sheet.working_capital.slice(-4).map((w) => <th key={w.period} className="text-right font-medium">{w.period.replace('Mar ', 'FY').replace('FY20', 'FY')}</th>)}</tr></thead>
                  <tbody>
                    {([['Receivables', 'debtor_days'], ['Inventory', 'inventory_days'], ['Payables', 'payable_days'], ['Cash cycle', 'ccc']] as const).map(([l, k]) => (
                      <tr key={k} className="border-t border-line/70">
                        <td className={`py-1.5 ${k === 'ccc' ? 'font-semibold' : 'text-ink2'}`}>{l}</td>
                        {s.balance_sheet!.working_capital.slice(-4).map((w) => <td key={w.period} className={`text-right ${k === 'ccc' ? 'font-semibold' : ''}`}>{w[k] ?? '—'}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </>
        )}

        {s.cash && s.cash.rows.length > 0 && !snap?.lender && (
          <>
            <SectionTitle id="cash" right={s.cash.cfo_pat_5y != null && <span className="num text-[12px] text-ink2">5y cash conversion <b className={s.cash.cfo_pat_5y >= 90 ? 'text-up' : s.cash.cfo_pat_5y < 70 ? 'text-down' : ''}>{s.cash.cfo_pat_5y}%</b></span>}>Cash quality</SectionTitle>
            <Card className="p-4">
              <PairBars labels={s.cash.rows.slice(-6).map((c) => c.period.replace('Mar 20', 'FY'))} a={s.cash.rows.slice(-6).map((c) => c.cfo)} b={s.cash.rows.slice(-6).map((c) => c.pat)}
                aLabel="Operating cash flow" bLabel="Reported profit" />
              <div className="num mt-2 grid grid-cols-3 gap-1.5 text-center text-[12px]">
                {s.cash.rows.slice(-3).map((c) => (
                  <div key={c.period} className="rounded-lg bg-sunk py-1.5">
                    <div className="font-semibold">{c.cfo_pat ?? '—'}%</div>
                    <div className="text-[10.5px] text-ink3">CFO/PAT {c.period.replace('Mar 20', 'FY')}</div>
                    <div className="text-[10.5px] text-ink3">FCF {crore(c.fcf)}</div>
                  </div>
                ))}
              </div>
            </Card>
          </>
        )}

        {!!s.business?.analyst_focus?.length && (
          <>
            <SectionTitle>What analysts pressed on</SectionTitle>
            <Card className="space-y-4 p-4">
              {s.business.analyst_focus.map((f) => (
                <div key={f.quote}><div className="mb-1 text-[12px] font-semibold">{f.topic}</div><Quote text={f.quote} call={f.call} page={f.page} url={f.url} /></div>
              ))}
            </Card>
          </>
        )}

        {s.sources && (
          <>
            <SectionTitle id="sources">Sources & cost</SectionTitle>
            <Card className="p-4 text-[13px]">
              <div className="space-y-1.5">
                {s.guidance?.calls.map((c) => (
                  <div key={c.call} className="flex items-baseline justify-between gap-2">
                    <ExtLink href={c.url}>{c.call} earnings call</ExtLink>
                    <span className="num text-[12px] text-ink3">{c.error ? 'unreadable' : `${c.pages ?? '?'} pp · ${c.n} promises kept${c.dropped_unverified ? `, ${c.dropped_unverified} discarded` : ''}`}</span>
                  </div>
                ))}
                <div className="flex justify-between"><ExtLink href={s.sources.statements}>Standardised statements</ExtLink><span className="text-[12px] text-ink3">screener.in · from filings</span></div>
                {s.sources.annual_reports.slice(0, 2).map((a) => <div key={a.year}><ExtLink href={a.url}>Annual report {a.year}</ExtLink></div>)}
              </div>
              {r?.usage && (
                <div className="num mt-3 rounded-lg bg-sunk p-2.5 text-[12px] text-ink2">
                  {r.usage.calls} model calls ({r.usage.cache_hits} from cache) · {(r.usage.tokens_in / 1000).toFixed(1)}k tokens in, {(r.usage.tokens_out / 1000).toFixed(1)}k out
                  {r.usage.models.length > 0 && <div className="mt-0.5 text-ink3">{r.usage.models.join(' · ')}</div>}
                </div>
              )}
              <p className="mt-2 text-[11.5px] text-ink3">Primary sources only — no news, broker notes or model memory. Numbers are computed in code; the model only judges and writes, and every figure it writes is checked against the sources.</p>
            </Card>
          </>
        )}
        <div className="h-24" />
      </div>

      <Sheet open={!!row} onClose={() => setRow(null)} title={row?.subject}>
        {row && (
          <div className="space-y-4 pb-2">
            <div className="flex items-center gap-2">
              <span className={`rounded-md px-1.5 py-0.5 text-[12px] font-semibold ${VERDICT[row.verdict].cls}`}>{VERDICT[row.verdict].label}</span>
              {row.downgraded_from && <span className="text-[12px] text-ink3">(model said “{row.downgraded_from}”; corrected by FINN’s evidence check)</span>}
            </div>
            <p className="text-[14px] leading-relaxed">{row.why}</p>
            <div>
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink3">What management said</div>
              <div className="space-y-3">{row.evidence.map((g) => <Quote key={g.id} text={g.statement} call={g.call} page={g.page} url={g.url} speaker={g.speaker} />)}</div>
            </div>
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink3">What was reported</div>
              {row.facts.length ? row.facts.map((f) => <FactLine key={f.id} f={f} />) : <div className="text-[13px] text-ink3">No reported figure bears on this yet.</div>}
              {row.facts[0] && <div className="mt-1 text-[11.5px] text-ink3">Source: <ExtLink href={row.facts[0].url}>{row.facts[0].source}</ExtLink></div>}
            </div>
          </div>
        )}
      </Sheet>
      <Sheet open={!!refs} onClose={() => setRefs(null)} title="Evidence">
        {refs && <><p className="mb-4 text-[14px] font-medium">{refs.point}</p><Evidence items={refs.evidence} /></>}
      </Sheet>
    </div>
  )
}
