import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Chip, Panel, SimulatedBadge, StatusDot, type DotStatus } from '@bcs/ui'
import { useConsole } from '../data/store'
import { SiteMiniMap } from '../minimap/SiteMiniMap'
import { NodeCard } from '../nodes/NodeCard'
import { ScenarioPanel } from '../scenarios/ScenarioPanel'
import { NaturePanel } from '../nature/NaturePanel'
import { LifecyclePanel } from '../lifecycle/LifecyclePanel'
import { PacketInspector } from '../inspector/PacketInspector'
import { RecordReplay } from '../recording/RecordReplay'

/** One panel failing must not blank the whole Console during a demo. */
class PanelBoundary extends Component<{ children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null }
  static getDerivedStateFromError(e: Error) {
    return { error: e.message }
  }
  componentDidCatch(e: Error, info: ErrorInfo) {
    console.error('panel failed', e, info.componentStack)
  }
  render() {
    if (this.state.error)
      return (
        <div className="banner banner--error" role="alert">
          This panel failed: {this.state.error}{' '}
          <button type="button" className="mini-btn" onClick={() => this.setState({ error: null })}>Retry</button>
        </div>
      )
    return this.props.children
  }
}

function Region({ id, title, children, actions }: { id: string; title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className={`console__cell console__cell--${id}`} data-testid={`region-${id}`}>
      <Panel title={title} actions={actions}>
        <PanelBoundary>{children}</PanelBoundary>
      </Panel>
    </div>
  )
}

function NodeGrid() {
  const nodes = useConsole((s) => s.nodes)
  const history = useConsole((s) => s.history)
  const sim = useConsole((s) => s.sim)
  if (!nodes.length)
    return <div className="console__empty">{sim === 'offline' ? 'Simulator offline: no nodes.' : 'Waiting for the simulator…'}</div>
  return (
    <div className="node-grid">
      {nodes.map((n) => (
        <NodeCard key={n.node_id} node={n} history={history[n.node_id]} />
      ))}
    </div>
  )
}

export function ConsoleShell() {
  const sim = useConsole((s) => s.sim)
  const config = useConsole((s) => s.config)
  const state = useConsole((s) => s.state)
  const status = useConsole((s) => s.status)
  const ws = useConsole((s) => s.ws)
  const nodeCount = useConsole((s) => s.nodes.length)

  const online = sim === 'online'
  const simDot: DotStatus = online ? (status?.runtime === 'starting' ? 'warn' : 'ok') : sim === 'offline' ? 'fail' : 'off'
  const simText = online ? 'online' : sim === 'offline' ? 'offline' : 'connecting'
  const brokerUp = status?.broker_connected ?? state?.broker_connected
  const broker: DotStatus = !online ? 'off' : brokerUp ? 'ok' : 'fail'
  const brokerText = !online ? 'unknown' : brokerUp ? 'connected' : 'disconnected'
  const demo = state?.demo_time_scale ?? config?.demo_time_scale
  const ff = status?.fast_forward ?? state?.fast_forward

  return (
    <div className="console">
      <header className="console__top">
        <div className="console__brand">
          <div className="console__logo" />
          <div>
            <div className="console__name">Simulator Console</div>
            <div className="console__site">{config?.site?.name ?? 'Blue Carbon Sentinel'}</div>
          </div>
        </div>
        <div className="console__chips">
          <Chip>
            <span data-testid="broker-status"><StatusDot status={broker} label={`Broker: ${brokerText}`} /> Broker: {brokerText}</span>
          </Chip>
          <Chip>
            <span data-testid="sim-status"><StatusDot status={simDot} label={`Simulator: ${simText}`} /> Simulator: {simText}</span>
          </Chip>
          <Chip>
            <span data-testid="demo-time">DEMO TIME {demo === undefined ? '-' : demo ? 'on' : 'off'}</span>
          </Chip>
          <Chip>
            <span data-testid="fast-forward">Fast-forward: {typeof ff === 'number' ? `${ff}x` : '-'}</span>
          </Chip>
        </div>
        <PanelBoundary>
          <RecordReplay />
        </PanelBoundary>
        <SimulatedBadge />
      </header>
      <main className="console__grid">
        <Region id="minimap" title="Site mini-map">
          <SiteMiniMap />
        </Region>
        <Region
          id="nodes"
          title={`Nodes${nodeCount ? ` · ${nodeCount}` : ''}`}
          actions={<span className={`console__live${ws ? ' is-on' : ''}`}>{ws ? 'live 4 Hz' : 'stream offline'}</span>}
        >
          <NodeGrid />
        </Region>
        <div className="console__side">
          <Region id="scenarios" title="Scenarios">
            <ScenarioPanel />
          </Region>
          <Region id="nature" title="Natural behaviour">
            <NaturePanel />
          </Region>
          <Region id="lifecycle" title="Lifecycle">
            <LifecyclePanel />
          </Region>
        </div>
        <div className="console__drawer" data-testid="region-inspector">
          <PanelBoundary>
            <PacketInspector />
          </PanelBoundary>
        </div>
      </main>
      <div className="console__watermark" aria-hidden="true">SIMULATED HARDWARE</div>
    </div>
  )
}
