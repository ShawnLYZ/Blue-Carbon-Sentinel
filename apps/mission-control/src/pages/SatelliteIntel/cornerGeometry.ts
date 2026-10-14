// Four-corner calibration helpers (addendum F4). The ordering must match the Ground Station's
// `normalise_corners` in services/ground-station/src/bcs_gs/site/calibration.py exactly.

export type Pt = [number, number]

/**
 * Clockwise on screen (y points down): sort by angle around the centroid, then start at the corner
 * with the smallest x + y (tie: smallest y).
 */
export function sortClockwise(points: readonly Pt[]): Pt[] {
  const n = points.length
  if (n === 0) return []
  const cx = points.reduce((s, p) => s + p[0], 0) / n
  const cy = points.reduce((s, p) => s + p[1], 0) / n
  const pts = points.map((p) => [p[0], p[1]] as Pt)
  pts.sort((a, b) => Math.atan2(a[1] - cy, a[0] - cx) - Math.atan2(b[1] - cy, b[0] - cx))
  let start = 0
  for (let i = 1; i < n; i++) {
    const a = pts[i]!
    const b = pts[start]!
    const sa = a[0] + a[1]
    const sb = b[0] + b[1]
    if (sa < sb || (sa === sb && a[1] < b[1])) start = i
  }
  return [...pts.slice(start), ...pts.slice(0, start)]
}

export interface Edge {
  /** The `north_edge` value to send when this edge is north. */
  index: number
  from: Pt
  to: Pt
}

/** Edge k runs from corner k to corner k+1 (F4). */
export function edgesOf(sorted: readonly Pt[]): Edge[] {
  return sorted.map((from, i) => ({ index: i, from, to: sorted[(i + 1) % sorted.length]! }))
}

/** A click on the displayed image, converted to native frame pixels. */
export function toImagePoint(
  click: { x: number; y: number },
  shown: { width: number; height: number },
  natural: { width: number; height: number },
): Pt {
  const sx = shown.width > 0 ? natural.width / shown.width : 1
  const sy = shown.height > 0 ? natural.height / shown.height : 1
  return [Math.round(click.x * sx), Math.round(click.y * sy)]
}
