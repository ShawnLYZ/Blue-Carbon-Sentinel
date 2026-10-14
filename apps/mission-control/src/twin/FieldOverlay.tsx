// The Digital Twin's surface overlay (design §26): one texture blended by the surface shader at a time.
// - NDVI-proxy and land-cover classes come from the latest capture with a class map.
// - Water fields (WQ readings) and soil fields (SP readings) are IDW-interpolated onto a 64 x 64 grid,
//   clipped to the water class (water) or to land (soil) of that class map; with no class map they are
//   drawn unclipped and the legend says so. Field textures are recomputed at most once per second.
// Also mirrors the zone-grid and reality layers into the shared surface state.
import { useEffect, useMemo } from 'react'
import { useThree } from '@react-three/fiber'
import { DataTexture, LinearFilter, NearestFilter, RGBAFormat, UnsignedByteType } from 'three'
import type { Node } from '@bcs/api-types'
import { useAppStore } from '../data/store'
import { idwGrid, maskFromClasses, type FieldPoint } from '../lib/idw'
import { RASTER_SIZE, useLatestRasters } from './captureRasters'
import {
  FIELD_RANGES,
  activeOverlay,
  fieldParam,
  isFieldKey,
  layerOn,
  useOverlayStatus,
  type FieldKey,
} from './layers'
import { OVERLAY_CLASSES, OVERLAY_FIELD, OVERLAY_NDVI, OVERLAY_NONE } from './surfaceMaterial'
import { useSurfaceState } from './surfaceContext'

export const FIELD_GRID = 64
export const FIELD_REFRESH_MS = 1000
const FIELD_OPACITY = 0.78

/** Field readings for a layer: the online nodes of the layer's type with a finite latest value. */
export function fieldPoints(nodes: Node[], key: FieldKey): FieldPoint[] {
  const type = key.startsWith('water:') ? 'water_quality' : 'soil_probe'
  const param = fieldParam(key)
  const out: FieldPoint[] = []
  for (const n of nodes) {
    if (n.node_type !== type || n.status !== 'online') continue
    const v = n.latest?.readings[param]
    if (v === undefined || !Number.isFinite(v)) continue
    out.push({ e: n.position.e_m, s: n.position.s_m, v })
  }
  return out
}

/** Writes a field grid into RGBA bytes: R = value within [min, max] as 0..255, A = 0 for NaN cells. */
export function fieldTextureData(grid: Float32Array, min: number, max: number, out: Uint8Array): void {
  const span = max - min || 1
  for (let i = 0; i < grid.length; i++) {
    const v = grid[i]!
    const o = 4 * i
    if (Number.isNaN(v)) {
      out[o] = out[o + 1] = out[o + 2] = out[o + 3] = 0
      continue
    }
    const t = Math.min(1, Math.max(0, (v - min) / span))
    out[o] = Math.round(t * 255)
    out[o + 1] = 0
    out[o + 2] = 0
    out[o + 3] = 255
  }
}

function texture(size: number, filter: typeof NearestFilter | typeof LinearFilter): DataTexture {
  const t = new DataTexture(new Uint8Array(size * size * 4), size, size, RGBAFormat, UnsignedByteType)
  t.flipY = false // row 0 = north, sampled at t = 0 like the height map
  t.minFilter = filter
  t.magFilter = filter
  t.generateMipmaps = false
  return t
}

export function FieldOverlay() {
  const state = useSurfaceState()
  const invalidate = useThree((s) => s.invalidate)
  const layers = useAppStore((s) => s.ui.layers)
  const overlay = activeOverlay(layers)
  const grid = layerOn(layers, 'grid')
  const reality = layerOn(layers, 'reality')
  const { rasters, loading } = useLatestRasters()

  const fieldTex = useMemo(() => texture(FIELD_GRID, LinearFilter), [])
  const rasterTex = useMemo(() => texture(RASTER_SIZE, NearestFilter), [])
  useEffect(
    () => () => {
      fieldTex.dispose()
      rasterTex.dispose()
    },
    [fieldTex, rasterTex],
  )

  useEffect(() => {
    useOverlayStatus.setState({
      classMap: loading ? 'loading' : rasters?.classes ? 'ok' : 'none',
      ndvi: loading ? 'loading' : rasters?.ndvi ? 'ok' : 'none',
    })
  }, [rasters, loading])

  useEffect(() => {
    state.grid = grid
    state.reality = reality
    invalidate()
  }, [state, grid, reality, invalidate])

  // NDVI-proxy and classes: one upload per raster change.
  useEffect(() => {
    if (overlay !== 'ndvi' && overlay !== 'classes') return
    const src = overlay === 'ndvi' ? rasters?.ndvi : rasters?.classes
    if (!src) {
      state.overlay = { mode: OVERLAY_NONE, texture: null, opacity: 0 }
      invalidate()
      return
    }
    const data = rasterTex.image.data as Uint8Array
    for (let i = 0; i < src.length; i++) {
      data[4 * i] = src[i]!
      data[4 * i + 1] = 0
      data[4 * i + 2] = 0
      data[4 * i + 3] = 255
    }
    rasterTex.needsUpdate = true
    state.overlay =
      overlay === 'ndvi'
        ? { mode: OVERLAY_NDVI, texture: rasterTex, opacity: 0.8 }
        : { mode: OVERLAY_CLASSES, texture: rasterTex, opacity: 0.7 }
    invalidate()
  }, [overlay, rasters, rasterTex, state, invalidate])

  // Water and soil fields: recomputed from the store's latest readings at most once per second.
  useEffect(() => {
    if (!isFieldKey(overlay)) return
    const key = overlay
    const [min, max] = FIELD_RANGES[fieldParam(key)] ?? [0, 1]
    const mask = rasters?.classes
      ? maskFromClasses(rasters.classes, RASTER_SIZE, key.startsWith('water:') ? 'water' : 'land', FIELD_GRID)
      : new Uint8Array(FIELD_GRID * FIELD_GRID).fill(1)
    let dirty = true
    const compute = () => {
      if (!dirty) return
      dirty = false
      const pts = fieldPoints(useAppStore.getState().nodes.items, key)
      fieldTextureData(idwGrid(pts, mask, FIELD_GRID), min, max, fieldTex.image.data as Uint8Array)
      fieldTex.needsUpdate = true
      state.overlay = { mode: OVERLAY_FIELD, texture: fieldTex, opacity: FIELD_OPACITY }
      if (useOverlayStatus.getState().points !== pts.length) useOverlayStatus.setState({ points: pts.length })
      invalidate()
    }
    compute()
    const unsub = useAppStore.subscribe((s, prev) => {
      if (s.nodes.items !== prev.nodes.items) dirty = true
    })
    const timer = setInterval(compute, FIELD_REFRESH_MS)
    return () => {
      unsub()
      clearInterval(timer)
    }
  }, [overlay, rasters, fieldTex, state, invalidate])

  // No overlay layer on: clear it.
  useEffect(() => {
    if (overlay !== null) return
    state.overlay = { mode: OVERLAY_NONE, texture: null, opacity: 0 }
    invalidate()
  }, [overlay, state, invalidate])

  // Leaving the twin page: the surface goes back to its plain look.
  useEffect(
    () => () => {
      state.overlay = { mode: OVERLAY_NONE, texture: null, opacity: 0 }
      state.grid = false
      state.reality = true
      invalidate()
    },
    [state, invalidate],
  )
  return null
}
