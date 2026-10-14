// Linked cameras for Time Travel's two maps: moving one moves the other (US 148).

/** The part of a Mapbox map (or react-map-gl MapRef) the sync needs. */
export interface SyncableMap {
  on(type: 'move', fn: () => void): unknown
  off(type: 'move', fn: () => void): unknown
  getCenter(): { lng: number; lat: number }
  getZoom(): number
  getBearing(): number
  getPitch(): number
  jumpTo(o: { center: [number, number]; zoom: number; bearing: number; pitch: number }): unknown
}

/**
 * Mirrors each map's camera onto the other with `jumpTo` on `move`. Re-entrancy guarded: the `move`
 * the jump itself fires on the follower is not echoed back. Returns an unsubscribe function.
 */
export function syncCameras(a: SyncableMap, b: SyncableMap): () => void {
  let syncing = false
  const follow = (src: SyncableMap, dst: SyncableMap) => () => {
    if (syncing) return
    syncing = true
    try {
      const c = src.getCenter()
      dst.jumpTo({ center: [c.lng, c.lat], zoom: src.getZoom(), bearing: src.getBearing(), pitch: src.getPitch() })
    } finally {
      syncing = false
    }
  }
  const ab = follow(a, b)
  const ba = follow(b, a)
  a.on('move', ab)
  b.on('move', ba)
  return () => {
    a.off('move', ab)
    b.off('move', ba)
  }
}
