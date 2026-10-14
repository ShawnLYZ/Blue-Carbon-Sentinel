import { describe, expect, it } from 'vitest'
import { FPS_WINDOW_MS, fpsOver, liveStats, recordLiveTiming, summarise } from './liveStats'

describe('live stats', () => {
  it('counts uploads inside the window only', () => {
    const times = [0, 100, 1100, 1200, 1300, 2100]
    expect(fpsOver(times, 2100)).toBe(2) // 0 and 100 are outside (100, 2100]; four remain
    expect(fpsOver([], 1000)).toBe(0)
    expect(fpsOver([500], 500 + FPS_WINDOW_MS)).toBe(0)
  })

  it('adds server latency and browser time for frame-to-screen', () => {
    const s = summarise({ seq: 3, receiveToUploadMs: 40, serverLatencyMs: 180, uploadedAt: 1000 }, [1000], 1250)
    expect(s).toEqual({ serverLatencyMs: 180, receiveToUploadMs: 40, frameToScreenMs: 220, fps: 0.5, ageMs: 250 })
  })

  it('records samples, exposes the newest on window.__bcsLive and prunes old uploads', () => {
    for (let i = 0; i < 30; i++) recordLiveTiming({ seq: i, receiveToUploadMs: 10, serverLatencyMs: 100, uploadedAt: i * 100 })
    const s = liveStats(2900)
    expect(s?.fps).toBe(10)
    expect((globalThis as { __bcsLive?: { seq: number } }).__bcsLive?.seq).toBe(29)
  })
})
