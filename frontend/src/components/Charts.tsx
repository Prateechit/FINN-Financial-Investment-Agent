import { useState } from 'react'

const W = 340

/** Bars (₹ Cr) with an optional line (%) on a second scale. */
export function BarLine({ labels, bars, line, barLabel, lineLabel, h = 150 }: {
  labels: string[]; bars: (number | null)[]; line?: (number | null)[]; barLabel: string; lineLabel?: string; h?: number
}) {
  const [hover, setHover] = useState<number | null>(null)
  const n = labels.length
  const top = 14, bottom = 20, plot = h - top - bottom
  const bmax = Math.max(1, ...bars.map((b) => b ?? 0))
  const lv = (line ?? []).filter((v): v is number => v != null)
  const lmin = Math.min(0, ...lv), lmax = Math.max(1, ...lv)
  const bw = (W / n) * 0.62
  const x = (i: number) => (W / n) * (i + 0.5)
  const by = (v: number) => top + plot - (Math.max(0, v) / bmax) * plot
  const ly = (v: number) => top + plot - ((v - lmin) / (lmax - lmin || 1)) * plot * 0.9
  const path = line?.map((v, i) => (v == null ? '' : `${i && line[i - 1] != null ? 'L' : 'M'}${x(i)},${ly(v)}`)).join('')
  const i = hover ?? n - 1
  return (
    <div>
      <div className="num mb-1 flex items-baseline gap-3 text-[12px]">
        <span className="font-semibold">{labels[i]}</span>
        <span className="text-ink2"><span className="mr-1 inline-block size-2 rounded-sm bg-ink3/50" />{barLabel} {bars[i]?.toLocaleString('en-IN') ?? '—'} Cr</span>
        {line && <span className="text-accent"><span className="mr-1 inline-block h-0.5 w-3 bg-accent align-middle" />{lineLabel} {line[i] ?? '—'}%</span>}
      </div>
      <svg viewBox={`0 0 ${W} ${h}`} className="w-full touch-none" onPointerLeave={() => setHover(null)}
        onPointerMove={(e) => {
          const r = (e.currentTarget as SVGElement).getBoundingClientRect()
          setHover(Math.max(0, Math.min(n - 1, Math.floor(((e.clientX - r.left) / r.width) * n))))
        }}>
        <line x1={0} x2={W} y1={top + plot} y2={top + plot} stroke="var(--line)" />
        {bars.map((v, k) => v != null && (
          <rect key={k} x={x(k) - bw / 2} y={by(v)} width={bw} height={top + plot - by(v)} rx={2}
            fill={k === i ? 'var(--ink2)' : 'var(--ink3)'} opacity={k === i ? 0.9 : 0.45} />
        ))}
        {path && <path d={path} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" />}
        {line?.map((v, k) => v != null && <circle key={k} cx={x(k)} cy={ly(v)} r={k === i ? 3.5 : 2} fill="var(--accent)" />)}
        {labels.map((l, k) => (n <= 8 || k % 2 === (n - 1) % 2) && (
          <text key={k} x={x(k)} y={h - 5} textAnchor="middle" fontSize={10} fill="var(--ink3)">{l}</text>
        ))}
      </svg>
    </div>
  )
}

/** Two series side by side per period (e.g. operating cash flow vs profit). */
export function PairBars({ labels, a, b, aLabel, bLabel, h = 140 }: {
  labels: string[]; a: (number | null)[]; b: (number | null)[]; aLabel: string; bLabel: string; h?: number
}) {
  const n = labels.length
  const top = 8, bottom = 20, plot = h - top - bottom
  const vals = [...a, ...b].filter((v): v is number => v != null)
  const max = Math.max(1, ...vals), min = Math.min(0, ...vals)
  const y = (v: number) => top + ((max - v) / (max - min)) * plot
  const slot = W / n, bw = slot * 0.32
  return (
    <div>
      <div className="mb-1 flex gap-3 text-[12px] text-ink2">
        <span><span className="mr-1 inline-block size-2 rounded-sm bg-accent" />{aLabel}</span>
        <span><span className="mr-1 inline-block size-2 rounded-sm bg-ink3/60" />{bLabel}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${h}`} className="w-full">
        <line x1={0} x2={W} y1={y(0)} y2={y(0)} stroke="var(--line)" />
        {labels.map((l, k) => {
          const cx = slot * (k + 0.5)
          return (
            <g key={l}>
              {a[k] != null && <rect x={cx - bw - 1} y={Math.min(y(a[k]!), y(0))} width={bw} height={Math.abs(y(a[k]!) - y(0))} rx={2} fill="var(--accent)" />}
              {b[k] != null && <rect x={cx + 1} y={Math.min(y(b[k]!), y(0))} width={bw} height={Math.abs(y(b[k]!) - y(0))} rx={2} fill="var(--ink3)" opacity={0.6} />}
              <text x={cx} y={h - 5} textAnchor="middle" fontSize={10} fill="var(--ink3)">{l}</text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

/** Close-price line with filing markers coloured by tier. */
export function PriceChart({ prices, marks, h = 170 }: {
  prices: { d: string; c: number }[]; marks: { d: string; tier: string; title: string }[]; h?: number
}) {
  const [hover, setHover] = useState<number | null>(null)
  if (prices.length < 2) return null
  const top = 10, bottom = 18, plot = h - top - bottom
  const cs = prices.map((p) => p.c)
  const min = Math.min(...cs), max = Math.max(...cs)
  const x = (i: number) => (i / (prices.length - 1)) * W
  const y = (v: number) => top + ((max - v) / (max - min || 1)) * plot
  const d = prices.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.c).toFixed(1)}`).join('')
  const idx = new Map(prices.map((p, i) => [p.d, i]))
  const i = hover ?? prices.length - 1
  const color: Record<string, string> = { critical: 'var(--crit)', notable: 'var(--note)', routine: 'var(--ink3)' }
  const nearest = (date: string) => {
    if (idx.has(date)) return idx.get(date)!
    const k = prices.findIndex((p) => p.d >= date)
    return k < 0 ? undefined : k
  }
  const markAt = marks.filter((m) => m.tier !== 'routine').map((m) => ({ ...m, i: nearest(m.d) })).filter((m) => m.i !== undefined)
  const here = markAt.filter((m) => m.i === i)
  return (
    <div>
      <div className="num mb-1 flex items-baseline justify-between text-[12px]">
        <span className="text-ink2">{new Date(prices[i].d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}</span>
        <span className="font-semibold">₹{prices[i].c.toLocaleString('en-IN')}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${h}`} className="w-full touch-none" onPointerLeave={() => setHover(null)}
        onPointerMove={(e) => {
          const r = (e.currentTarget as SVGElement).getBoundingClientRect()
          setHover(Math.round(((e.clientX - r.left) / r.width) * (prices.length - 1)))
        }}>
        <path d={d} fill="none" stroke="var(--ink)" strokeWidth={1.6} strokeLinejoin="round" />
        {markAt.map((m, k) => <circle key={k} cx={x(m.i!)} cy={y(prices[m.i!].c)} r={4} fill={color[m.tier]} stroke="var(--card)" strokeWidth={1.5} />)}
        <line x1={x(i)} x2={x(i)} y1={top} y2={top + plot} stroke="var(--ink3)" strokeDasharray="2 3" />
      </svg>
      <div className="min-h-5 text-[12px] text-ink2">{here.map((m) => m.title).join(' · ')}</div>
    </div>
  )
}
