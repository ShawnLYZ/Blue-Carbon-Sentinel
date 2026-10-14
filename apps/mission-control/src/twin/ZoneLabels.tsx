// "A1".."E5" at the zone centres (F4), 5 m above the live surface; shown at zoom >= 15 (US 34).
import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import type { Group } from 'three'
import type { Zone } from '@bcs/api-types'
import { siteToScene, surfaceHeightAt, zoneCentreSite, type SurfaceState } from './surfaceMaterial'

export const LABEL_LIFT_M = 5

export function ZoneLabels({ zones, state }: { zones: Pick<Zone, 'id' | 'label' | 'col' | 'row'>[]; state: SurfaceState }) {
  const groups = useRef<(Group | null)[]>([])

  // Follow the surface: the label height tracks the live relief and the exaggeration.
  useFrame(() => {
    zones.forEach((z, i) => {
      const g = groups.current[i]
      if (!g) return
      const [e, s] = zoneCentreSite(z.col, z.row)
      g.position.y = surfaceHeightAt(state, e, s) + LABEL_LIFT_M
    })
  })

  return (
    <>
      {zones.map((z, i) => {
        const [e, s] = zoneCentreSite(z.col, z.row)
        return (
          <group
            key={z.id}
            ref={(g) => {
              groups.current[i] = g
            }}
            position={siteToScene(e, s, state.base + LABEL_LIFT_M)}
          >
            <Html center zIndexRange={[5, 0]} style={{ pointerEvents: 'none' }}>
              <span className="zone-label">{z.label}</span>
            </Html>
          </group>
        )
      })}
    </>
  )
}
