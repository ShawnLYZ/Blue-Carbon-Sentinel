// Time Travel's procedural trees (design §21): the base capture's located trees (M4 TreeLocator points)
// and, on the "with restoration" map, saplings in planted zones.
// - Declining zones: each tree fades, browns and falls (a rotation about its base), in proportion to the
//   zone's canopy-loss fraction since 2026 (a tree dies when its own fixed threshold is below the loss).
// - Planted zones: instanced saplings, placed on the zone's mud pixels when the class map is known, grow
//   with the cohort fraction (or, when the API does not pass it, with the canopy gained over "without").
// Matrices are rebuilt only when the year, heights or inputs change, never per repaint.
import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { Color, DoubleSide, Matrix4, MeshBasicMaterial, Quaternion, Vector3, type InstancedMesh } from 'three'
import type { Forecast, TreePoint, YearPoint } from '@bcs/api-types'
import { interpYear, type Scenario, type YearPointExtra } from '../lib/interp'
import { RASTER_SIZE } from './captureRasters'
import { siteToScene, surfaceHeightAt, type SurfaceState } from './surfaceMaterial'
import { DIEBACK_CANOPY, HEALTHY_CANOPY, WOOD, canopyGeometry, woodGeometry } from './Trees'

const DEAD_GREY = '#8a8478'
const SAPLING = '#6fd36a'
const MUD_CODE = 3
/** A tree's decline runs over this much extra canopy loss past its threshold (0..1 of the zone). */
const DECLINE_SPAN = 0.15
export const MAX_SAPLINGS_PER_ZONE = 80

/** Deterministic 0..1 hash of an integer and a salt. */
export function hash01(i: number, salt = 0): number {
  let x = (i * 374761393 + salt * 668265263) | 0
  x = Math.imul(x ^ (x >>> 13), 1274126177)
  x = x ^ (x >>> 16)
  return (x >>> 0) / 4294967296
}

/** Canopy lost since 2026 as a fraction of the 2026 canopy (0..1). */
export function canopyLoss(series: YearPoint[] | undefined, year: number): number {
  if (!series?.length) return 0
  const c0 = series[0]!.canopy.central
  if (c0 <= 1e-6) return 0
  return Math.min(1, Math.max(0, (c0 - interpYear(series, year).canopy.central) / c0))
}

/** How far tree `i` (with threshold hash01(i)) has declined at zone loss `loss`: 0 healthy .. 1 fallen. */
export function treeDecline(i: number, loss: number): number {
  const r = hash01(i, 1) * (1 - DECLINE_SPAN)
  return Math.min(1, Math.max(0, (loss - r) / DECLINE_SPAN))
}

/** Sapling growth 0..1: the cohort fraction when present, else the canopy gained over "without", normalised. */
export function saplingGrowth(withSeries: YearPoint[] | undefined, withoutSeries: YearPoint[] | undefined, year: number): number {
  if (!withSeries?.length) return 0
  const p = interpYear(withSeries, year) as YearPointExtra
  if (typeof p.cohort_fraction === 'number') return Math.min(1, Math.max(0, p.cohort_fraction))
  if (!withoutSeries?.length) return 0
  const gain = (y: number) => interpYear(withSeries, y).canopy.central - interpYear(withoutSeries, y).canopy.central
  const last = withSeries[withSeries.length - 1]!.year
  const full = Math.max(0.005, gain(last))
  return Math.min(1, Math.max(0, gain(year) / full))
}

/** Sapling positions (site metres) inside zone (col, row): on mud pixels of the class map when there are any. */
export function saplingSpots(col: number, row: number, count: number, classes: Uint8Array | null): [number, number][] {
  const out: [number, number][] = []
  const px = RASTER_SIZE / 5
  const mud: number[] = []
  if (classes) {
    for (let y = Math.floor(row * px); y < Math.floor((row + 1) * px); y++)
      for (let x = Math.floor(col * px); x < Math.floor((col + 1) * px); x++)
        if (classes[y * RASTER_SIZE + x] === MUD_CODE) mud.push(y * RASTER_SIZE + x)
  }
  const m = 500 / RASTER_SIZE
  for (let k = 0; k < count; k++) {
    if (mud.length) {
      const p = mud[Math.floor(hash01(k, col * 7 + row * 131) * mud.length)]!
      out.push([((p % RASTER_SIZE) + hash01(k, 3)) * m, (Math.floor(p / RASTER_SIZE) + hash01(k, 4)) * m])
    } else out.push([col * 100 + 10 + hash01(k, 5) * 80, row * 100 + 10 + hash01(k, 6) * 80])
  }
  return out
}

export interface Planting {
  zoneId: string
  col: number
  row: number
  saplings: number
}

export interface FutureTreesProps {
  state: SurfaceState
  trees: TreePoint[]
  forecast: Forecast
  scenario: Scenario
  year: number
  /** Planted zones of the forecast's plan ("with" map only). */
  plantings: Planting[]
  classes: Uint8Array | null
  /** Bumps when the surface heights changed (the trees follow the ground). */
  heightsRev: number
}

