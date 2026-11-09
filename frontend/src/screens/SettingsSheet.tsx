import { useEffect, useState } from 'react'
import { Chip, Sheet } from '../components/ui'
import { api, type Settings } from '../lib/api'
import { cat } from '../lib/format'

const ALL = ['results', 'M&A', 'management_change', 'fund_raise', 'credit_rating', 'litigation', 'pledging', 'insider_trading',
  'capex', 'dividend', 'bonus_split', 'press_release', 'earnings_call']

function Stepper({ label, hint, value, step, min, max, unit, onChange }: {
  label: string; hint: string; value: number; step: number; min: number; max: number; unit: string; onChange: (v: number) => void
}) {
  const set = (v: number) => onChange(Math.min(max, Math.max(min, Math.round(v * 100) / 100)))
  return (
    <div className="flex items-center justify-between border-t border-line py-3 first:border-t-0">
      <div>
        <div className="text-[14px] font-medium">{label}</div>
        <div className="text-[12px] text-ink3">{hint}</div>
      </div>
      <div className="flex items-center gap-1">
        <button onClick={() => set(value - step)} className="size-9 rounded-full bg-sunk text-lg active:bg-line" aria-label={`decrease ${label}`}>−</button>
        <span className="num w-16 text-center text-[16px] font-semibold">{value}{unit}</span>
        <button onClick={() => set(value + step)} className="size-9 rounded-full bg-sunk text-lg active:bg-line" aria-label={`increase ${label}`}>+</button>
      </div>
    </div>
  )
}

export default function SettingsSheet({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const [s, setS] = useState<Settings | null>(null)
  const [saving, setSaving] = useState(false)
  useEffect(() => { if (open) api<Settings>('/api/settings').then(setS).catch(() => setS(null)) }, [open])
  const save = async () => {
    if (!s) return
    setSaving(true)
    try {
      await api('/api/settings', { method: 'PUT', body: JSON.stringify(s) })
      onSaved()
      onClose()
    } finally {
      setSaving(false)
    }
  }
  const toggle = (c: string) => s && setS({ ...s, alert_categories: s.alert_categories.includes(c) ? s.alert_categories.filter((x) => x !== c) : [...s.alert_categories, c] })

  return (
    <Sheet open={open} onClose={onClose} title="What counts as unusual">
      {!s ? <div className="py-10 text-center text-ink3">Loading…</div> : (
        <>
          <Stepper label="Price move" hint="Alert when a holding closes beyond ±" value={s.price_move_pct} step={0.5} min={0.5} max={20} unit="%" onChange={(v) => setS({ ...s, price_move_pct: v })} />
          <Stepper label="Volume spike" hint="× the trailing average volume" value={s.volume_multiple} step={0.25} min={1.25} max={10} unit="×" onChange={(v) => setS({ ...s, volume_multiple: v })} />
          <Stepper label="Volume lookback" hint="Days in the trailing average" value={s.volume_lookback_days} step={5} min={5} max={60} unit="d" onChange={(v) => setS({ ...s, volume_lookback_days: v })} />
          <Stepper label="Filing score" hint="Minimum materiality to alert (0–100)" value={s.min_alert_materiality} step={5} min={30} max={95} unit="" onChange={(v) => setS({ ...s, min_alert_materiality: v })} />
          <div className="border-t border-line py-3">
            <div className="text-[14px] font-medium">Alert me about</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {ALL.map((c) => <Chip key={c} active={s.alert_categories.includes(c)} onClick={() => toggle(c)}>{cat(c)}</Chip>)}
            </div>
          </div>
          <button onClick={save} disabled={saving} className="mt-2 h-12 w-full rounded-xl bg-ink text-[15px] font-semibold text-bg disabled:opacity-60">
            {saving ? 'Saving…' : 'Save — applies to past days too'}
          </button>
          <p className="mt-2 pb-2 text-center text-[11.5px] text-ink3">Alerts are recomputed from stored prices and filings on every view.</p>
        </>
      )}
    </Sheet>
  )
}
