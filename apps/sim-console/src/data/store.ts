import { useSyncExternalStore } from 'react'
import type { Coverage, PublicConfig, Site } from '@bcs/api-types'
import { loadCoverage } from './gsClient'
import { createSimClient, type SimClient } from './simClient'
import type { InspectorPacket, SimNode, SimPosition, SimState, SimWsMessage, SimWsStatus } from './types'

/** Simulator /state poll (online/offline, nature, zone scenarios). Live node values come from /ws. */
export const STATE_POLL_MS = 3000
export const COVERAGE_POLL_MS = 5000
/** Sparkline window and sampling: 2 minutes at 1 Hz. */
export const HISTORY_WINDOW_MS = 120_000
export const HISTORY_STEP_MS = 1000
export const PACKET_BUFFER = 1000
/** WS messages are applied in batches, so 4 Hz node state plus packet bursts cost one render each. */
const FLUSH_MS = 100
const WS_RETRY_MS = 1500
const FALLBACK_SIM_URL = 'http://127.0.0.1:8701'

export type SimLink = 'connecting' | 'online' | 'offline'
export type Point = [number, number]

export interface PacketRow extends InspectorPacket {
  seq: number
}

export interface ConsoleState {
  config: PublicConfig | null
  client: SimClient | null
  sim: SimLink
  state: SimState | null
  status: SimWsStatus | null
  ws: boolean
  nodes: SimNode[]
  /** node -> parameter -> [t_ms, value][] over the last 2 minutes. */
  history: Record<string, Record<string, Point[]>>
  packets: PacketRow[]
  dropped: number
  coverage: Coverage | null
  site: Site | null
  /** A point picked on the mini-map (site metres), for install and move. */
  picked: SimPosition | null
  /** The gap suggestion picked on the mini-map. */
  suggestion: string | null
}

const initial: ConsoleState = {
  config: null,
  client: null,
  sim: 'connecting',
  state: null,
  status: null,
  ws: false,
  nodes: [],
  history: {},
  packets: [],
  dropped: 0,
  coverage: null,
  site: null,
  picked: null,
  suggestion: null,
}

type Listener = () => void
let current: ConsoleState = initial
const listeners = new Set<Listener>()

export function getState(): ConsoleState {
  return current
}

export function setState(patch: Partial<ConsoleState> | ((s: ConsoleState) => Partial<ConsoleState>)): void {
  const p = typeof patch === 'function' ? patch(current) : patch
  current = { ...current, ...p }
  listeners.forEach((l) => l())
}

function subscribe(l: Listener): () => void {
  listeners.add(l)
  return () => listeners.delete(l)
}

/** Select a slice; the selector must return stored references (no new objects). */
export function useConsole<T>(selector: (s: ConsoleState) => T): T {
  return useSyncExternalStore(subscribe, () => selector(current))
}

export function resetStore(): void {
  current = initial
  listeners.forEach((l) => l())
}

// ---- reducers --------------------------------------------------------------------------------------

/** Append a sample per parameter at most once per HISTORY_STEP_MS, keeping the last 2 minutes. */
export function appendHistory(
  history: ConsoleState['history'],
  nodes: SimNode[],
  now: number,
): ConsoleState['history'] {
  let changed = false
  const next: ConsoleState['history'] = { ...history }
  for (const n of nodes) {
    const prev = history[n.node_id] ?? {}
    const per: Record<string, Point[]> = { ...prev }
    let nodeChanged = false
    for (const [param, v] of Object.entries(n.readings)) {
      if (!Number.isFinite(v)) continue
      const pts = prev[param] ?? []
      const last = pts[pts.length - 1]
      if (last && now - last[0] < HISTORY_STEP_MS) continue
      const cut = now - HISTORY_WINDOW_MS
      let start = 0
      while (start < pts.length && pts[start][0] < cut) start++
      per[param] = [...pts.slice(start), [now, v]]
      nodeChanged = true
    }
    if (nodeChanged) {
      next[n.node_id] = per
      changed = true
    }
  }
  return changed ? next : history
}

