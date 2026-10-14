// Alert markers (design §26): a billboard above every zone and node with unacknowledged alerts, in the
// colour of the most severe one, with the count. drei Html labels always face the viewer.
import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import type { Group } from 'three'
import type { Alert, Node, Zone } from '@bcs/api-types'
import { useAppStore } from '../data/store'
import { siteToScene, surfaceHeightAt, zoneCentreSite } from './surfaceMaterial'
import { useSurfaceState } from './surfaceContext'

export const MARKER_LIFT_M = 55
const RANK: Record<Alert['severity'], number> = { info: 0, warning: 1, critical: 2 }

export interface Marker {
  key: string
  /** "zone" markers sit over the zone centre, "node" markers over the node. */
  target: 'zone' | 'node'
  id: string
  e: number
  s: number
  severity: Alert['severity']
  count: number
  title: string
}

/** One marker per zone or node with unacknowledged alerts (node alerts go on the node, not its zone). */
export function alertMarkers(
  alerts: Alert[],
  zones: Pick<Zone, 'id' | 'label' | 'col' | 'row'>[],
  nodes: Pick<Node, 'id' | 'position'>[],
): Marker[] {
  const out = new Map<string, Marker>()
  for (const a of alerts) {
    if (a.acknowledged_at) continue
    let m: Omit<Marker, 'severity' | 'count' | 'title'> | null = null
    if (a.node_id) {
      const n = nodes.find((x) => x.id === a.node_id)
      if (n) m = { key: `node:${n.id}`, target: 'node', id: n.id, e: n.position.e_m, s: n.position.s_m }
    }
    if (!m && a.zone_id) {
      const z = zones.find((x) => x.id === a.zone_id)
      if (z) {
        const [e, s] = zoneCentreSite(z.col, z.row)
        m = { key: `zone:${z.id}`, target: 'zone', id: z.id, e, s }
      }
    }
    if (!m) continue
    const prev = out.get(m.key)
    if (!prev) out.set(m.key, { ...m, severity: a.severity, count: 1, title: a.message })
    else {
      prev.count += 1
      if (RANK[a.severity] > RANK[prev.severity]) {
        prev.severity = a.severity
        prev.title = a.message
      }
    }
  }
  return [...out.values()]
}

export function AlertMarkers({ zones }: { zones: Pick<Zone, 'id' | 'label' | 'col' | 'row'>[] }) {
  const state = useSurfaceState()
  const alerts = useAppStore((s) => s.alerts.items)
  const nodes = useAppStore((s) => s.nodes.items)
  const selectZone = useAppStore((s) => s.selectZone)
  const groups = useRef<(Group | null)[]>([])
  const markers = alertMarkers(alerts, zones, nodes)

  useFrame(() => {
    markers.forEach((m, i) => {
      const g = groups.current[i]
      if (g) g.position.y = surfaceHeightAt(state, m.e, m.s) + MARKER_LIFT_M
    })
  })

  return (
    <>
      {markers.map((m, i) => (
        <group
          key={m.key}
          ref={(g) => {
            groups.current[i] = g
          }}
          position={siteToScene(m.e, m.s, state.base + MARKER_LIFT_M)}
        >
          <Html center zIndexRange={[7, 0]}>
            <button
              type="button"
              className="alert-marker"
              data-severity={m.severity}
              data-testid={`alert-marker-${m.id}`}
              title={m.title}
              onClick={() => m.target === 'zone' && selectZone(m.id)}
            >
              !{m.count > 1 ? <span className="alert-marker__count">{m.count}</span> : null}
            </button>
          </Html>
        </group>
      ))}
    </>
  )
}
