// The Canopy Map and the Forest Model (PRD decision 7, addendum A0.1). Pure functions, run in a Web Worker.

import { CANOPY_RINGS, WATER_RINGS } from '../site/canopyOutlines'
import { fbm2, rng } from '../sim/noise'

export const N = 500 // 1 m pixels across the Footprint
export const GRID = 251 // terrain vertices across (2 m spacing)
export const WATER_LEVEL = -0.15
export const MUD = 0
export const CANOPY = 1
export const WATER = 2

/** Tree record stride: x, z, height, crownScale, rotation, variant, tint, lean */
export const TREE_STRIDE = 8
/** Breathing-root record stride: x, z, height, rotation */
export const ROOT_STRIDE = 4

export interface ForestModel {
  classes: Uint8Array
  heights: Float32Array
  info: Uint8Array
  trees: Float32Array
  roots: Float32Array
  areaM2: number
}

/** Even-odd scanline fill at 2 x 2 samples per pixel; a pixel is set when any sample is inside. */
function rasterise(rings: number[][], out: Uint8Array, value: number) {
  const xs: number[] = []
  for (let row = 0; row < N * 2; row++) {
    const y = (row + 0.5) / 2 - 250
    xs.length = 0
    for (const r of rings) {
      const n = r.length / 2
      for (let i = 0, j = n - 1; i < n; j = i++) {
        const xi = r[i * 2], zi = r[i * 2 + 1], xj = r[j * 2], zj = r[j * 2 + 1]
        if ((zi > y) !== (zj > y)) xs.push(xi + ((y - zi) / (zj - zi)) * (xj - xi))
      }
    }
    xs.sort((a, b) => a - b)
    const py = row >> 1
    for (let k = 0; k + 1 < xs.length; k += 2) {
      const a = Math.max(0, Math.ceil((xs[k] + 250) * 2 - 0.5))
      const b = Math.min(N * 2 - 1, Math.floor((xs[k + 1] + 250) * 2 - 0.5))
      for (let c = a; c <= b; c++) out[py * N + (c >> 1)] = value
    }
  }
}

export function canopyMap(): Uint8Array {
  const m = new Uint8Array(N * N)
  rasterise(CANOPY_RINGS, m, CANOPY)
  rasterise(WATER_RINGS, m, WATER)
  return m
}

function boxBlur(src: Float32Array, r: number, passes = 3): Float32Array {
  let a = Float32Array.from(src)
  let b = new Float32Array(N * N)
  const w = 2 * r + 1
  for (let p = 0; p < passes; p++) {
    for (let y = 0; y < N; y++) {
      let acc = 0
      for (let x = -r; x <= r; x++) acc += a[y * N + Math.min(N - 1, Math.max(0, x))]
      for (let x = 0; x < N; x++) {
        b[y * N + x] = acc / w
        acc += a[y * N + Math.min(N - 1, x + r + 1)] - a[y * N + Math.max(0, x - r)]
      }
    }
    for (let x = 0; x < N; x++) {
      let acc = 0
      for (let y = -r; y <= r; y++) acc += b[Math.min(N - 1, Math.max(0, y)) * N + x]
      for (let y = 0; y < N; y++) {
        a[y * N + x] = acc / w
        acc += b[Math.min(N - 1, y + r + 1) * N + x] - b[Math.max(0, y - r) * N + x]
      }
    }
  }
  return a
}

function morph(mask: Uint8Array, r: number, dilate: boolean): Uint8Array {
  const out = new Uint8Array(N * N)
  const offs: [number, number][] = []
  for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) if (dx * dx + dy * dy <= r * r) offs.push([dx, dy])
  for (let y = 0; y < N; y++) {
    for (let x = 0; x < N; x++) {
      let v = dilate ? 0 : 1
      for (const [dx, dy] of offs) {
        const xx = x + dx, yy = y + dy
        const m = xx < 0 || yy < 0 || xx >= N || yy >= N ? (dilate ? 0 : 1) : mask[yy * N + xx]
        if (dilate && m) { v = 1; break }
        if (!dilate && !m) { v = 0; break }
      }
      out[y * N + x] = v
    }
  }
  return out
}

/** Mangrove area: canopy after a morphological closing with a 2 m radius. */
export function mangroveAreaM2(classes: Uint8Array): number {
  const m = new Uint8Array(N * N)
  for (let i = 0; i < m.length; i++) m[i] = classes[i] === CANOPY ? 1 : 0
  const closed = morph(morph(m, 2, true), 2, false)
  let n = 0
  for (let i = 0; i < closed.length; i++) n += closed[i]
  return n
}

const smoothstep = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)))
  return t * t * (3 - 2 * t)
}

function sample(f: Float32Array, x: number, z: number): number {
  const px = Math.min(N - 1, Math.max(0, x + 250 - 0.5))
  const pz = Math.min(N - 1, Math.max(0, z + 250 - 0.5))
  const i = Math.floor(px), j = Math.floor(pz)
  const i1 = Math.min(N - 1, i + 1), j1 = Math.min(N - 1, j + 1)
  const fx = px - i, fz = pz - j
  const a = f[j * N + i] + (f[j * N + i1] - f[j * N + i]) * fx
  const b = f[j1 * N + i] + (f[j1 * N + i1] - f[j1 * N + i]) * fx
  return a + (b - a) * fz
}

