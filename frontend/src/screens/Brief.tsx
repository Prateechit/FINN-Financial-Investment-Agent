import { useMemo } from 'react'
import { RoutineGroup, StoryCard } from '../components/Story'
import { Card, Chip, Empty, Icon, SectionTitle, Skeleton, Spark } from '../components/ui'
import type { Digest, Holding, Story } from '../lib/api'
import { cat, pct, tone } from '../lib/format'
import { useApi, usePersisted } from '../lib/hooks'

const WINDOWS = [{ h: 24, label: '24h' }, { h: 72, label: '3 days' }, { h: 168, label: 'Week' }, { h: 336, label: '2 weeks' }]

function headline(stories: Story[], routine: number, hours: number): string {
  const crit = stories.filter((s) => s.tier === 'critical')
  if (!stories.length) return routine ? `Nothing material. ${routine} routine filing${routine > 1 ? 's' : ''} folded away.` : 'A quiet tape. Nothing filed.'
  const names = [...new Set(crit.map((s) => s.symbol))]
  const span = hours <= 24 ? 'today' : hours <= 72 ? 'in three days' : hours <= 168 ? 'this week' : 'in two weeks'
  if (!names.length) return `${stories.length} thing${stories.length > 1 ? 's' : ''} worth a look ${span}.`
  if (names.length <= 3) return `${names.join(names.length === 2 ? ' and ' : ', ')} need${names.length === 1 ? 's' : ''} you ${span}.`
  return `${crit.length} things need you ${span}, led by ${names.slice(0, 2).join(' and ')}.`
}

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Morning brief' : h < 17 ? 'Afternoon brief' : 'Evening brief'
}

export default function Brief({ go, openSettings }: { go: (r: string) => void; openSettings: () => void }) {
  const [hours, setHours] = usePersisted('finn.window', 24)
  const [cleared, setCleared] = usePersisted<string[]>('finn.cleared', [])
  const { data, error, loading } = useApi<Digest>(`/api/digest?hours=${hours}`)
  const { data: folio } = useApi<Holding[]>('/api/portfolio')

  const visible = useMemo(() => (data?.stories ?? []).filter((s) => !cleared.includes(s.id)), [data, cleared])
  const done = (data?.stories ?? []).filter((s) => cleared.includes(s.id))
  const crit = visible.filter((s) => s.tier === 'critical')
  const notable = visible.filter((s) => s.tier === 'notable')
  const clear = (id: string) => setCleared([...cleared, id].slice(-400))
  const research = (sym: string) => go(`memo/${sym}`)
  const today = new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })

  return (
    <div className="mx-auto max-w-xl px-4 pt-[calc(env(safe-area-inset-top)+12px)]">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="grid size-7 place-items-center rounded-lg bg-ink font-serif text-[15px] font-semibold text-bg">F</div>
          <div className="text-[13px] text-ink2">{today}</div>
        </div>
        <button onClick={openSettings} className="rounded-full p-2 text-ink2 active:bg-sunk" aria-label="Alert settings"><Icon name="gear" /></button>
      </header>

      <div className="mt-5">
        <div className="text-[12px] font-semibold uppercase tracking-[0.1em] text-accent">{greeting()}</div>
        {data ? (
          <h1 className="mt-1 font-serif text-[30px] leading-[1.1] tracking-tight">{headline(visible, data.counts.routine, hours)}</h1>
        ) : <Skeleton className="mt-2 h-16 w-4/5" />}
        {data && (
          <p className="num mt-2 text-[13px] text-ink2">
            {data.counts.filings} filings across your 19 holdings → {data.counts.critical + data.counts.notable} worth reading, {data.counts.routine} folded.
          </p>
        )}
      </div>

      <div className="no-scrollbar -mx-4 mt-4 flex gap-2 overflow-x-auto px-4">
        {WINDOWS.map((w) => <Chip key={w.h} active={hours === w.h} onClick={() => setHours(w.h)}>{w.label}</Chip>)}
      </div>

      {folio && (
        <div className="no-scrollbar -mx-4 mt-4 flex gap-2 overflow-x-auto px-4 pb-1">
          {folio.map((h) => (
            <button key={h.symbol} onClick={() => go(`company/${h.symbol}`)}
              className="shrink-0 rounded-xl border border-line bg-card px-2.5 py-1.5 text-left active:bg-sunk">
              <div className="flex items-center gap-1.5">
                <span className="text-[11.5px] font-bold">{h.symbol}</span>
                {h.material_7d > 0 && <span className="size-1.5 rounded-full bg-crit" />}
              </div>
              <div className="flex items-end gap-1.5">
                <span className={`num text-[12px] font-semibold ${tone(h.change_pct)}`}>{pct(h.change_pct)}</span>
                <Spark data={h.spark.slice(-15)} w={36} h={14} />
              </div>
            </button>
          ))}
        </div>
      )}

      {error && <Card className="mt-6 p-4 text-sm text-down">Couldn’t load the brief: {error}</Card>}
      {!data && loading && <div className="mt-6 space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-40" />)}</div>}

      {data && (
        <>
          {crit.length > 0 && <SectionTitle right={<span className="text-[11.5px] text-ink3">swipe left when done</span>}>Needs you</SectionTitle>}
          <div className="space-y-3">
            {crit.map((s, i) => <StoryCard key={s.id} s={s} rank={i + 1} expanded={i < 3} onClear={() => clear(s.id)} onResearch={() => research(s.symbol)} />)}
          </div>
          {notable.length > 0 && <SectionTitle>Worth a look</SectionTitle>}
          <div className="space-y-2.5">
            {notable.map((s) => <StoryCard key={s.id} s={s} onClear={() => clear(s.id)} onResearch={() => research(s.symbol)} />)}
          </div>
          {!visible.length && data.stories.length > 0 && (
            <Empty title="You’re through.">Nothing else in your portfolio needs attention in this window.</Empty>
          )}
          {data.routine.length > 0 && (
            <>
              <SectionTitle right={<span className="num text-[11.5px] text-ink3">{data.counts.routine} items</span>}>Folded — routine</SectionTitle>
              <Card>{data.routine.map((g) => <RoutineGroup key={g.category} category={g.category} items={g.items} />)}</Card>
              <p className="mt-2 px-1 text-[11.5px] text-ink3">
                Folded: {data.routine.slice(0, 4).map((g) => cat(g.category).toLowerCase()).join(', ')}. Filings stay one tap away.
              </p>
            </>
          )}
          {done.length > 0 && (
            <div className="mt-6 flex items-center justify-between rounded-xl bg-sunk px-3 py-2.5 text-[13px] text-ink2">
              <span>{done.length} cleared</span>
              <button className="inline-flex items-center gap-1 font-medium text-ink" onClick={() => setCleared(cleared.filter((id) => !done.some((d) => d.id === id)))}>
                <Icon name="undo" className="size-4" />Restore
              </button>
            </div>
          )}
        </>
      )}
      <div className="h-24" />
    </div>
  )
}
