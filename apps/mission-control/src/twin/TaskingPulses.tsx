// Tasking pulses: an expanding, fading ring at every node an open task holds, one pulse per 1.5 s.
// The twin renders on demand, so the pulse drives repaints itself — only while a task is open, only
// while the tab is visible, and capped at PULSE_FRAME_MS (20 Hz) instead of every display frame. With
// no open task nothing here schedules a repaint.
import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { DoubleSide, MeshBasicMaterial, type Mesh } from 'three'
import { useAppStore } from '../data/store'
import { heldNodes, isOpenTask } from '../data/network'
import { usePins } from './NodePins'
import { siteToScene, surfaceHeightAt } from './surfaceMaterial'
import { useSurfaceState } from './surfaceContext'

export const PULSE_PERIOD_MS = 1500
export const PULSE_FRAME_MS = 50
/** Ring radius at the start and end of one pulse, metres. */
export const PULSE_START_M = 6
export const PULSE_END_M = 45

/** 0..1 through the current pulse. */
export function pulsePhase(tMs: number): number {
  const p = (tMs % PULSE_PERIOD_MS) / PULSE_PERIOD_MS
  return p < 0 ? p + 1 : p
}

export function pulseRadius(phase: number): number {
  return PULSE_START_M + (PULSE_END_M - PULSE_START_M) * phase
}

export function pulseOpacity(phase: number): number {
  return 0.9 * (1 - phase)
}

/** Sorted ids of the nodes open tasks hold, joined (stable across task updates that change nothing). */
export function pulsingSignature(tasks: Parameters<typeof heldNodes>[0][]): string {
  const ids = new Set<string>()
  for (const t of tasks) if (isOpenTask(t)) for (const id of heldNodes(t)) ids.add(id)
  return [...ids].sort().join(',')
}

/** Repaints the on-demand scene at most every PULSE_FRAME_MS while `on` and the tab is visible. */
export function usePulseDriver(on: boolean, invalidate: () => void): void {
  useEffect(() => {
    if (!on) return
    let timer: ReturnType<typeof setInterval> | undefined
    const sync = () => {
      const run = document.visibilityState !== 'hidden'
      if (run && timer === undefined) timer = setInterval(invalidate, PULSE_FRAME_MS)
      else if (!run && timer !== undefined) {
        clearInterval(timer)
        timer = undefined
      }
    }
    sync()
    document.addEventListener('visibilitychange', sync)
    return () => {
      document.removeEventListener('visibilitychange', sync)
      if (timer !== undefined) clearInterval(timer)
      invalidate() // one last frame without the rings
    }
  }, [on, invalidate])
}

function Pulse({ e, s, colour }: { e: number; s: number; colour: string }) {
  const state = useSurfaceState()
  const mesh = useRef<Mesh>(null)
  const material = useMemo(
    () => new MeshBasicMaterial({ color: colour, transparent: true, depthWrite: false, side: DoubleSide, toneMapped: false }),
    [colour],
  )
  useEffect(() => () => material.dispose(), [material])

  useFrame(() => {
    const m = mesh.current
    if (!m) return
    const phase = pulsePhase(performance.now())
    const r = pulseRadius(phase)
    m.scale.set(r, r, r)
    m.position.set(...siteToScene(e, s, surfaceHeightAt(state, e, s) + 0.6))
    material.opacity = pulseOpacity(phase)
  })

  return (
    <mesh ref={mesh} rotation-x={-Math.PI / 2} material={material} frustumCulled={false} renderOrder={3}>
      <ringGeometry args={[0.86, 1, 64]} />
    </mesh>
  )
}

export function TaskingPulses() {
  const pins = usePins()
  const sig = useAppStore((s) => pulsingSignature(s.tasks.items))
  const invalidate = useThree((s) => s.invalidate)
  const ids = useMemo(() => new Set(sig ? sig.split(',') : []), [sig])
  const pulsing = pins.filter((p) => ids.has(p.id))
  usePulseDriver(pulsing.length > 0, invalidate)
  return (
    <>
      {pulsing.map((p) => (
        <Pulse key={p.id} e={p.e} s={p.s} colour={p.colour} />
      ))}
    </>
  )
}