const tmp = new Matrix4()
const q = new Quaternion()
const pos = new Vector3()
const scl = new Vector3()
const axis = new Vector3()
const healthy = new Color(HEALTHY_CANOPY)
const brown = new Color(DIEBACK_CANOPY)
const grey = new Color(DEAD_GREY)

export function FutureTrees({ state, trees, forecast, scenario, year, plantings, classes, heightsRev }: FutureTreesProps) {
  const invalidate = useThree((s) => s.invalidate)
  const canopy = useRef<InstancedMesh>(null)
  const wood = useRef<InstancedMesh>(null)
  const saplings = useRef<InstancedMesh>(null)
  const dirty = useRef(true)

  const geo = useMemo(() => ({ canopy: canopyGeometry(), wood: woodGeometry(), sapling: canopyGeometry().scale(0.4, 0.4, 0.4) }), [])
  const mats = useMemo(
    () => ({
      canopy: new MeshBasicMaterial({ vertexColors: true, side: DoubleSide, toneMapped: false }),
      wood: new MeshBasicMaterial({ color: WOOD, side: DoubleSide, toneMapped: false }),
      sapling: new MeshBasicMaterial({ vertexColors: true, color: SAPLING, side: DoubleSide, toneMapped: false }),
    }),
    [],
  )
  useEffect(
    () => () => {
      for (const g of Object.values(geo)) g.dispose()
      for (const m of Object.values(mats)) m.dispose()
    },
    [geo, mats],
  )

  const spots = useMemo(
    () =>
      plantings.flatMap((p) =>
        saplingSpots(p.col, p.row, Math.min(MAX_SAPLINGS_PER_ZONE, Math.max(8, Math.round(p.saplings / 50))), classes).map(
          (s) => ({ zoneId: p.zoneId, e: s[0], s: s[1] }),
        ),
      ),
    [plantings, classes],
  )

  useEffect(() => {
    dirty.current = true
    invalidate()
  }, [trees, forecast, scenario, year, spots, heightsRev, invalidate])

  useFrame(() => {
    if (!dirty.current) return
    dirty.current = false
    const zones = forecast.scenarios[scenario].zones
    const c = canopy.current
    const w = wood.current
    if (c && w) {
      const col = new Color()
      const hadColours = c.instanceColor !== null
      const loss: Record<string, number> = {}
      trees.forEach((t, i) => {
        const l = (loss[t.zone_id] ??= canopyLoss(zones[t.zone_id], year))
        const d = treeDecline(i, l)
        const a = hash01(i, 2) * Math.PI * 2
        q.setFromAxisAngle(axis.set(Math.cos(a), 0, Math.sin(a)), d * (Math.PI / 2) * 0.95)
        const k = 1 - 0.25 * d
        pos.set(...siteToScene(t.e_m, t.s_m, surfaceHeightAt(state, t.e_m, t.s_m)))
        tmp.compose(pos, q, scl.set(k, k, k))
        c.setMatrixAt(i, tmp)
        w.setMatrixAt(i, tmp)
        col.copy(healthy).lerp(brown, Math.min(1, d * 1.5)).lerp(grey, d * d)
        c.setColorAt(i, col)
      })
      c.count = w.count = trees.length
      c.instanceMatrix.needsUpdate = true
      w.instanceMatrix.needsUpdate = true
      if (c.instanceColor) c.instanceColor.needsUpdate = true
      if (!hadColours && trees.length) mats.canopy.needsUpdate = true // the shader gains instance colours
    }
    const s = saplings.current
    if (s) {
      const grow: Record<string, number> = {}
      q.identity()
      spots.forEach((p, i) => {
        const g = (grow[p.zoneId] ??= saplingGrowth(zones[p.zoneId], forecast.scenarios.without.zones[p.zoneId], year))
        const k = 0.15 + 0.85 * g
        pos.set(...siteToScene(p.e, p.s, surfaceHeightAt(state, p.e, p.s)))
        tmp.compose(pos, q, scl.set(k, k * (0.8 + 0.4 * hash01(i, 9)), k))
        s.setMatrixAt(i, tmp)
      })
      s.count = spots.length
      s.instanceMatrix.needsUpdate = true
    }
  })

  return (
    <group>
      {trees.length > 0 && (
        <>
          <instancedMesh key={`c${trees.length}`} ref={canopy} args={[geo.canopy, mats.canopy, trees.length]} frustumCulled={false} />
          <instancedMesh key={`w${trees.length}`} ref={wood} args={[geo.wood, mats.wood, trees.length]} frustumCulled={false} />
        </>
      )}
      {spots.length > 0 && (
        <instancedMesh key={`s${spots.length}`} ref={saplings} args={[geo.sapling, mats.sapling, spots.length]} frustumCulled={false} />
      )}
    </group>
  )
}
