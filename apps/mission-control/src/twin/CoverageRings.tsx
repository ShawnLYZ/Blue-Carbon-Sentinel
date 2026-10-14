// Coverage rings, drawn by the surface shader itself (uRingCentres / uRingRadii, at most MAX_RINGS):
// WQ 150 m and SP 100 m around each node, in the node's type colour (grey when offline). The TG covers
// the whole site and gets no ring. Nothing animates: the uniforms change only when the registry does.
import { useEffect } from 'react'
import { useThree } from '@react-three/fiber'
import { COVERAGE_RADIUS_M } from '../data/network'
import { usePins, type Pin } from './NodePins'
import { packRings, type Ring } from './surfaceMaterial'
import { useSurfaceState } from './surfaceContext'

export function ringsFromPins(pins: Pin[]): Ring[] {
  const out: Ring[] = []
  for (const p of pins) {
    const radius = COVERAGE_RADIUS_M[p.type]
    if (radius === undefined) continue
    out.push({ e: p.e, s: p.s, radius, colour: p.colour })
  }
  return out
}

export function CoverageRings() {
  const state = useSurfaceState()
  const pins = usePins()
  const invalidate = useThree((s) => s.invalidate)

  useEffect(() => {
    packRings(state.rings, ringsFromPins(pins))
    invalidate()
  }, [pins, state, invalidate])

  useEffect(
    () => () => {
      state.rings.count = 0
      invalidate()
    },
    [state, invalidate],
  )
  return null
}
