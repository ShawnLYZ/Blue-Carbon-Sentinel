// Risk tiles (design §26): a translucent tile per assessed zone in its risk colour (low green, medium
// yellow, high orange, critical red), coloured from the zone's latest assessment. With "columns" on the
// tiles are extruded by risk score. Tile heights follow the surface at the zone centre.
import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { CylinderGeometry, DoubleSide, MeshBasicMaterial, type Group } from 'three'
import type { Zone } from '@bcs/api-types'
import { riskColor, type RiskClass } from '@bcs/ui'
import { useAppStore } from '../data/store'
import { surfaceHeightAt, zoneCentreSite } from './surfaceMaterial'
import { useSurfaceState } from './surfaceContext'

/** Tile footprint (a 100 m zone with a 2 m gap each side) and heights, metres. */
export const TILE_SIZE_M = 96
export const TILE_HEIGHT_M = 1.5
export const COLUMN_MAX_M = 60
export const TILE_OPACITY = 0.35

/** Tile height: flat, or a column of up to COLUMN_MAX_M by risk score 0..100. */
export function tileHeight(riskScore: number, columns: boolean): number {
  if (!columns) return TILE_HEIGHT_M
  return TILE_HEIGHT_M + (Math.min(100, Math.max(0, riskScore)) / 100) * COLUMN_MAX_M
}

const CLASSES: RiskClass[] = ['low', 'medium', 'high', 'critical']

export function RiskTiles({ zones, columns }: { zones: Pick<Zone, 'id' | 'col' | 'row'>[]; columns: boolean }) {
  const state = useSurfaceState()
  const invalidate = useThree((s) => s.invalidate)
  const byZone = useAppStore((s) => s.assessments.byZone)
  const groups = useRef<(Group | null)[]>([])

  const box = useMemo(() => new CylinderGeometry(0.5, 0.5, 1, 32).translate(0, 0.5, 0), [])
  const mats = useMemo(
    () =>
      Object.fromEntries(
        CLASSES.map((c) => [
          c,
          new MeshBasicMaterial({ color: riskColor(c), transparent: true, opacity: TILE_OPACITY, depthWrite: false, side: DoubleSide, toneMapped: false }),
        ]),
      ) as Record<RiskClass, MeshBasicMaterial>,
    [],
  )
  useEffect(
    () => () => {
      box.dispose()
      for (const m of Object.values(mats)) m.dispose()
    },
    [box, mats],
  )

  const tiles = zones.flatMap((z) => {
    const a = byZone[z.id]
    return a ? [{ zone: z, cls: a.risk_class, h: tileHeight(a.risk_score, columns) }] : []
  })
  useEffect(() => invalidate(), [tiles.length, byZone, columns, invalidate])

  useFrame(() => {
    tiles.forEach((t, i) => {
      const g = groups.current[i]
      if (!g) return
      const [e, s] = zoneCentreSite(t.zone.col, t.zone.row)
      g.position.y = surfaceHeightAt(state, e, s) + 0.5
    })
  })

  return (
    <>
      {tiles.map((t, i) => {
        const [e, s] = zoneCentreSite(t.zone.col, t.zone.row)
        return (
          <group
            key={t.zone.id}
            ref={(g) => {
              groups.current[i] = g
            }}
            position={[e, state.base, s]}
          >
            <mesh geometry={box} material={mats[t.cls]} scale={[TILE_SIZE_M, t.h, TILE_SIZE_M]} renderOrder={3} />
          </group>
        )
      })}
    </>
  )
}