/** Replace one node in the list (a REST answer), keeping the order. */
export function applyNode(node: SimNode): void {
  setState((s) => ({ nodes: s.nodes.map((n) => (n.node_id === node.node_id ? node : n)) }))
}

// ---- wiring ----------------------------------------------------------------------------------------

let packetSeq = 0

/** Start polling and the /ws stream for this config. Returns a stop function. */
export function connect(config: PublicConfig | null): () => void {
  const simUrl = (config?.sim_url || FALLBACK_SIM_URL).replace(/\/+$/, '')
  const client = createSimClient(simUrl)
  setState({ config, client, site: (config?.site as Site | undefined) ?? null })
  let stopped = false
  const timers: ReturnType<typeof setInterval>[] = []

  // /state poll: the simulator is "online" exactly when it answers.
  const poll = () =>
    client.state().then(
      (state) => {
        if (stopped) return
        setState((s) => ({
          sim: 'online',
          state,
          // Before /ws has delivered anything, /state seeds the cards.
          nodes: s.ws && s.nodes.length ? s.nodes : (state.nodes ?? []),
        }))
      },
      () => !stopped && setState({ sim: 'offline' }), // never crash: the shell just says offline
    )
  void poll()
  timers.push(setInterval(poll, STATE_POLL_MS))

  const pollCoverage = () =>
    loadCoverage().then(
      (coverage) => !stopped && setState({ coverage }),
      () => undefined, // keep the last coverage
    )
  void pollCoverage()
  timers.push(setInterval(pollCoverage, COVERAGE_POLL_MS))

  // /ws: buffered and flushed in batches.
  let pendingNodes: SimNode[] | null = null
  let pendingStatus: SimWsStatus | null = null
  let pendingPackets: PacketRow[] = []
  let pendingDropped = 0
  const flush = () => {
    if (!pendingNodes && !pendingStatus && !pendingPackets.length && !pendingDropped) return
    const nodes = pendingNodes
    const status = pendingStatus
    const packets = pendingPackets
    const dropped = pendingDropped
    pendingNodes = null
    pendingStatus = null
    pendingPackets = []
    pendingDropped = 0
    setState((s) => {
      const patch: Partial<ConsoleState> = {}
      if (nodes) {
        patch.nodes = nodes
        patch.history = appendHistory(s.history, nodes, Date.now())
      }
      if (status) patch.status = status
      if (packets.length) patch.packets = [...packets.reverse(), ...s.packets].slice(0, PACKET_BUFFER)
      if (dropped) patch.dropped = s.dropped + dropped
      return patch
    })
  }
  timers.push(setInterval(flush, FLUSH_MS))

  let socket: WebSocket | null = null
  let retry: ReturnType<typeof setTimeout> | undefined
  const open = () => {
    if (stopped) return
    const ws = new WebSocket(`${simUrl.replace(/^http/, 'ws')}/ws`)
    socket = ws
    ws.onopen = () => setState({ ws: true })
    ws.onmessage = (ev) => {
      let msg: SimWsMessage
      try {
        msg = JSON.parse(String(ev.data)) as SimWsMessage
      } catch {
        return
      }
      if (typeof msg.dropped === 'number') pendingDropped += msg.dropped
      if (msg.type === 'nodes.state') pendingNodes = msg.data
      else if (msg.type === 'sim.status') pendingStatus = msg.data
      else if (msg.type === 'inspector.packet') pendingPackets.push({ ...msg.data, seq: ++packetSeq })
    }
    ws.onclose = () => {
      if (socket === ws) socket = null
      setState({ ws: false })
      if (!stopped) retry = setTimeout(open, WS_RETRY_MS)
    }
  }
  open()

  return () => {
    stopped = true
    timers.forEach(clearInterval)
    if (retry) clearTimeout(retry)
    socket?.close()
  }
}

/** Re-read /state now (after an action), instead of waiting for the next poll. */
export function refreshState(): void {
  const { client } = current
  if (!client) return
  client.state().then(
    (state) => setState({ sim: 'online', state }),
    () => undefined,
  )
}

export function refreshCoverage(): void {
  loadCoverage().then(
    (coverage) => setState({ coverage }),
    () => undefined,
  )
}
