// Sentinel Node pins on the twin: one instanced cone per node at its registered position, coloured by
// type (offline grey), each with a "SIMULATED" label. Positions come from the registry snapshot only
// (they change on node.registry, never per sample), so the pins re-render only when a node's position,
// type, source or online state changes. Heights follow the live surface in useFrame.
import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import { Color, ConeGeometry, DoubleSide, Matrix4, MeshBasicMaterial, type Group, type InstancedMesh } from 'three'
import type { Node } from '@bcs/api-types'
import { useAppStore } from '../data/store'
import { OFFLINE_COLOUR, TYPE_COLOUR, TYPE_SHORT, isOnline, sourceText } from '../data/network'
import { siteToScene, surfaceHeightAt } from './surfaceMaterial'
import { useSurfaceState } from './surfaceContext'

/** Pin tip height above the surface and the cone size, in metres (1 scene unit = 1 m). */
export const PIN_LIFT_M = 2
export const PIN_HEIGHT_M = 24
export const PIN_RADIUS_M = 7
/** Above the pin and well above the zone labels (5 m), so the two do not overlap at the oblique preset. */
const LABEL_LIFT_M = PIN_LIFT_M + PIN_HEIGHT_M + 14

export interface Pin {
  id: string
  type: Node['node_type']
  source: Node['source']
  online: boolean
  e: number
  s: number
  colour: string
}

/** Pins for the active (not decommissioned) nodes; offline or unknown nodes are grey. */
export function pinsFromNodes(nodes: Node[]): Pin[] {
  return nodes
    .filter((n) => n.status !== 'decommissioned')
    .map((n) => ({
      id: n.id,
      type: n.node_type,
      source: n.source,
      online: isOnline(n),
      e: n.position.e_m,
      s: n.position.s_m,
      colour: isOnline(n) ? TYPE_COLOUR[n.node_type] : OFFLINE_COLOUR,
    }))
}

/** A string that changes only when something a map layer draws changes (not on every sample). */
export function layerSignature(nodes: Node[]): string {
  return pinsFromNodes(nodes)
    .map((p) => `${p.id}:${p.type}:${p.source}:${p.online ? 1 : 0}:${p.e.toFixed(2)}:${p.s.toFixed(2)}`)
    .join('|')
}

/** The pins, recomputed only when the layer signature moves. */
export function usePins(): Pin[] {
  const sig = useAppStore((s) => layerSignature(s.nodes.items))
  // eslint-disable-next-line react-hooks/exhaustive-deps -- the signature captures everything drawn
  return useMemo(() => pinsFromNodes(useAppStore.getState().nodes.items), [sig])
}

const tmp = new Matrix4()
const flip = new Matrix4().makeRotationX(Math.PI) // cone tip points down at the node

export function NodePins() {
  const state = useSurfaceState()
  const pins = usePins()
  const selected = useAppStore((s) => s.ui.selectedNodeId)
  const selectNode = useAppStore((s) => s.selectNode)
  const invalidate = useThree((s) => s.invalidate)
  const mesh = useRef<InstancedMesh>(null)
  const labels = useRef<(Group | null)[]>([])

  const geometry = useMemo(() => new ConeGeometry(PIN_RADIUS_M, PIN_HEIGHT_M, 16).applyMatrix4(flip), [])
  const material = useMemo(() => new MeshBasicMaterial({ side: DoubleSide, toneMapped: false }), [])
  useEffect(
    () => () => {
      geometry.dispose()
      material.dispose()
    },
    [geometry, material],
  )

  useEffect(() => {
    const m = mesh.current
    if (!m) return
    const c = new Color()
    const hadColours = m.instanceColor !== null
    pins.forEach((p, i) => m.setColorAt(i, c.set(p.colour)))
    if (m.instanceColor) m.instanceColor.needsUpdate = true
    // The first setColorAt creates the colour attribute: recompile so the shader uses it.
    if (!hadColours) material.needsUpdate = true
    invalidate()
  }, [pins, material, invalidate])

  useEffect(() => invalidate(), [selected, invalidate])

  useFrame(() => {
    const m = mesh.current
    pins.forEach((p, i) => {
      const h = surfaceHeightAt(state, p.e, p.s)
      const scale = p.id === selected ? 1.5 : 1
      if (m) {
        tmp.makeScale(scale, scale, scale)
        tmp.setPosition(...siteToScene(p.e, p.s, h + PIN_LIFT_M + (PIN_HEIGHT_M * scale) / 2))
        m.setMatrixAt(i, tmp)
      }
      const g = labels.current[i]
      if (g) g.position.y = h + LABEL_LIFT_M
    })
    if (m) {
      m.count = pins.length
      m.instanceMatrix.needsUpdate = true
    }
  })

  return (
    <>
      {pins.length > 0 && (
        <instancedMesh
          key={pins.length}
          ref={mesh}
          args={[geometry, material, pins.length]}
          frustumCulled={false}
          renderOrder={2}
        />
      )}
      {pins.map((p, i) => (
        <group
          key={p.id}
          ref={(g) => {
            labels.current[i] = g
          }}
          position={siteToScene(p.e, p.s, state.base + LABEL_LIFT_M)}
        >
          <Html center zIndexRange={[6, 0]}>
            <button
              type="button"
              className="node-pin-label"
              data-online={p.online}
              data-selected={p.id === selected}
              data-testid={`node-pin-${p.id}`}
              style={{ borderColor: p.colour }}
              title={`${p.id} (${TYPE_SHORT[p.type]})${p.online ? '' : ' — offline'}`}
              onClick={() => selectNode(p.id)}
            >
              <span className="node-pin-label__id">{p.id}</span>
              <span className="node-pin-label__src">{sourceText(p.source)}</span>
            </button>
          </Html>
        </group>
      ))}
    </>
  )
}
