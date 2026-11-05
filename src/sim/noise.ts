// Small deterministic noise helpers. Same inputs always give the same outputs.

export function hash1(n: number): number {
  let x = Math.imul((n | 0) ^ 0x9e3779b9, 0x85ebca6b)
  x ^= x >>> 13
  x = Math.imul(x, 0xc2b2ae35)
  x ^= x >>> 16
  return (x >>> 0) / 4294967296
}

export function hash2(i: number, j: number, seed = 0): number {
  return hash1(Math.imul(i | 0, 374761393) + Math.imul(j | 0, 668265263) + Math.imul(seed | 0, 2147483647))
}

const smooth = (t: number) => t * t * (3 - 2 * t)

/** 1D value noise in [-1, 1]. */
export function noise1(t: number, seed: number): number {
  const i = Math.floor(t)
  const f = smooth(t - i)
  const a = hash1(i * 7919 + seed * 104729)
  const b = hash1((i + 1) * 7919 + seed * 104729)
  return (a + (b - a) * f) * 2 - 1
}

/** 2D value noise in [-1, 1]. */
export function noise2(x: number, y: number, seed: number): number {
  const i = Math.floor(x)
  const j = Math.floor(y)
  const fx = smooth(x - i)
  const fy = smooth(y - j)
  const a = hash2(i, j, seed)
  const b = hash2(i + 1, j, seed)
  const c = hash2(i, j + 1, seed)
  const d = hash2(i + 1, j + 1, seed)
  const top = a + (b - a) * fx
  const bottom = c + (d - c) * fx
  return (top + (bottom - top) * fy) * 2 - 1
}

/** Fractal 2D noise, roughly in [-1, 1]. */
export function fbm2(x: number, y: number, seed: number, octaves = 3): number {
  let sum = 0
  let amp = 0.5
  let norm = 0
  let f = 1
  for (let o = 0; o < octaves; o++) {
    sum += noise2(x * f, y * f, seed + o * 31) * amp
    norm += amp
    amp *= 0.5
    f *= 2.03
  }
  return sum / norm
}

/** Mulberry32 seeded random generator. */
export function rng(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
