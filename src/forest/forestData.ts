// Main-thread access to the Forest Model worker: one build per session, overlays on request.

import { create } from 'zustand'
import type { ForestModel } from './model'
import type { Reading, SensorId } from '../sim/ranges'

interface ForestDataState {
  model: ForestModel | null
  error: string | null
}

export const useForestData = create<ForestDataState>(() => ({ model: null, error: null }))

let worker: Worker | null = null
let seq = 0
const waiting = new Map<number, (rgba: Uint8Array) => void>()

function getWorker(): Worker {
  if (worker) return worker
  worker = new Worker(new URL('./forest.worker.ts', import.meta.url), { type: 'module' })
  worker.onmessage = (e) => {
    const msg = e.data
    if (msg.type === 'built') useForestData.setState({ model: msg.model as ForestModel })
    if (msg.type === 'overlay') {
      const cb = waiting.get(msg.seq)
      waiting.delete(msg.seq)
      cb?.(msg.rgba as Uint8Array)
    }
  }
  worker.onerror = () => useForestData.setState({ error: 'The forest model could not be built.' })
  return worker
}

/** Starts building the Forest Model in the background. Safe to call many times. */
export function ensureForestModel() {
  if (useForestData.getState().model) return
  if (!worker) getWorker().postMessage({ type: 'build' })
}

/** Paints the layer from one Reading per sensor post (SENSOR_POSTS order). */
export function requestOverlay(layer: SensorId | 'natural', posts: Reading[]): Promise<Uint8Array> {
  const id = ++seq
  return new Promise((resolve) => {
    waiting.set(id, resolve)
    getWorker().postMessage({ type: 'overlay', seq: id, layer, posts })
  })
}
