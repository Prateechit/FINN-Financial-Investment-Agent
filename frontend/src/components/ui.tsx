import { useEffect, type ReactNode } from 'react'
import type { Tier } from '../lib/api'

type IconName = 'brief' | 'bell' | 'search' | 'folio' | 'gear' | 'out' | 'chev' | 'check' | 'x' | 'doc' | 'undo' | 'spark' | 'back'

const PATHS: Record<IconName, string> = {
  brief: 'M4 5h16M4 10h16M4 15h10M4 20h7',
  bell: 'M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15L6 16Zm4 4a2 2 0 0 0 4 0',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5-2 4 4',
  folio: 'M4 19V9m5 10V5m5 14v-7m5 7V8',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7.5 7.5 0 0 0-2-1.2L14.5 2h-5l-.4 2.6a7.5 7.5 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7.5 7.5 0 0 0 2 1.2l.4 2.6h5l.4-2.6a7.5 7.5 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z',
  out: 'M14 4h6v6m0-6-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5',
  chev: 'm9 6 6 6-6 6',
  check: 'm5 12 5 5 9-10',
  x: 'M6 6l12 12M18 6 6 18',
  doc: 'M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm7 0v5h5M9 13h6M9 17h6',
  undo: 'M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3',
  spark: 'M12 3v4m0 10v4M3 12h4m10 0h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6',
  back: 'm15 6-6 6 6 6',
}

export function Icon({ name, className = 'size-5', strokeWidth = 1.8 }: { name: IconName; className?: string; strokeWidth?: number }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <path d={PATHS[name]} />
    </svg>
  )
}

export const tierColor: Record<Tier, string> = { critical: 'bg-crit', notable: 'bg-note', routine: 'bg-ink3' }

export function TierBar({ tier }: { tier: Tier }) {
  return <span className={`absolute left-0 top-3 bottom-3 w-[3px] rounded-r ${tierColor[tier]}`} aria-label={tier} />
}

export function Chip({ active, onClick, children, className = '' }: { active?: boolean; onClick?: () => void; children: ReactNode; className?: string }) {
  return (
    <button
      onClick={onClick}
      className={`h-8 shrink-0 rounded-full px-3 text-[13px] font-medium transition-colors ${active ? 'bg-ink text-bg' : 'bg-sunk text-ink2 active:bg-line'} ${className}`}
    >
      {children}
    </button>
  )
}

export function Pill({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${className}`}>{children}</span>
}

export function Spark({ data, w = 64, h = 22, className = '' }: { data: number[]; w?: number; h?: number; className?: string }) {
  if (data.length < 2) return <svg width={w} height={h} />
  const min = Math.min(...data), max = Math.max(...data)
  const y = (v: number) => h - 2 - ((v - min) / (max - min || 1)) * (h - 4)
  const d = data.map((v, i) => `${i ? 'L' : 'M'}${((i / (data.length - 1)) * w).toFixed(1)},${y(v).toFixed(1)}`).join('')
  const up = data[data.length - 1] >= data[0]
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className={className} aria-hidden>
      <path d={d} fill="none" stroke={up ? 'var(--up)' : 'var(--down)'} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  )
}

export function Sheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title?: ReactNode; children: ReactNode }) {
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => { document.body.style.overflow = prev; window.removeEventListener('keydown', onKey) }
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center" role="dialog" aria-modal>
      <div className="fade absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="sheet relative max-h-[86vh] w-full max-w-xl overflow-y-auto rounded-t-2xl bg-card pb-[calc(env(safe-area-inset-bottom)+20px)] shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-card/95 px-4 py-3 backdrop-blur">
          <div className="text-[15px] font-semibold">{title}</div>
          <button onClick={onClose} className="-mr-1 rounded-full p-1.5 text-ink2 active:bg-sunk" aria-label="Close"><Icon name="x" /></button>
        </div>
        <div className="px-4 pt-3">{children}</div>
      </div>
    </div>
  )
}

export function SectionTitle({ children, right, id }: { children: ReactNode; right?: ReactNode; id?: string }) {
  return (
    <div id={id} className="mb-2 mt-6 flex scroll-mt-28 items-baseline justify-between px-1">
      <h2 className="text-[12px] font-semibold uppercase tracking-[0.08em] text-ink3">{children}</h2>
      {right}
    </div>
  )
}

export function Card({ children, className = '', onClick }: { children: ReactNode; className?: string; onClick?: () => void }) {
  return <div onClick={onClick} className={`relative rounded-2xl border border-line bg-card ${className}`}>{children}</div>
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton rounded-lg ${className}`} />
}

export function ExtLink({ href, children, className = '' }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
      className={`inline-flex items-center gap-1 text-accent underline-offset-2 hover:underline ${className}`}>
      {children}<Icon name="out" className="size-3.5" />
    </a>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="px-6 py-14 text-center">
      <div className="font-serif text-2xl">{title}</div>
      {children && <div className="mt-2 text-sm text-ink2">{children}</div>}
    </div>
  )
}

export function TabBar({ route, go, alertCount }: { route: string; go: (r: string) => void; alertCount: number }) {
  const tabs: { id: string; label: string; icon: IconName }[] = [
    { id: 'brief', label: 'Brief', icon: 'brief' },
    { id: 'alerts', label: 'Alerts', icon: 'bell' },
    { id: 'research', label: 'Research', icon: 'search' },
    { id: 'portfolio', label: 'Portfolio', icon: 'folio' },
  ]
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-card/90 pb-[env(safe-area-inset-bottom)] backdrop-blur-lg">
      <div className="mx-auto flex max-w-xl">
        {tabs.map((t) => {
          const on = route === t.id || (t.id === 'research' && route === 'memo') || (t.id === 'portfolio' && route === 'company')
          return (
            <button key={t.id} onClick={() => go(t.id)} className={`relative flex h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium ${on ? 'text-ink' : 'text-ink3'}`}>
              <Icon name={t.icon} strokeWidth={on ? 2.2 : 1.8} />
              {t.label}
              {t.id === 'alerts' && alertCount > 0 && (
                <span className="num absolute right-[calc(50%-20px)] top-1.5 min-w-4 rounded-full bg-crit px-1 text-[10px] font-bold leading-4 text-white">{alertCount}</span>
              )}
            </button>
          )
        })}
      </div>
    </nav>
  )
}
