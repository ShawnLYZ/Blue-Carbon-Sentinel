// Frame-to-screen statistics of the live surface (product spec: >= 5 fps, <= 500 ms). The reality
// surface records one sample per frame it uploads to the GPU; the System page reads them. The newest
// sample is also kept on window.__bcsLive for the browser console.

/** One frame-to-screen sample. */
export interface LiveTiming {
  seq: number
  /** ms from the message arriving to the frame being uploaded for the next map render. */
  receiveToUploadMs: number
  /** Server-side camera-to-processed latency from the frame header (`latency_ms`). */
  serverLatencyMs: number
  /** performance.now() at the upload. */
  uploadedAt: number
}

export interface LiveStats {
  serverLatencyMs: number
  receiveToUploadMs: number
  /** Server latency plus browser receive-to-upload (the socket hop on localhost is not measured). */
  frameToScreenMs: number
  /** Frames uploaded per second over the last FPS_WINDOW_MS. */
  fps: number
  /** ms since the newest sample. */
  ageMs: number
}

export const FPS_WINDOW_MS = 2000

/** Frames per second from upload times, counting those inside the window ending at `now`. */
export function fpsOver(times: readonly number[], now: number, windowMs = FPS_WINDOW_MS): number {
  let n = 0
  for (const t of times) if (t > now - windowMs && t <= now) n += 1
  return n / (windowMs / 1000)
}

export function summarise(last: LiveTiming, times: readonly number[], now: number): LiveStats {
  return {
    serverLatencyMs: last.serverLatencyMs,
    receiveToUploadMs: last.receiveToUploadMs,
    frameToScreenMs: last.serverLatencyMs + last.receiveToUploadMs,
    fps: fpsOver(times, now),
    ageMs: Math.max(0, now - last.uploadedAt),
  }
}

let last: LiveTiming | null = null
const uploads: number[] = []

export function recordLiveTiming(t: LiveTiming): void {
  last = t
  uploads.push(t.uploadedAt)
  while (uploads.length > 0 && uploads[0] <= t.uploadedAt - FPS_WINDOW_MS) uploads.shift()
  ;(globalThis as { __bcsLive?: LiveTiming }).__bcsLive = t
}

/** Current statistics, or null before the first frame reached the screen. */
export function liveStats(now: number = performance.now()): LiveStats | null {
  return last ? summarise(last, uploads, now) : null
}