export function buildForest(): ForestModel {
  const classes = canopyMap()
  const water = new Float32Array(N * N)
  const canopy = new Float32Array(N * N)
  for (let i = 0; i < classes.length; i++) {
    water[i] = classes[i] === WATER ? 1 : 0
    canopy[i] = classes[i] === CANOPY ? 1 : 0
  }
  const waterNear = boxBlur(water, 2)
  const waterWide = boxBlur(water, 6)
  const canopyNear = boxBlur(canopy, 2)
  const canopyWide = boxBlur(canopy, 4)

  // Terrain heights on a 2 m grid: gentle mud undulation, slightly raised under the forest, channels below water.
  const heights = new Float32Array(GRID * GRID)
  for (let j = 0; j < GRID; j++) {
    for (let i = 0; i < GRID; i++) {
      const x = i * 2 - 250, z = j * 2 - 250
      const base = 0.12 + 0.22 * fbm2(x / 46, z / 46, 3, 3) + 0.06 * fbm2(x / 7, z / 7, 9, 2)
      const raise = 0.22 * sample(canopyWide, x, z)
      const wn = sample(waterNear, x, z)
      const ww = sample(waterWide, x, z)
      const dip = 0.9 * smoothstep(0.05, 0.75, wn) + 1.3 * smoothstep(0.35, 1, ww)
      heights[j * GRID + i] = base + raise - dip
    }
  }

  // Info texture: R wetness, G canopy shade, B water presence, A open-ground dryness.
  const info = new Uint8Array(N * N * 4)
  for (let i = 0; i < N * N; i++) {
    info[i * 4] = Math.round(255 * Math.min(1, waterWide[i] * 2.2))
    info[i * 4 + 1] = Math.round(255 * canopyNear[i])
    info[i * 4 + 2] = Math.round(255 * waterNear[i])
    info[i * 4 + 3] = Math.round(255 * (1 - canopyWide[i]) * (1 - Math.min(1, waterWide[i] * 3)))
  }

  // Trees: one seeded dart-throwing pass over canopy pixels (Year 1 cohort), about 4.4 m apart.
  const R = 4.4
  const rand = rng(20261017)
  const cand: number[] = []
  for (let i = 0; i < classes.length; i++) if (classes[i] === CANOPY) cand.push(i)
  for (let i = cand.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1))
    const t = cand[i]; cand[i] = cand[j]; cand[j] = t
  }
  const cell = R
  const gw = Math.ceil(N / cell)
  const grid: number[][] = Array.from({ length: gw * gw }, () => [])
  const pts: number[] = []
  for (const idx of cand) {
    const x = (idx % N) + rand() - 250
    const z = Math.floor(idx / N) + rand() - 250
    const gx = Math.floor((x + 250) / cell), gz = Math.floor((z + 250) / cell)
    let ok = true
    for (let dz = -1; dz <= 1 && ok; dz++) {
      for (let dx = -1; dx <= 1 && ok; dx++) {
        const cx = gx + dx, cz = gz + dz
        if (cx < 0 || cz < 0 || cx >= gw || cz >= gw) continue
        for (const k of grid[cz * gw + cx]) {
          const ex = pts[k * 2] - x, ez = pts[k * 2 + 1] - z
          if (ex * ex + ez * ez < R * R) { ok = false; break }
        }
      }
    }
    if (!ok) continue
    grid[gz * gw + gx].push(pts.length / 2)
    pts.push(x, z)
  }
  const count = pts.length / 2
  const trees = new Float32Array(count * TREE_STRIDE)
  for (let k = 0; k < count; k++) {
    const x = pts[k * 2], z = pts[k * 2 + 1]
    const inner = smoothstep(0.45, 0.95, sample(canopyWide, x, z))
    const stand = 0.5 + 0.5 * fbm2(x / 85, z / 85, 17, 3)
    let h = 9 + 7.5 * stand + (rand() - 0.5) * 3
    h *= 0.74 + 0.26 * inner
    h = Math.min(18, Math.max(8, h))
    const o = k * TREE_STRIDE
    trees[o] = x
    trees[o + 1] = z
    trees[o + 2] = h
    trees[o + 3] = 0.86 + rand() * 0.34
    trees[o + 4] = rand() * Math.PI * 2
    trees[o + 5] = Math.floor(rand() * 4)
    trees[o + 6] = rand()
    trees[o + 7] = (rand() - 0.5) * 0.09
  }

  // Breathing roots: scattered on mud and the forest fringe close to water.
  const roots: number[] = []
  const rr = rng(77)
  for (let i = 0; i < classes.length && roots.length < 32_000 * ROOT_STRIDE; i++) {
    if (classes[i] === WATER) continue
    const near = Math.min(1, waterWide[i] * 2.6)
    const fringe = classes[i] === MUD ? smoothstep(0.1, 0.5, canopyWide[i]) * 0.5 : 0
    const p = Math.max(near * (classes[i] === CANOPY ? 0.35 : 0.9), fringe)
    if (p <= 0.02) continue
    const n = rr() < p ? (rr() < p ? 2 : 1) : 0
    for (let c = 0; c < n; c++) {
      roots.push((i % N) + rr() - 250, Math.floor(i / N) + rr() - 250, 0.14 + rr() * 0.26, rr() * Math.PI * 2)
    }
  }

  return { classes, heights, info, trees, roots: new Float32Array(roots), areaM2: mangroveAreaM2(classes) }
}

/** Terrain height at any local point, bilinear on the 2 m grid. */
export function heightAt(heights: Float32Array, x: number, z: number): number {
  const gx = Math.min(GRID - 1.0001, Math.max(0, (x + 250) / 2))
  const gz = Math.min(GRID - 1.0001, Math.max(0, (z + 250) / 2))
  const i = Math.floor(gx), j = Math.floor(gz)
  const fx = gx - i, fz = gz - j
  const a = heights[j * GRID + i] + (heights[j * GRID + i + 1] - heights[j * GRID + i]) * fx
  const b = heights[(j + 1) * GRID + i] + (heights[(j + 1) * GRID + i + 1] - heights[(j + 1) * GRID + i]) * fx
  return a + (b - a) * fz
}
