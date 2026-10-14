// The live reality surface: a 500 x 500 m, 256 x 256-vertex plane displaced by the live height map
// and coloured by the live site raster. Frames reach the GPU in useFrame from a ref; React never
// re-renders per frame. Until the first real frame arrives the surface is hidden (nothing is
// substituted), and after the camera goes offline the last frame stays.
import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import type { Mesh } from 'three'
import { acquireLiveFeed, latestLiveFrame, onLiveFrame, type ReceivedFrame } from './liveFeed'
import { recordLiveTiming } from './liveStats'
import {
  SITE_SIZE_M,
  SURFACE_POSITION,
  SURFACE_ROTATION_X,
  SURFACE_SEGMENTS,
  createSurfaceMaterial,
  normaliseHeights,
  surfaceVisible,
  type SurfaceState,
} from './surfaceMaterial'

export { RealitySurfaceTextureHook } from './RealitySurfaceHook'

interface Pending {
  seq: number
  heights: Uint16Array | null
  bitmap: ImageBitmap | null
  receivedAt: number
  serverLatencyMs: number
}

export function RealitySurface({ state }: { state: SurfaceState }) {
  const res = useMemo(() => createSurfaceMaterial(state.heights, state.rings), [state])
  const mesh = useRef<Mesh>(null)
  const pending = useRef<Pending | null>(null)
  const invalidate = useThree((s) => s.invalidate)

  useEffect(() => () => res.dispose(), [res])

  useEffect(() => {
    let alive = true
    let newestSeq = -1
    const take = (seq: number, f: ReceivedFrame, bitmap: ImageBitmap | null) => {
      // Latest frame wins: a slower decode of an older frame never replaces a newer one.
      if (!alive || seq <= newestSeq) {
        bitmap?.close()
        return
      }
      newestSeq = seq
      pending.current?.bitmap?.close()
      pending.current = { seq, heights: f.heights, bitmap, receivedAt: f.receivedAt, serverLatencyMs: f.header.latency_ms }
      invalidate() // one map repaint per frame; camera motion repaints on its own
    }
    let counter = 0
    const handle = (f: ReceivedFrame) => {
      const seq = ++counter
      if (!f.jpeg) return take(seq, f, null)
      createImageBitmap(f.jpeg, { imageOrientation: 'none', premultiplyAlpha: 'none', colorSpaceConversion: 'none' }).then(
        (bmp) => take(seq, f, bmp),
        () => take(seq, f, null),
      )
    }
    const last = latestLiveFrame()
    if (last) handle(last)
    const off = onLiveFrame(handle)
    const release = acquireLiveFeed()
    return () => {
      alive = false
      off()
      release()
      pending.current?.bitmap?.close()
      pending.current = null
    }
  }, [invalidate])

  // Close the bitmap the colour texture holds when the surface goes away.
  useEffect(
    () => () => {
      const img = res.colourTexture.image as ImageBitmap | null | undefined
      if (img && typeof img.close === 'function') img.close()
    },
    [res],
  )

  useFrame(() => {
    const u = res.material.uniforms
    u.uBase.value = state.base
    u.uExaggeration.value = state.exaggeration
    u.uMaxRelief.value = state.maxRelief
    u.uRingCount.value = state.rings.count
    u.uOverlayMode.value = state.overlay.texture ? state.overlay.mode : 0
    u.uOverlayTex.value = state.overlay.texture ?? res.emptyOverlay
    u.uOverlayOpacity.value = state.overlay.opacity
    u.uGrid.value = state.grid ? 1 : 0
    const p = pending.current
    pending.current = null
    if (p) upload(p)
    const hasColour = res.colourTexture.image != null
    u.uShowColour.value = state.reality && hasColour && state.hasHeights ? 1 : 0
    if (mesh.current) mesh.current.visible = surfaceVisible(state, hasColour)
  })

  function upload(p: Pending) {
    if (p.heights) {
      normaliseHeights(p.heights, state.heights)
      state.hasHeights = true
      res.heightTexture.needsUpdate = true
    }
    if (p.bitmap) {
      const old = res.colourTexture.image as ImageBitmap | null | undefined
      res.colourTexture.image = p.bitmap
      res.colourTexture.needsUpdate = true
      // The texture no longer references the old bitmap; the GPU copy is replaced in this render.
      if (old && old !== p.bitmap && typeof old.close === 'function') old.close()
    }
    const now = performance.now()
    recordLiveTiming({ seq: p.seq, receiveToUploadMs: now - p.receivedAt, serverLatencyMs: p.serverLatencyMs, uploadedAt: now })
  }

  return (
    <mesh ref={mesh} position={SURFACE_POSITION} rotation-x={SURFACE_ROTATION_X} visible={false} frustumCulled={false}>
      <planeGeometry args={[SITE_SIZE_M, SITE_SIZE_M, SURFACE_SEGMENTS, SURFACE_SEGMENTS]} />
      <primitive object={res.material} attach="material" />
    </mesh>
  )
}
