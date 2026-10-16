import { useEffect } from 'react'
import { create } from 'zustand'
import { KSL, loadRaster, searchScenes, type Raster, type Region, type Scene } from './satellite'
import { DEFAULT_ENV, type Environment } from './model'

export const sceneDate = (s: Scene) => new Date(s.properties.datetime).toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
interface Observation {
  region: Region; scenes: Scene[]; sceneId: string; raster: Raster | null; env: Environment
  error: string; busy: string; catalogueBusy: boolean; checked: string; selectionNote: string
}
export const useObservationStore = create<Observation>(() => ({ region: KSL, scenes: [], sceneId: '', raster: null, env: DEFAULT_ENV, error: '', busy: '', catalogueBusy: false, checked: '', selectionNote: '' }))
let controller: AbortController | null = null
let started = false
const cache = new Map<string, Raster>()
const set = useObservationStore.setState

export async function refreshObservation(region = useObservationStore.getState().region) {
  started = true
  controller?.abort()
  const request = new AbortController()
  controller = request
  const signal = request.signal
  cache.clear()
  set({ region, raster: null, sceneId: '', scenes: [], error: '', busy: 'Finding recent acquisitions…', catalogueBusy: true, selectionNote: 'Searching recent scenes for a clear view of this site…' })
  try {
    const items = await searchScenes(region, signal)
    if (signal.aborted) return
    set({ scenes: items })
    if (!items.length) throw new Error('No supported Sentinel-2 scenes found here. Try another location.')
    const preferred = items.filter(s => s.properties['eo:cloud_cover'] <= 35)
    const candidates = [...preferred, ...items.filter(s => !preferred.includes(s))].slice(0, 8)
    let chosen: Scene | null = null, bestRaster: Raster | null = null
    for (const candidate of candidates) {
      if (signal.aborted) return
      set({ busy: `Checking site visibility: ${sceneDate(candidate)}…` })
      try {
        const raster = await loadRaster(candidate, region, AbortSignal.any([signal, AbortSignal.timeout(30000)]))
        if (signal.aborted) return
        cache.set(candidate.id, raster)
        if (!bestRaster || raster.clearPct > bestRaster.clearPct) { chosen = candidate; bestRaster = raster }
        if (raster.clearPct >= 35) break
      } catch (error) { if (signal.aborted) return; console.warn('Satellite scene unavailable', candidate.id, error) }
    }
    if (!chosen || !bestRaster) throw new Error('Satellite pixels could not load. Check your connection and retry.')
    set({ sceneId: chosen.id, raster: bestRaster, selectionNote: chosen.id === items[0]?.id ? 'Showing the newest acquisition.' : 'Showing a recent observation selected for site visibility. Newer acquisitions remain available.', checked: new Date().toLocaleTimeString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour: '2-digit', minute: '2-digit' }) })
  } catch (error) { if (!signal.aborted) set({ error: String(error) }) }
  finally { if (!signal.aborted) set({ busy: '', catalogueBusy: false }) }
}

export async function selectObservation(sceneId: string) {
  const state = useObservationStore.getState()
  const scene = state.scenes.find(s => s.id === sceneId)
  if (!scene) return
  controller?.abort()
  const request = new AbortController(); controller = request
  set({ sceneId, raster: null, busy: 'Reading satellite pixels…', catalogueBusy: false, error: '', selectionNote: 'Showing your selected acquisition.' })
  try {
    const raster = cache.get(sceneId) ?? await loadRaster(scene, state.region, AbortSignal.any([request.signal, AbortSignal.timeout(30000)]))
    if (request.signal.aborted) return
    cache.set(sceneId, raster); set({ raster })
  } catch (error) { if (!request.signal.aborted) set({ error: String(error) }) }
  finally { if (!request.signal.aborted) set({ busy: '' }) }
}

export function useObservation() {
  const state = useObservationStore()
  useEffect(() => {
    if (!started) void refreshObservation()
    const timer = setInterval(() => { if (document.visibilityState === 'visible') void refreshObservation() }, 15 * 60 * 1000)
    return () => clearInterval(timer)
  }, [])
  return state
}
