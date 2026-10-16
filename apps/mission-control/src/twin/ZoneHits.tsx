// Zone hit targets: an invisible 100 x 100 m plane per zone, raycast with R3F's onClick, selects the
// zone (ui.selectedZoneId) for the Digital Twin's zone card. The selected zone gets an accent outline.
// Planes follow the surface height at the zone centre.
import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree, type ThreeEvent } from '@react-three/fiber'
import { DoubleSide, EdgesGeometry, RingGeometry, LineBasicMaterial, MeshBasicMaterial, PlaneGeometry, type Group } from 'three'
import type { Zone } from '@bcs/api-types'
import { useAppStore } from '../data/store'
import { surfaceHeightAt, zoneCentreSite } from './surfaceMaterial'
import { useSurfaceState } from './surfaceContext'

export const HIT_LIFT_M = 2
const ACCENT = '#3fe0d0'

export interface ZoneHitsProps {
  zones: Pick<Zone, 'id' | 'col' | 'row'>[]
  /** Overrides the store selection (Time Travel's "with" map selects its own plan zone). */
  selected?: string | null
  onSelect?: (zoneId: string) => void
  /** Hit mesh names are `${namePrefix}${zone id}`. */
  namePrefix?: string
}

export function ZoneHits({ zones, selected: selectedProp, onSelect, namePrefix = 'zone-hit-' }: ZoneHitsProps) {
  const state = useSurfaceState()
  const invalidate = useThree((s) => s.invalidate)
  const storeSelected = useAppStore((s) => s.ui.selectedZoneId)
  const storeSelect = useAppStore((s) => s.selectZone)
  const selected = selectedProp === undefined ? storeSelected : selectedProp
  const selectZone = onSelect ?? storeSelect
  const groups = useRef<(Group | null)[]>([])

  // A flat 100 m square in the scene's x (east) / z (south) plane.
  const plane = useMemo(() => new PlaneGeometry(100, 100).rotateX(-Math.PI / 2), [])
  const edges = useMemo(() => new EdgesGeometry(new RingGeometry(47.8, 48, 48).rotateX(-Math.PI / 2)), [])
  // Drawn into neither colour nor depth: a pure raycast target.
  const hitMat = useMemo(
    () => new MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false, colorWrite: false, side: DoubleSide }),
    [],
  )
  const lineMat = useMemo(() => new LineBasicMaterial({ color: ACCENT, toneMapped: false }), [])
  useEffect(
    () => () => {
      plane.dispose()
      edges.dispose()
      hitMat.dispose()
      lineMat.dispose()
    },
    [plane, edges, hitMat, lineMat],
  )
  useEffect(() => invalidate(), [selected, invalidate])

  useFrame(() => {
    zones.forEach((z, i) => {
      const g = groups.current[i]
      if (!g) return
      const [e, s] = zoneCentreSite(z.col, z.row)
      g.position.y = surfaceHeightAt(state, e, s) + HIT_LIFT_M
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
            position={[e, state.base + HIT_LIFT_M, s]}
          >
            <mesh
              name={`${namePrefix}${z.id}`}
              geometry={plane}
              material={hitMat}
              onClick={(ev: ThreeEvent<MouseEvent>) => {
                ev.stopPropagation()
                selectZone(z.id)
              }}
            />
            {z.id === selected && <lineSegments geometry={edges} material={lineMat} renderOrder={4} />}
          </group>
        )
      })}
    </>
  )
}
