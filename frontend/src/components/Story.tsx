import { useRef, useState } from 'react'
import type { MgmtChange, ResultsCard, Story } from '../lib/api'
import { ago, bps, cat, clock, crore, pageLink, pct, tone } from '../lib/format'
import { Card, ExtLink, Icon, Pill, Sheet, TierBar } from './ui'

export function ResultsTable({ card, compact = false }: { card: ResultsCard; compact?: boolean }) {
  const rows = compact ? card.rows.filter((r) => ['revenue', 'ebitda', 'nii', 'pbt', 'pat'].includes(r.key)) : card.rows
  const failed = card.checks.filter((c) => !c.ok)
  return (
    <div>
      <table className="num w-full text-[13px]">
        <thead>
          <tr className="text-[11px] text-ink3">
            <th className="py-1 text-left font-medium">{card.quarter.label}</th>
            <th className="py-1 text-right font-medium">₹ Cr</th>
            <th className="py-1 text-right font-medium">QoQ</th>
            <th className="py-1 text-right font-medium">YoY</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-line/70">
              <td className="py-1.5 text-ink2">{r.label}</td>
              <td className="py-1.5 text-right font-medium">{crore(r.cur).replace(' Cr', '')}</td>
              <td className={`py-1.5 text-right ${tone(r.qoq_pct)}`}>{pct(r.qoq_pct, 0)}</td>
              <td className={`py-1.5 text-right font-semibold ${tone(r.yoy_pct)}`}>{pct(r.yoy_pct, 0)}</td>
            </tr>
          ))}
          {card.margins.slice(0, compact ? 1 : 2).map((m) => (
            <tr key={m.label} className="border-t border-line/70">
              <td className="py-1.5 text-ink2">{m.label}</td>
              <td className="py-1.5 text-right font-medium">{m.cur == null ? '—' : `${m.cur}%`}</td>
              <td className={`py-1.5 text-right ${tone(m.qoq_bps)}`}>{bps(m.qoq_bps).replace(' bps', '')}</td>
              <td className={`py-1.5 text-right font-semibold ${tone(m.yoy_bps)}`}>{bps(m.yoy_bps)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {card.notes.length > 0 && (
        <div className="mt-2 rounded-lg bg-note-soft px-2.5 py-2 text-[12.5px] leading-snug text-ink">
          {card.notes.map((n) => <p key={n}>{n}</p>)}
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-ink3">
        <span>{card.basis} · {card.source}</span>
        {failed.length === 0 && card.checks.length > 0 && (
          <span className="inline-flex items-center gap-0.5 text-up"><Icon name="check" className="size-3.5" />{card.checks.length} checks passed</span>
        )}
        {failed.map((c) => <span key={c.name} className="text-note" title={c.detail}>⚠ {c.name.replace('matches', '≠')}: {c.detail}</span>)}
        {card.kind !== 'industrial' && <span>{card.kind === 'bank' ? 'Bank' : 'Lender'} format — EBITDA not meaningful</span>}
      </div>
    </div>
  )
}

function MgmtBlock({ changes, src }: { changes: MgmtChange[]; src?: { url: string } }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="space-y-3">
      {changes.map((c) => (
        <div key={c.person + c.role}>
          <div className="flex items-start gap-2.5">
            <div className="grid size-9 shrink-0 place-items-center rounded-full bg-accent-soft text-[13px] font-semibold text-accent">
              {c.person.replace(/^(mr|ms|mrs|dr|shri|smt)\.?\s+/i, '').split(/\s+/).map((p) => p[0]).slice(0, 2).join('')}
            </div>
            <div className="min-w-0">
              <div className="text-[14px] font-semibold leading-tight">{c.person}</div>
              <div className="text-[12.5px] text-ink2">
                <span className="capitalize">{c.change}</span> · {c.role}{c.effective_date ? ` · w.e.f. ${c.effective_date}` : ''}
              </div>
            </div>
          </div>
          {!!c.highlights?.length && (
            <ul className="mt-2 space-y-1 pl-[46px] text-[13px] text-ink">
              {c.highlights.slice(0, 3).map((h) => <li key={h} className="relative before:absolute before:-left-3 before:text-ink3 before:content-['–']">{h}</li>)}
            </ul>
          )}
          {c.profile && (
            <div className="mt-2 pl-[46px]">
              <p className={`text-[12.5px] leading-relaxed text-ink2 ${open ? '' : 'line-clamp-2'}`}>“{c.profile}”</p>
              <div className="mt-1 flex gap-3 text-[11.5px]">
                <button className="text-accent" onClick={(e) => { e.stopPropagation(); setOpen(!open) }}>{open ? 'Less' : 'Full profile'}</button>
                {src && <ExtLink href={pageLink(src.url, c.page)}>{c.profile_verified ? `Verbatim from filing p.${c.page}` : 'Filing'}</ExtLink>}
              </div>
            </div>
          )}
          {c.reason && <p className="mt-1 pl-[46px] text-[12.5px] text-ink2">Reason given: {c.reason}</p>}
        </div>
      ))}
    </div>
  )
}

function Body({ s }: { s: Story }) {
  const e = s.enrichment
  if (e?.type === 'results' && e.status === 'ok' && e.card) return <ResultsTable card={e.card} compact />
  if (e?.type === 'results' && e.status === 'pending') return <p className="text-[13px] text-ink2">{e.note}</p>
  if (e?.type === 'management_change' && e.status === 'ok' && e.changes?.length) return <MgmtBlock changes={e.changes} src={e.source} />
  const norm = (t?: string | null) => (t ?? '').toLowerCase().replace(/[^a-z0-9]+/g, '')
  const fresh = (t?: string | null) => (t && norm(t) !== norm(s.title) && !norm(s.title).includes(norm(t)) ? t : null)
  const line = fresh(s.summary) || fresh(s.subject) || fresh(s.text)
  return line ? <p className="line-clamp-3 text-[13.5px] leading-snug text-ink2">{line}</p> : null
}

export function StoryCard({ s, rank, expanded = false, onClear, onResearch }: {
  s: Story; rank?: number; expanded?: boolean; onClear?: () => void; onResearch: () => void
}) {
  const [why, setWhy] = useState(false)
  const [open, setOpen] = useState(expanded)
  const [dx, setDx] = useState(0)
  const start = useRef<{ x: number; y: number } | null>(null)
  const compact = s.tier === 'notable'

  const onDown = (e: React.PointerEvent) => { start.current = { x: e.clientX, y: e.clientY } }
  const onMove = (e: React.PointerEvent) => {
    if (!start.current || !onClear) return
    const ddx = e.clientX - start.current.x, ddy = e.clientY - start.current.y
    if (Math.abs(ddx) > 12 && Math.abs(ddx) > Math.abs(ddy) * 1.5) setDx(Math.min(0, ddx))
  }
  const onUp = () => {
    if (dx < -110 && onClear) onClear()
    setDx(0)
    start.current = null
  }

  return (
    <div className="relative">
      {onClear && dx < 0 && (
        <div className="absolute inset-0 flex items-center justify-end rounded-2xl bg-accent-soft pr-5 text-[13px] font-semibold text-accent">
          <Icon name="check" className="mr-1 size-4" />Done
        </div>
      )}
      <Card className="touch-pan-y overflow-hidden transition-transform" >
        <div onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
          style={{ transform: `translateX(${dx}px)`, transition: dx ? 'none' : 'transform 180ms ease-out' }}
          className="bg-card px-4 pb-3 pt-3">
          <TierBar tier={s.tier} />
          <div className="flex items-center gap-2 text-[12px]">
            <button onClick={onResearch} className="font-bold tracking-wide text-ink">{s.symbol}</button>
            <span className="text-ink3">·</span>
            <span className="text-ink2">{cat(s.category)}</span>
            <span className="text-ink3">·</span>
            <span className="text-ink3" title={clock(s.ts)}>{ago(s.ts)}</span>
            {s.reaction && (
              <span className={`num ml-auto rounded-md px-1.5 py-0.5 font-semibold ${s.reaction.pct >= 0 ? 'bg-up/10 text-up' : 'bg-down/10 text-down'}`}
                title={`Close-to-close move in the first session after the filing (${s.reaction.date})`}>
                {pct(s.reaction.pct)}
              </span>
            )}
          </div>
          <h3 className={`mt-1 font-semibold leading-snug text-ink ${compact ? 'text-[14.5px]' : 'text-[16px]'}`}>{s.title}</h3>
          {s.enrichment?.type === 'results' && s.enrichment.card?.headline && (
            <p className="mt-0.5 text-[12.5px] text-ink2">{s.enrichment.card.headline}</p>
          )}
          {open || s.enrichment?.type !== 'results' || s.enrichment.status !== 'ok'
            ? <div className="mt-2.5"><Body s={s} /></div>
            : <button onClick={() => setOpen(true)} className="mt-1.5 text-[12.5px] font-medium text-accent">Show the numbers</button>}
          <div className="mt-3 flex items-center gap-1 text-[12px] text-ink3">
            <button onClick={() => setWhy(true)} className="num whitespace-nowrap rounded-md bg-sunk px-2 py-1 font-medium text-ink2 active:bg-line">
              {rank ? `#${rank} · ` : ''}score {s.materiality}
            </button>
            {s.related.length > 0 && <span className="whitespace-nowrap px-1.5">+{s.related.length} filing{s.related.length > 1 ? 's' : ''}</span>}
            <div className="ml-auto flex items-center gap-3">
              {s.pdf_url && <ExtLink href={s.pdf_url} className="text-[12px]">Filing</ExtLink>}
              <button onClick={onResearch} className="inline-flex items-center font-medium text-ink">Research<Icon name="chev" className="size-4" /></button>
            </div>
          </div>
        </div>
      </Card>
      <Sheet open={why} onClose={() => setWhy(false)} title={`Why ${s.symbol} ranks here`}>
        <ol className="space-y-2 text-[14px]">
          {s.reasons.map((r, i) => (
            <li key={r} className="flex gap-2"><span className="num w-5 text-ink3">{i + 1}.</span><span>{r}</span></li>
          ))}
        </ol>
        <p className="mt-3 text-[13px] text-ink2">Score {s.materiality}/100 → <b className="capitalize">{s.tier}</b>. Rules are deterministic: the same filing always gets the same rank, and each adjustment is listed above.</p>
        <div className="mt-4 rounded-xl bg-sunk p-3 text-[12.5px] text-ink2">
          <div className="font-medium text-ink">Exchange record</div>
          <div className="mt-1">{s.exch_category} · {clock(s.ts)}</div>
          {s.text && <div className="mt-1">{s.text}</div>}
        </div>
        {s.related.length > 0 && (
          <div className="mt-4">
            <div className="text-[12px] font-semibold uppercase tracking-wider text-ink3">Grouped into this story</div>
            {s.related.map((r) => (
              <div key={r.id} className="mt-2 border-t border-line pt-2 text-[13px]">
                <div className="text-ink2">{r.exch_category} · {clock(r.ts)}</div>
                <div>{r.text}</div>
                {r.pdf_url && <ExtLink href={r.pdf_url} className="text-[12px]">Filing</ExtLink>}
              </div>
            ))}
          </div>
        )}
      </Sheet>
    </div>
  )
}

export function RoutineGroup({ category, items }: { category: string; items: Story[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border-t border-line first:border-t-0">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-4 py-3 text-left text-[14px]">
        <span className="flex-1 text-ink2">{cat(category)}</span>
        <span className="num text-ink3">{items.length}</span>
        <Icon name="chev" className={`size-4 text-ink3 transition-transform ${open ? 'rotate-90' : ''}`} />
      </button>
      {open && (
        <div className="space-y-2 px-4 pb-3">
          {items.map((s) => (
            <div key={s.id} className="flex items-start gap-2 text-[13px]">
              <span className="w-[86px] shrink-0 font-semibold">{s.symbol}</span>
              <span className="flex-1 text-ink2">{s.title}</span>
              {s.pdf_url && <a href={s.pdf_url} target="_blank" rel="noreferrer" className="text-ink3"><Icon name="doc" className="size-4" /></a>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export { Pill }
