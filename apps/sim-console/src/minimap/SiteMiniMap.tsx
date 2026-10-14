import { useEffect, useRef, useState, type MouseEvent } from 'react'
import { loadLiveFrame } from '../data/gsClient'
import { setState, useConsole } from '../data/store'
import { COVERAGE_RADIUS_M, TYPE_SHORT } from '../data/params'
import type { SimNode } from '../data/types'
import { GRID, cellForLabel, labelForCell } from '../scenarios/zonePicker'

/** The Ground Station's live raster is polled about once per second (addendum I2). */
export const LIVE_POLL_MS = 1000
/** While the Ground Station has no frame (404), ask less often. */
export const NO_FRAME_POLL_MS = 5000

/**
 * The live site raster, or null. A 404 means the Ground Station has no frame: nothing is substituted.
 * A network error keeps the last real frame.
 */
function useLiveFrame(): string | null {
  const [url, setUrl] = useState<string | null>(null)
  const latest = useRef<string | null>(null)
  latest.current = url
  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const swap = (next: string | null) =>
      setUrl((prev) => {
        if (prev && prev !== next) URL.revokeObjectURL(prev)
        return next
      })
    const tick = async () => {
      let wait = LIVE_POLL_MS
      try {
        const blob = await loadLiveFrame()
        if (!stopped) swap(blob ? URL.createObjectURL(blob) : null)
        if (!blob) wait = NO_FRAME_POLL_MS
      } catch {
        // keep the last real frame; try again next tick
      }
      if (!stopped) timer = setTimeout(tick, wait)
    }
    void tick()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
      if (latest.current) URL.revokeObjectURL(latest.current)
    }
  }, [])
  return url
}

function Marker({ node }: { node: SimNode }) {
  const short = TYPE_SHORT[node.node_type] ?? '?'
  const { e_m: x, s_m: y } = node.position
  const cls = `marker marker--${short}${node.mode !== 'baseline' ? ' marker--hot' : ''}${node.connected ? '' : ' marker--off'}`
  const shape =
    short === 'SP' ? (
      <rect x={x - 7} y={y - 7} width={14} height={14} rx={2} />
    ) : short === 'TG' ? (
      <path d={`M ${x} ${y - 9} L ${x + 8.5} ${y + 6} L ${x - 8.5} ${y + 6} Z`} />
    ) : (
      <circle cx={x} cy={y} r={7.5} />
    )
  const anchor = x > 400 ? 'end' : x < 100 ? 'start' : 'middle'
  const tx = anchor === 'end' ? Math.min(x + 8, 496) : anchor === 'start' ? Math.max(x - 8, 4) : x
  const below = y < 440
  return (
    <g className={cls} data-testid={`marker-${node.node_id}`}>
      <title>{`${node.node_id} · SIMULATED · ${node.mode} · battery ${Math.round(node.battery_pct)}%`}</title>
      {shape}
      <text className="marker__id" x={tx} y={below ? y + 22 : y - 24} textAnchor={anchor}>
        {node.node_id}
      </text>
      <text className="marker__meta" x={tx} y={below ? y + 34 : y - 12} textAnchor={anchor}>
        SIMULATED · {node.mode} · {Math.round(node.battery_pct)}%
      </text>
    </g>
  )
}

/** Left column: live raster (or a dark grid square), zone grid, node markers, coverage rings and gaps. */
export function SiteMiniMap() {
  const frame = useLiveFrame()
  const nodes = useConsole((s) => s.nodes)
  const site = useConsole((s) => s.site)
  const coverage = useConsole((s) => s.coverage)
  const picked = useConsole((s) => s.picked)
  const suggestion = useConsole((s) => s.suggestion)
  const scenarios = useConsole((s) => s.state?.zone_scenarios)
  const size = site?.size_m ?? 500
  const cell = size / GRID

  const pick = (e: MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const e_m = Math.round(((e.clientX - r.left) / r.width) * size * 10) / 10
    const s_m = Math.round(((e.clientY - r.top) / r.height) * size * 10) / 10
    setState({ picked: { e_m, s_m }, suggestion: null })
  }

  return (
    <div className="minimap">
      <div className="minimap__square">
        {frame ? (
          <img className="minimap__frame" src={frame} alt="Live site raster from the Ground Station" draggable={false} />
        ) : (
          <div className="minimap__noframe">
            <span data-testid="minimap-no-frame">no camera frame</span>
          </div>
        )}
        <svg
          className="minimap__overlay"
          viewBox={`0 0 ${size} ${size}`}
          onClick={pick}
          role="img"
          aria-label="Site mini-map: click to pick a point for install or move"
        >
          {Object.keys(scenarios ?? {}).map((label) => {
            const c = cellForLabel(label)
            if (!c) return null
            return <rect key={label} className="minimap__scenario" x={c.col * cell} y={c.row * cell} width={cell} height={cell} />
          })}
          {Array.from({ length: GRID + 1 }, (_, i) => (
            <g key={i} className="minimap__grid">
              <line x1={i * cell} y1={0} x2={i * cell} y2={size} />
              <line x1={0} y1={i * cell} x2={size} y2={i * cell} />
            </g>
          ))}
          {Array.from({ length: GRID * GRID }, (_, i) => {
            const col = i % GRID
            const row = Math.floor(i / GRID)
            return (
              <text key={i} className="minimap__zone" x={col * cell + 6} y={row * cell + 16}>
                {labelForCell(col, row)}
              </text>
            )
          })}
          {nodes.map((n) => {
            const r = COVERAGE_RADIUS_M[n.node_type]
            return r ? (
              <circle key={`ring-${n.node_id}`} className={`ring ring--${TYPE_SHORT[n.node_type]}`}
                cx={n.position.e_m} cy={n.position.s_m} r={r} />
            ) : null
          })}
          {(coverage?.gaps ?? []).map((g) => (
            <g
              key={g.id}
              className={`gap${suggestion === g.id ? ' gap--picked' : ''}`}
              data-testid={`gap-${g.id}`}
              onClick={(e) => {
                e.stopPropagation()
                setState({ suggestion: g.id, picked: null })
              }}
            >
              <title>{`Install simulated node here (${g.node_type}, ${g.zone_id})`}</title>
              <circle className="gap__halo" cx={g.e_m} cy={g.s_m} r={14} />
              <path className="gap__plus" d={`M ${g.e_m - 8} ${g.s_m} H ${g.e_m + 8} M ${g.e_m} ${g.s_m - 8} V ${g.s_m + 8}`} />
              <text className="gap__label" x={g.e_m} y={g.s_m - 20} textAnchor="middle">
                Install simulated node here
              </text>
            </g>
          ))}
          {nodes.map((n) => (
            <Marker key={n.node_id} node={n} />
          ))}
          {picked && (
            <g className="picked">
              <circle cx={picked.e_m} cy={picked.s_m} r={9} />
              <path d={`M ${picked.e_m - 14} ${picked.s_m} H ${picked.e_m + 14} M ${picked.e_m} ${picked.s_m - 14} V ${picked.s_m + 14}`} />
            </g>
          )}
        </svg>
      </div>
      <div className="minimap__legend">
        <span><i className="lg lg--WQ" /> WQ · 150 m</span>
        <span><i className="lg lg--SP" /> SP · 100 m</span>
        <span><i className="lg lg--TG" /> TG · site-wide</span>
        <span className="minimap__pick bcs-mono">
          {picked ? `picked ${picked.e_m.toFixed(0)}, ${picked.s_m.toFixed(0)} m` : 'click to pick a point'}
        </span>
      </div>
    </div>
  )
}
