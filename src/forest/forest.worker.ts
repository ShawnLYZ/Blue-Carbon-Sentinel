// Web Worker: builds the Forest Model once, and paints the Digital Twin layer overlay (500 x 500, 1 m).
// The overlay only colours the ground around each sensor post: there is no data between posts.

import { buildForest, N } from './model'
import { SENSORS, stressOf, type Reading, type SensorId } from '../sim/ranges'
import { STRESS_LUT } from './stressColor'
import { POST_RADIUS_M, SENSOR_POSTS } from '../site/catalogue'

export type WorkerRequest =
  | { type: 'build' }
  | { type: 'overlay'; seq: number; layer: SensorId | 'natural'; posts: Reading[] }

let nearest: Int8Array | null = null
let falloff: Float32Array | null = null

/** For every pixel: the nearest post within reach (or -1) and how strongly its colour shows there. */
function prepareZones() {
  if (nearest && falloff) return
  nearest = new Int8Array(N * N).fill(-1)
  falloff = new Float32Array(N * N)
  const r2 = POST_RADIUS_M * POST_RADIUS_M
  for (let j = 0; j < N; j++) {
    for (let i = 0; i < N; i++) {
      const x = i + 0.5 - 250, z = j + 0.5 - 250
      let best = -1, bestD2 = r2
      for (let k = 0; k < SENSOR_POSTS.length; k++) {
        const dx = x - SENSOR_POSTS[k].x, dz = z - SENSOR_POSTS[k].z
        const d2 = dx * dx + dz * dz
        if (d2 < bestD2) { bestD2 = d2; best = k }
      }
      if (best < 0) continue
      const p = j * N + i
      nearest[p] = best
      // Solid core, soft rim.
      const e = Math.min(1, (1 - Math.sqrt(bestD2) / POST_RADIUS_M) / 0.35)
      falloff[p] = e * e * (3 - 2 * e)
    }
  }
}

function paint(layer: SensorId | 'natural', posts: Reading[]): Uint8Array {
  prepareZones()
  const near = nearest!, fall = falloff!
  const out = new Uint8Array(N * N * 4)
  // One stress value per post, then each pixel just looks up its post.
  const stress = posts.map((r) => {
    if (layer !== 'natural') return Math.min(3, stressOf(layer, r[layer]))
    let worst = 0
    for (const s of SENSORS) worst = Math.max(worst, stressOf(s.id, r[s.id]))
    return worst
  })
  for (let p = 0; p < N * N; p++) {
    const k = near[p]
    if (k < 0) continue
    const s = stress[k]
    const li = Math.round((Math.min(3, s) / 3) * 255) * 3
    let a: number
    if (layer === 'natural') {
      // Natural: no tint, except a red bloom around posts whose readings are outside the healthy range.
      const g = Math.min(1, Math.max(0, (s - 0.95) / 1.0))
      a = g * g * (3 - 2 * g) * 200 * fall[p]
    } else {
      a = 255 * fall[p]
    }
    out[p * 4] = STRESS_LUT[li]
    out[p * 4 + 1] = STRESS_LUT[li + 1]
    out[p * 4 + 2] = STRESS_LUT[li + 2]
    out[p * 4 + 3] = Math.round(a)
  }
  return out
}

self.onmessage = (e: MessageEvent<WorkerRequest>) => {
  const msg = e.data
  if (msg.type === 'build') {
    const m = buildForest()
    ;(self as unknown as Worker).postMessage({ type: 'built', model: m }, [
      m.classes.buffer, m.heights.buffer, m.info.buffer, m.trees.buffer, m.roots.buffer,
    ])
    prepareZones()
  } else if (msg.type === 'overlay') {
    const rgba = paint(msg.layer, msg.posts)
    ;(self as unknown as Worker).postMessage({ type: 'overlay', seq: msg.seq, layer: msg.layer, rgba }, [rgba.buffer])
  }
}
