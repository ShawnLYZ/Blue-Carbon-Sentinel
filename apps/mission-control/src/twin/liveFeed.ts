// One shared /ws/live connection for every consumer (the 3D surface, the stage HUD, Task 12 panels).
// Ref-counted: the socket is open while anything holds it and the page is visible. The newest frame
// is kept after the camera goes offline or the socket closes, so the map freezes on the last real
// frame (nothing ever substitutes for it).
import { useSyncExternalStore } from 'react'
import type { LiveFrame } from './liveDecoder'
import { openLiveSocket } from './liveSocket'

export const LIVE_MAX_FPS = 10

export interface ReceivedFrame extends LiveFrame {
  /** performance.now() when the message was decoded (for frame-to-screen timing). */
  receivedAt: number
}

let latest: ReceivedFrame | null = null
const frameListeners = new Set<(f: ReceivedFrame) => void>()
const stateListeners = new Set<() => void>()
let holders = 0
let dispose: (() => void) | null = null
let visibilityBound = false
let suspended = false

function onFrame(f: LiveFrame): void {
  const prevMode = latest?.header.mode
  const hadFrame = latest !== null
  latest = { ...f, receivedAt: performance.now() }
  for (const l of frameListeners) l(latest)
  if (!hadFrame || prevMode !== latest.header.mode) for (const l of stateListeners) l()
}

function visible(): boolean {
  return typeof document === 'undefined' || document.visibilityState !== 'hidden'
}

function reconcile(): void {
  const want = holders > 0 && visible() && !suspended
  if (want && !dispose) dispose = openLiveSocket(onFrame, LIVE_MAX_FPS)
  else if (!want && dispose) {
    dispose()
    dispose = null
  }
}

/**
 * Pauses the shared live feed while the persistent map is hidden (Time Travel, design §21/§26): the
 * socket closes and reopens when resumed; the last frame is kept.
 */
export function setLiveFeedSuspended(on: boolean): void {
  if (suspended === on) return
  suspended = on
  reconcile()
}

/** Holds the live feed open; returns a release function. Paused while the tab or the map is hidden. */
export function acquireLiveFeed(): () => void {
  if (!visibilityBound && typeof document !== 'undefined') {
    visibilityBound = true
    document.addEventListener('visibilitychange', reconcile)
  }
  holders += 1
  reconcile()
  let released = false
  return () => {
    if (released) return
    released = true
    holders -= 1
    reconcile()
  }
}

/** Called for every new frame (outside React); returns an unsubscribe function. */
export function onLiveFrame(cb: (f: ReceivedFrame) => void): () => void {
  frameListeners.add(cb)
  return () => frameListeners.delete(cb)
}

export function latestLiveFrame(): ReceivedFrame | null {
  return latest
}

function subscribeState(cb: () => void): () => void {
  stateListeners.add(cb)
  return () => stateListeners.delete(cb)
}

/** True once any real frame has arrived (React re-renders only when this flips). */
export function useHasLiveFrame(): boolean {
  return useSyncExternalStore(subscribeState, () => latest !== null, () => false)
}

/** Depth mode of the newest frame, or null before the first frame. */
export function useLiveMode(): 'depth' | 'fallback' | null {
  return useSyncExternalStore(subscribeState, () => latest?.header.mode ?? null, () => null)
}
