import { useState } from 'react'
import { Card, Chip, Empty, Icon, SectionTitle, Skeleton } from '../components/ui'
import type { Alert, Settings } from '../lib/api'
import { cat, clock } from '../lib/format'
import { useApi } from '../lib/hooks'

const KIND = { price: 'Price', volume: 'Volume', announcement: 'Filing' } as const

function AlertRow({ a, go }: { a: Alert; go: (r: string) => void }) {
  const icon = a.kind === 'announcement' ? '◆' : a.kind === 'volume' ? '▮' : (a.ret_pct ?? 0) >= 0 ? '▲' : '▼'
  const color = a.kind === 'announcement' ? 'text-crit' : a.kind === 'volume' ? 'text-accent' : (a.ret_pct ?? 0) >= 0 ? 'text-up' : 'text-down'
  return (
    <button onClick={() => go(`company/${a.symbol}`)} className="flex w-full gap-3 border-t border-line px-4 py-3 text-left first:border-t-0 active:bg-sunk">
      <span className={`mt-0.5 w-4 text-center text-[13px] ${color}`}>{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="text-[14px] font-semibold leading-snug">{a.title}</div>
        {a.kind !== 'announcement' && (
          <div className="num mt-0.5 text-[12px] text-ink3">
            {a.kind === 'price' ? `your threshold ±${a.threshold}%` : `your threshold ${a.threshold}×`} · close ₹{a.close?.toLocaleString('en-IN')}
          </div>
        )}
        {a.kind === 'announcement' && a.text && <div className="mt-0.5 line-clamp-2 text-[12.5px] text-ink2">{a.text}</div>}
        {a.linked && (
          <div className="mt-1.5 line-clamp-2 rounded-lg bg-sunk px-2.5 py-1.5 text-[12px] text-ink2">
            <span className="font-medium text-ink">Likely why · {cat(a.linked.category)}, {clock(a.linked.ts)}:</span> {a.linked.text}
          </div>
        )}
      </div>
      <Icon name="chev" className="mt-0.5 size-4 shrink-0 text-ink3" />
    </button>
  )
}

export default function Alerts({ go, openSettings }: { go: (r: string) => void; openSettings: () => void }) {
  const [days, setDays] = useState(7)
  const [kind, setKind] = useState<'all' | Alert['kind']>('all')
  const { data, loading } = useApi<{ settings: Settings; alerts: Alert[] }>(`/api/alerts?days=${days}`)
  const s = data?.settings
  const list = (data?.alerts ?? []).filter((a) => kind === 'all' || a.kind === kind)
  const byDay = list.reduce<Record<string, Alert[]>>((acc, a) => { (acc[a.date] ??= []).push(a); return acc }, {})

  return (
    <div className="mx-auto max-w-xl px-4 pt-[calc(env(safe-area-inset-top)+16px)]">
      <h1 className="font-serif text-[30px] leading-tight">Alerts</h1>
      <p className="mt-1 text-[13px] text-ink2">You decide what “unusual” means. FINN checks every end-of-day print against it and tells you what was filed that day.</p>

      <Card className="mt-4 p-3.5" onClick={openSettings}>
        <div className="flex items-center justify-between">
          <div className="text-[12px] font-semibold uppercase tracking-wider text-ink3">Your thresholds</div>
          <span className="text-[13px] font-medium text-accent">Edit</span>
        </div>
        {s ? (
          <div className="num mt-2 grid grid-cols-3 gap-2 text-center">
            <div className="rounded-lg bg-sunk py-2"><div className="text-[17px] font-semibold">±{s.price_move_pct}%</div><div className="text-[11px] text-ink3">daily move</div></div>
            <div className="rounded-lg bg-sunk py-2"><div className="text-[17px] font-semibold">{s.volume_multiple}×</div><div className="text-[11px] text-ink3">{s.volume_lookback_days}-day volume</div></div>
            <div className="rounded-lg bg-sunk py-2"><div className="text-[17px] font-semibold">≥{s.min_alert_materiality}</div><div className="text-[11px] text-ink3">filing score</div></div>
          </div>
        ) : <Skeleton className="mt-2 h-14" />}
        {s && <div className="mt-2 text-[12px] text-ink3">Filing alerts for: {s.alert_categories.map(cat).join(', ')}</div>}
      </Card>

      <div className="no-scrollbar -mx-4 mt-4 flex gap-2 overflow-x-auto px-4">
        {(['all', 'price', 'volume', 'announcement'] as const).map((k) => (
          <Chip key={k} active={kind === k} onClick={() => setKind(k)}>{k === 'all' ? 'All' : KIND[k]}</Chip>
        ))}
        <span className="w-2 shrink-0" />
        {[3, 7, 14].map((d) => <Chip key={d} active={days === d} onClick={() => setDays(d)}>{d}d</Chip>)}
      </div>

      {loading && !data && <Skeleton className="mt-4 h-60" />}
      {data && !list.length && <Empty title="Nothing crossed your lines.">Loosen a threshold in settings, or widen the window.</Empty>}
      {Object.entries(byDay).map(([day, items]) => (
        <div key={day}>
          <SectionTitle right={<span className="num text-[11.5px] text-ink3">{items.length}</span>}>
            {new Date(day).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })}
          </SectionTitle>
          <Card>{items.map((a) => <AlertRow key={a.id} a={a} go={go} />)}</Card>
        </div>
      ))}
      {data && list.some((a) => a.kind === 'price') && (
        <p className="mt-3 px-1 text-[11.5px] text-ink3">σ = the move measured in the stock’s own recent daily volatility, so a 3% move in a utility and in a small-cap don’t read the same. Close-to-close, end-of-day prices.</p>
      )}
      <div className="h-24" />
    </div>
  )
}
