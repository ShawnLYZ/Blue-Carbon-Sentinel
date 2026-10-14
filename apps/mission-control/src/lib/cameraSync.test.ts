import { expect, test } from 'vitest'
import { syncCameras, type SyncableMap } from './cameraSync'

interface Cam {
  center: [number, number]
  zoom: number
  bearing: number
  pitch: number
}

/** A map whose jumpTo fires `move` synchronously, like Mapbox. */
function fakeMap(cam: Cam) {
  const handlers = new Set<() => void>()
  let jumps = 0
  const m: SyncableMap & { cam: Cam; move: (c: Partial<Cam>) => void; jumps: () => number; listeners: () => number } = {
    cam,
    on: (type, fn) => {
      if (type === 'move') handlers.add(fn)
    },
    off: (type, fn) => {
      if (type === 'move') handlers.delete(fn)
    },
    getCenter: () => ({ lng: m.cam.center[0], lat: m.cam.center[1] }),
    getZoom: () => m.cam.zoom,
    getBearing: () => m.cam.bearing,
    getPitch: () => m.cam.pitch,
    jumpTo: (o) => {
      jumps += 1
      m.cam = { center: o.center, zoom: o.zoom, bearing: o.bearing, pitch: o.pitch }
      for (const h of [...handlers]) h()
    },
    move: (c) => {
      m.cam = { ...m.cam, ...c }
      for (const h of [...handlers]) h()
    },
    jumps: () => jumps,
    listeners: () => handlers.size,
  }
  return m
}

test('moving either map moves the other once, without echo', () => {
  const a = fakeMap({ center: [103, 5], zoom: 16, bearing: 0, pitch: 60 })
  const b = fakeMap({ center: [0, 0], zoom: 2, bearing: 0, pitch: 0 })
  const stop = syncCameras(a, b)
  a.move({ zoom: 17, bearing: 30 })
  expect(b.cam).toEqual({ center: [103, 5], zoom: 17, bearing: 30, pitch: 60 })
  expect(b.jumps()).toBe(1)
  expect(a.jumps()).toBe(0) // b's move during the jump is not echoed back
  b.move({ pitch: 45 })
  expect(a.cam.pitch).toBe(45)
  expect(a.jumps()).toBe(1)
  stop()
  expect(a.listeners()).toBe(0)
  expect(b.listeners()).toBe(0)
  a.move({ zoom: 10 })
  expect(b.cam.zoom).toBe(17)
})
