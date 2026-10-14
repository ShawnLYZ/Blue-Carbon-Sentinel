import { Chip, Panel } from '@bcs/ui'
import { useAppStore } from '../../data/store'
import { useZoneLabels } from '../SatelliteIntel/shared'
import { CoveragePanel } from './CoveragePanel'
import { NodeCharts } from './NodeCharts'
import { NodeDrawer } from './NodeDrawer'
import { NodeTable } from './NodeTable'
import { TaskTimeline } from './TaskTimeline'

/**
 * Sentinel Network (design §26): oblique map preset with node pins, coverage rings and tasking pulses
 * (map layers mounted by MapStage). Left column: node table and the selected node's charts. Right
 * column: the node drawer, the task timeline and coverage/commissioning.
 */
export function SentinelNetwork() {
  const nodes = useAppStore((s) => s.nodes.items)
  const selectedId = useAppStore((s) => s.ui.selectedNodeId)
  const selectNode = useAppStore((s) => s.selectNode)
  const zoneLabel = useZoneLabels()
  const active = nodes.filter((n) => n.status !== 'decommissioned')
  const online = active.filter((n) => n.status === 'online').length
  const selected = active.find((n) => n.id === selectedId) ?? null

  return (
    <div className="net-page">
      <div className="net-page__col net-page__left">
        <header className="sat-header">
          <h1 className="page__title">Sentinel Network</h1>
          <div className="sat-header__chips">
            <Chip>
              {online} / {active.length} online
            </Chip>
            <Chip title="Every node is simulated by the Sentinel Simulator over the real MQTT protocol">
              Simulated hardware
            </Chip>
          </div>
        </header>
        <Panel title="Nodes">
          <NodeTable nodes={active} selectedId={selected?.id ?? null} onSelect={selectNode} zoneLabel={zoneLabel} />
        </Panel>
        {selected ? (
          <NodeCharts node={selected} />
        ) : (
          <p className="hint net-page__hint">Select a node (row or map pin) for its live charts and details.</p>
        )}
      </div>
      <div className="net-page__col net-page__right">
        {selected && <NodeDrawer node={selected} zoneLabel={zoneLabel} onClose={() => selectNode(null)} />}
        <TaskTimeline zoneLabel={zoneLabel} />
        <CoveragePanel zoneLabel={zoneLabel} />
      </div>
    </div>
  )
}
