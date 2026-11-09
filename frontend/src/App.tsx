import { useState } from 'react'
import { TabBar } from './components/ui'
import type { Alert } from './lib/api'
import { useApi, useHashRoute } from './lib/hooks'
import Alerts from './screens/Alerts'
import Brief from './screens/Brief'
import Memo from './screens/Memo'
import { Company, Portfolio } from './screens/Portfolio'
import Research from './screens/Research'
import SettingsSheet from './screens/SettingsSheet'

export default function App() {
  const [route, go] = useHashRoute()
  const [settings, setSettings] = useState(false)
  const [version, setVersion] = useState(0)
  const { data: alerts } = useApi<{ alerts: Alert[] }>('/api/alerts?days=1', [version])
  const [screen, arg] = route
  const open = () => setSettings(true)

  return (
    <div className="min-h-dvh">
      <main key={`${screen}/${arg ?? ''}/${version}`} className="fade">
        {screen === 'brief' && <Brief go={go} openSettings={open} />}
        {screen === 'alerts' && <Alerts go={go} openSettings={open} />}
        {screen === 'research' && <Research go={go} />}
        {screen === 'memo' && arg && <Memo symbol={arg.toUpperCase()} go={go} />}
        {screen === 'portfolio' && <Portfolio go={go} />}
        {screen === 'company' && arg && <Company symbol={arg.toUpperCase()} go={go} />}
      </main>
      <TabBar route={screen} go={go} alertCount={alerts?.alerts.length ?? 0} />
      <SettingsSheet open={settings} onClose={() => setSettings(false)} onSaved={() => setVersion((v) => v + 1)} />
    </div>
  )
}
