import { useEffect, useState } from 'react'
import { Chip, StatusDot, Toggle, formatMYT, tierLabel, type DotStatus } from '@bcs/ui'
import type { ComponentStatus } from '@bcs/api-types'
import { useAppStore } from '../data/store'
import { AlertBell } from './AlertBell'
import { BufferingBadge } from './BufferingBadge'
import { cloudChipValue } from './cloudSync'

function useNow(): string {
  const [now, setNow] = useState(() => new Date().toISOString())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date().toISOString()), 1000)
    return () => clearInterval(t)
  }, [])
  return now
}

function StatusChip({ id, label, status, value, title }: { id: string; label: string; status: DotStatus; value: string; title?: string }) {
  return (
    <span data-testid={`chip-${id}`}>
      <Chip title={title ?? `${label}: ${value}`}>
        <StatusDot status={status} label={`${label} ${status}`} />
        <span className="chip__label">{label}</span>
        <span className="chip__value">{value}</span>
      </Chip>
    </span>
  )
}

export function TopBar() {
  const status = useAppStore((s) => s.system.status)
  const config = useAppStore((s) => s.system.config)
  const site = useAppStore((s) => s.site.site)
  const connection = useAppStore((s) => s.system.connection)
  const director = useAppStore((s) => s.ui.director)
  const toggleDirector = useAppStore((s) => s.toggleDirector)
  const now = useNow()

  const find = (id: ComponentStatus['id']) => status?.components.find((c) => c.id === id)
  const camera = find('camera')
  const sim = find('simulator')
  const ai = find('ai')
  const nodesOnline = Number((sim?.details as { nodes_online?: number } | undefined)?.nodes_online ?? 0)
  const cloudState = status?.sync.state
  const demo = status?.demo_time_scale ?? config?.demo_time_scale ?? false

  const cloudStatus: DotStatus = !status ? 'off' : cloudState === 'online' ? 'ok' : cloudState === 'buffering' ? 'warn' : 'fail'
  const cloudValue = cloudChipValue(status ? cloudState : undefined)
  const netStatus: DotStatus = nodesOnline >= 8 ? 'ok' : nodesOnline > 0 ? 'warn' : 'off'
  const aiTier = !ai ? '—' : ai.status === 'ok' ? tierLabel('gemini_primary') : tierLabel('rules')

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <span className="topbar__logo" aria-hidden="true" />
        <div>
          <div className="topbar__name">Blue Carbon Sentinel</div>
          <div className="topbar__site">{site ? `${site.name} · ${site.region}` : 'Kuala Selangor'}</div>
        </div>
      </div>
      <div className="topbar__chips">
        <StatusChip id="camera" label="Camera" status={camera?.status ?? 'off'} value={camera?.status === 'ok' ? 'Live' : camera?.status === 'off' ? 'Offline' : camera?.status === 'warn' ? 'Degraded' : camera ? 'Down' : '—'} title={camera?.summary} />
        <StatusChip id="network" label="Sentinel Network" status={netStatus} value={`${nodesOnline}/8`} />
        <StatusChip id="ai" label="AI" status={ai?.status ?? 'off'} value={aiTier} title={ai?.summary} />
        <StatusChip id="cloud" label="Cloud sync" status={cloudStatus} value={cloudValue} />
        <BufferingBadge />
      </div>
      <div className="topbar__right">
        {demo && (
          <span data-testid="demo-time" title="Demo time is scaled: timers run faster than real life">
            <Chip color="var(--risk-medium)">DEMO TIME ×</Chip>
          </span>
        )}
        <span className="topbar__clock bcs-mono" data-testid="clock" title={connection === 'open' ? 'Live' : `Events: ${connection}`}>
          {formatMYT(now, { seconds: true })}
        </span>
        <Toggle checked={director} onChange={(on) => toggleDirector(on)} label="Director" />
        <AlertBell />
      </div>
    </header>
  )
}
