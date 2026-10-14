import { createContext, useContext } from 'react'
import type { SurfaceState } from './surfaceMaterial'

/** The twin's shared surface state, for map layers mounted as TwinScene children. */
export const SurfaceStateContext = createContext<SurfaceState | null>(null)

export function useSurfaceState(): SurfaceState {
  const st = useContext(SurfaceStateContext)
  if (!st) throw new Error('useSurfaceState must be used inside <TwinScene>')
  return st
}
