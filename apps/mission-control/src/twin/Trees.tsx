// Low-poly mangroves at the located tree points (TreeLocator, `trees.updated`): a cone canopy over a
// trunk standing on 6 prop roots, as two instanced meshes (canopy; trunk + roots). Tree scale follows
// the zone's health (canopy cover); a zone with dieback >= 15 % gets brown canopies. Heights follow the
// live surface in useFrame (the twin renders on demand, so this runs only when the map repaints).
import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import {
  BufferGeometry,
  Color,
  CylinderGeometry,
  DoubleSide,
  Matrix4,
  MeshBasicMaterial,
  Quaternion,
  Vector3,
  type InstancedMesh,
} from 'three'
import { organicCrownGeometry } from './mangroveGeometry'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import type { TreePoint, ZoneMetrics } from '@bcs/api-types'
import { useAppStore } from '../data/store'
import { siteToScene, surfaceHeightAt } from './surfaceMaterial'
import { useSurfaceState } from './surfaceContext'

export const DIEBACK_BROWN_PCT = 15
export const HEALTHY_CANOPY = '#2f9e44'
export const DIEBACK_CANOPY = '#8b5a2b'
export const WOOD = '#5b4130'
export const PROP_ROOTS = 6

/** Tree scale from the zone's canopy cover: 0.6 (bare) .. 1.4 (full); 1 when the zone is unmeasured. */
export function treeScale(m: Pick<ZoneMetrics, 'canopy_pct'> | undefined): number {
  if (!m || !Number.isFinite(m.canopy_pct)) return 1
  const health = Math.min(1, Math.max(0, m.canopy_pct / 100))
  return 0.6 + 0.8 * health
}

export function treeCanopyColour(m: Pick<ZoneMetrics, 'dieback_pct'> | undefined): string {
  return m && m.dieback_pct >= DIEBACK_BROWN_PCT ? DIEBACK_CANOPY : HEALTHY_CANOPY
}

/** Canopy cone, base at y = 0 of the tree (metres at scale 1). */
export function canopyGeometry(): BufferGeometry {
  return organicCrownGeometry().scale(3.2, 3, 3.2).translate(0, 7.5, 0)
}

/** Trunk plus 6 splayed prop roots meeting the trunk 2.2 m up. */
export function woodGeometry(): BufferGeometry {
  const parts: BufferGeometry[] = [new CylinderGeometry(0.35, 0.45, 4.5, 5).translate(0, 4.25, 0)]
  const up = new Vector3(0, 1, 0)
  for (let i = 0; i < PROP_ROOTS; i++) {
    const a = (i / PROP_ROOTS) * Math.PI * 2
    const foot = new Vector3(Math.cos(a) * 1.8, 0, Math.sin(a) * 1.8)
    const top = new Vector3(0, 2.2, 0)
    const dir = top.clone().sub(foot)
    const len = dir.length()
    const g = new CylinderGeometry(0.12, 0.16, len, 4)
    g.applyQuaternion(new Quaternion().setFromUnitVectors(up, dir.normalize()))
    g.translate((foot.x + top.x) / 2, (foot.y + top.y) / 2, (foot.z + top.z) / 2)
    parts.push(g)
  }
  const merged = mergeGeometries(parts)!
  for (const p of parts) p.dispose()
  return merged
}

const tmp = new Matrix4()
const q = new Quaternion()
const pos = new Vector3()
const scl = new Vector3()

export function Trees() {
  const state = useSurfaceState()
  const invalidate = useThree((s) => s.invalidate)
  const points = useAppStore((s) => s.trees.points?.points)
  const metrics = useAppStore((s) => s.zones.metrics)
  const canopy = useRef<InstancedMesh>(null)
  const wood = useRef<InstancedMesh>(null)

  const trees: TreePoint[] = useMemo(() => points ?? [], [points])
  const geo = useMemo(() => ({ canopy: canopyGeometry(), wood: woodGeometry() }), [])
  const mats = useMemo(
    // DoubleSide: react-three-map's mirrored projection flips the triangle winding.
    () => ({
      canopy: new MeshBasicMaterial({ vertexColors: true, side: DoubleSide, toneMapped: false }),
      wood: new MeshBasicMaterial({ color: WOOD, side: DoubleSide, toneMapped: false }),
    }),
    [],
  )
  useEffect(
    () => () => {
      geo.canopy.dispose()
      geo.wood.dispose()
      mats.canopy.dispose()
      mats.wood.dispose()
    },
    [geo, mats],
  )

  useEffect(() => {
    const m = canopy.current
    if (!m) return
    const c = new Color()
    const hadColours = m.instanceColor !== null
    trees.forEach((t, i) => m.setColorAt(i, c.set(treeCanopyColour(metrics[t.zone_id]))))
    if (m.instanceColor) m.instanceColor.needsUpdate = true
    if (!hadColours) mats.canopy.needsUpdate = true
    invalidate()
  }, [trees, metrics, mats, invalidate])

  useFrame(() => {
    const c = canopy.current
    const w = wood.current
    if (!c || !w) return
    trees.forEach((t, i) => {
      const k = treeScale(metrics[t.zone_id])
      pos.set(...siteToScene(t.e_m, t.s_m, surfaceHeightAt(state, t.e_m, t.s_m)))
      tmp.compose(pos, q, scl.set(k, k, k))
      c.setMatrixAt(i, tmp)
      w.setMatrixAt(i, tmp)
    })
    c.count = w.count = trees.length
    c.instanceMatrix.needsUpdate = true
    w.instanceMatrix.needsUpdate = true
  })

  if (trees.length === 0) return null
  return (
    <group>
      <instancedMesh key={`c${trees.length}`} ref={canopy} args={[geo.canopy, mats.canopy, trees.length]} frustumCulled={false} />
      <instancedMesh key={`w${trees.length}`} ref={wood} args={[geo.wood, mats.wood, trees.length]} frustumCulled={false} />
    </group>
  )
}
