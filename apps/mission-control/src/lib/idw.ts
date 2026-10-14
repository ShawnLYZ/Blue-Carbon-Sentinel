// Inverse-distance weighting of node readings onto the site grid (design §26 water and soil fields).
//
// The grid covers the 500 x 500 m site (addendum F4): `size` x `size` cells, row-major, row 0 on the
// north edge (s = 0) and column 0 on the west edge (e = 0), the same orientation as the height map and
// the class map. Cells outside the mask are NaN, which the field texture draws transparent.

export const SITE_M = 500

export interface FieldPoint {
  /** Site metres east of the NW anchor. */
  e: number
  /** Site metres south of the NW anchor. */
  s: number
  v: number
}

/**
 * IDW-interpolated grid. Each cell takes sum(v_i / d_i^p) / sum(1 / d_i^p) over every point, measured
 * from the cell centre; a point inside a cell's centre (d < 1e-6) gives that cell its value exactly.
 * With no points every cell is NaN.
 */
export function idwGrid(points: FieldPoint[], mask: Uint8Array, size = 64, power = 2): Float32Array {
  const out = new Float32Array(size * size).fill(Number.NaN)
  const pts = points.filter((p) => Number.isFinite(p.v) && Number.isFinite(p.e) && Number.isFinite(p.s))
  if (pts.length === 0) return out
  const cell = SITE_M / size
  for (let row = 0; row < size; row++) {
    const s = (row + 0.5) * cell
    for (let col = 0; col < size; col++) {
      const i = row * size + col
      if (!mask[i]) continue
      const e = (col + 0.5) * cell
      let num = 0
      let den = 0
      let exact: number | null = null
      for (const p of pts) {
        const d = Math.hypot(p.e - e, p.s - s)
        if (d < 1e-6) {
          exact = p.v
          break
        }
        const w = 1 / d ** power
        num += w * p.v
        den += w
      }
      out[i] = exact ?? num / den
    }
  }
  return out
}

/** Class codes (addendum F5): 0 unclassified, 1 canopy, 2 water, 3 mud, 4 other. */
export const CLASS_WATER = 2

/**
 * A `size` x `size` mask from a class raster (`width` x `height` codes, row 0 north) by nearest
 * sampling at each cell centre: "water" keeps water, "land" keeps canopy, mud and other.
 * Unclassified pixels belong to neither.
 */
export function maskFromClasses(
  classes: Uint8Array,
  width: number,
  kind: 'water' | 'land',
  size = 64,
  height = width,
): Uint8Array {
  const mask = new Uint8Array(size * size)
  for (let row = 0; row < size; row++) {
    const y = Math.min(height - 1, Math.floor(((row + 0.5) / size) * height))
    for (let col = 0; col < size; col++) {
      const x = Math.min(width - 1, Math.floor(((col + 0.5) / size) * width))
      const c = classes[y * width + x] ?? 0
      const keep = kind === 'water' ? c === CLASS_WATER : c !== 0 && c !== CLASS_WATER
      mask[row * size + col] = keep ? 1 : 0
    }
  }
  return mask
}
