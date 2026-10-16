// Carbon columns (design §26): a teal column per zone, its height proportional to the zone's carbon stock
// (tCO₂e), capped at COLUMN_MAX_M. Heights follow the surface at the zone centre.
import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { CylinderGeometry, InstancedMesh, MeshBasicMaterial, Object3D } from 'three'
import type { Zone } from '@bcs/api-types'
import { useCarbonSummary } from '../data/carbon'
import { surfaceHeightAt, zoneCentreSite } from './surfaceMaterial'
import { useSurfaceState } from './surfaceContext'
import { columnHeight, columnScale } from './columnMath'

export const COLUMN_SIZE_M = 40
export const CARBON_TEAL = '#1fb6a6'

export function CarbonColumns({ zones }: { zones: Pick<Zone, 'id' | 'col' | 'row'>[] }) {
  const state = useSurfaceState()
  const invalidate = useThree((s) => s.invalidate)
  const perZone = useCarbonSummary((s) => s.summary?.per_zone)
  const mesh = useRef<InstancedMesh>(null)
  const dummy = useMemo(() => new Object3D(), [])
  const box = useMemo(() => new CylinderGeometry(0.5, 0.5, 1, 24).translate(0, 0.5, 0), [])
  const mat = useMemo(() => new MeshBasicMaterial({ color: CARBON_TEAL, transparent: true, opacity: 0.8, toneMapped: false }), [])
  useEffect(
    () => () => {
      box.dispose()
      mat.dispose()
    },
    [box, mat],
  )
  const scale = useMemo(() => columnScale(Object.values(perZone ?? {})), [perZone])
  const cols = zones.flatMap((z) => (perZone && perZone[z.id] !== undefined ? [{ zone: z, h: columnHeight(perZone[z.id]!, scale) }] : []))
  useEffect(() => invalidate(), [perZone, invalidate])

  useFrame(() => {
    const m = mesh.current
    if (!m) return
    cols.forEach((c, i) => {
      const [e, s] = zoneCentreSite(c.zone.col, c.zone.row)
      dummy.position.set(e, surfaceHeightAt(state, e, s) + 0.5, s)
      dummy.scale.set(COLUMN_SIZE_M, Math.max(0.01, c.h), COLUMN_SIZE_M)
      dummy.updateMatrix()
      m.setMatrixAt(i, dummy.matrix)
    })
    m.count = cols.length
    m.instanceMatrix.needsUpdate = true
  })

  return <instancedMesh key={zones.length} ref={mesh} args={[box, mat, Math.max(1, zones.length)]} renderOrder={4} frustumCulled={false} />
}

