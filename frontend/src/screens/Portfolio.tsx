import { PriceChart } from '../components/Charts'
import { ResultsTable } from '../components/Story'
import { Card, ExtLink, Icon, SectionTitle, Skeleton, Spark, tierColor } from '../components/ui'
import type { CompanyView, Holding } from '../lib/api'
import { ago, cat, pct, rupee, tone } from '../lib/format'
import { useApi } from '../lib/hooks'

export function Portfolio({ go }: { go: (r: string) => void }) {
  const { data } = useApi<Holding[]>('/api/portfolio')
  const day = data?.filter((h) => h.change_pct != null).reduce((a, h) => a + (h.change_pct! * h.weight) / 100, 0)
  return (
    <div className="mx-auto max-w-xl px-4 pt-[calc(env(safe-area-inset-top)+16px)]">
      <h1 className="font-serif text-[30px] leading-tight">Portfolio</h1>
      {day != null && (
        <p className="num mt-1 text-[13px] text-ink2">
          Weighted day move <b className={tone(day)}>{pct(day, 2)}</b> · {data?.length} holdings · last close {data?.[0]?.date}
        </p>
      )}
      <SectionTitle>Holdings by weight</SectionTitle>
      {!data ? <Skeleton className="h-96" /> : (
        <Card>
          {data.map((h) => (
            <button key={h.symbol} onClick={() => go(`company/${h.symbol}`)} className="flex w-full items-center gap-3 border-t border-line px-4 py-2.5 text-left first:border-t-0 active:bg-sunk">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-[14px] font-bold">{h.symbol}</span>
                  {h.material_7d > 0 && <span className="num rounded bg-crit-soft px-1 text-[10.5px] font-semibold text-crit">{h.material_7d}</span>}
                </div>
                <div className="truncate text-[12px] text-ink3">{h.sector} · {h.weight}%</div>
              </div>
              <Spark data={h.spark} w={60} h={24} />
              <div className="num w-[78px] text-right">
                <div className="text-[13.5px] font-semibold">{rupee(h.close)}</div>
                <div className={`text-[12px] ${tone(h.change_pct)}`}>{pct(h.change_pct)}</div>
              </div>
            </button>
          ))}
        </Card>
      )}
      <p className="mt-2 px-1 text-[11.5px] text-ink3">Red badge = material filings in the last 7 days. Mock weights; end-of-day prices.</p>
      <div className="h-24" />
    </div>
  )
}

export function Company({ symbol, go }: { symbol: string; go: (r: string) => void }) {
  const { data } = useApi<CompanyView>(`/api/company/${symbol}`)
  const last = data?.prices.at(-1), first = data?.prices[0]
  return (
    <div className="mx-auto max-w-xl px-4 pt-[calc(env(safe-area-inset-top)+8px)]">
      <button onClick={() => history.length > 1 ? history.back() : go('portfolio')} className="-ml-2 rounded-full p-2 text-ink2 active:bg-sunk" aria-label="Back"><Icon name="back" /></button>
      <h1 className="font-serif text-[28px] leading-tight">{data?.name ?? symbol}</h1>
      {last && first && (
        <div className="num mt-0.5 text-[13px] text-ink2">{rupee(last.c)} · <span className={tone(last.c - first.c)}>{pct((last.c / first.c - 1) * 100)}</span> over {data!.prices.length} sessions{data?.weight ? ` · ${data.weight}% of portfolio` : ''}</div>
      )}
      <button onClick={() => go(`memo/${symbol}`)} className="mt-3 flex h-11 w-full items-center justify-center gap-1 rounded-xl bg-ink text-[14px] font-semibold text-bg">
        Open research memo<Icon name="chev" className="size-4" />
      </button>

      {!data ? <Skeleton className="mt-4 h-60" /> : (
        <>
          <SectionTitle>Price & filings</SectionTitle>
          <Card className="p-4">
            <PriceChart prices={data.prices} marks={data.announcements.map((a) => ({ d: a.ts.slice(0, 10), tier: a.tier, title: a.title }))} />
            <div className="mt-1 flex gap-3 text-[11px] text-ink3">
              <span><span className="mr-1 inline-block size-2 rounded-full bg-crit" />critical filing</span>
              <span><span className="mr-1 inline-block size-2 rounded-full bg-note" />notable</span>
            </div>
          </Card>
          {data.results && (
            <>
              <SectionTitle right={<span className="text-[11.5px] text-ink3">vs {data.results.prev_label} · {data.results.yoy_label}</span>}>Latest results</SectionTitle>
              <Card className="p-4">
                <ResultsTable card={data.results} />
                {data.results.links[0] && <div className="mt-2 text-[12px]"><ExtLink href={data.results.links[0]}>{data.results.source} source</ExtLink></div>}
              </Card>
            </>
          )}
          <SectionTitle>Filings</SectionTitle>
          <Card>
            {data.announcements.map((a) => (
              <div key={a.id} className="flex items-start gap-2.5 border-t border-line px-4 py-2.5 first:border-t-0">
                <span className={`mt-1.5 size-2 shrink-0 rounded-full ${tierColor[a.tier]}`} />
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px] leading-snug">{a.title}</div>
                  <div className="text-[11.5px] text-ink3">{cat(a.category)} · {ago(a.ts)} · score {a.materiality}</div>
                </div>
                {a.pdf_url && <a href={a.pdf_url} target="_blank" rel="noreferrer" className="mt-0.5 text-ink3"><Icon name="doc" className="size-4" /></a>}
              </div>
            ))}
          </Card>
        </>
      )}
      <div className="h-24" />
    </div>
  )
}
