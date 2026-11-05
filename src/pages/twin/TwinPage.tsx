import { useEffect, useMemo, useRef, useState } from 'react'
import { create } from 'zustand'
import { Camera, MousePointer2, Pin, Radio } from 'lucide-react'
import { ForestScene } from '../../forest/ForestScene'
import type { ForestView } from '../../forest/view'
import { requestOverlay } from '../../forest/forestData'
import { stressGradientCss } from '../../forest/stressColor'
import { useApp } from '../../state/store'
import { healthyReading } from '../../sim/engine'
import { postReadings } from '../../sim/field'
import { SENSORS, SENSOR_BY_ID, bandOf, formatReading, levelOf, type Reading, type SensorId } from '../../sim/ranges'
import { toLatLng, formatLat, formatLng } from '../../geo/geo'
import { POST_RADIUS_M, REPLANT_PATCHES, SENSOR_POSTS, type PatchId, type SensorPost } from '../../site/catalogue'
import { BandIcon, StatusChip } from '../../ui/components'

type Layer = SensorId | 'natural'

/** The layer and pinned sensor post survive page changes. */
const useTwin = create<{ layer: Layer; pinned: string | null }>(() => ({ layer: 'natural', pinned: null }))

const RANGE_TEXT: Record<SensorId, [string, string, string]> = {
  dissolved_oxygen: ['5.0 or more', '2.0 to 5.0', 'below 2.0'],
  salinity: ['35 or less', '35 to 45', 'above 45'],
  turbidity: ['25 or less', '25 to 100', 'above 100'],
  ph: ['7.0 to 8.5', '6.5–7.0 or 8.5–9.0', 'below 6.5 or above 9.0'],
  wave_height: ['0.50 or less', '0.50 to 1.00', 'above 1.00'],
  wave_velocity: ['0.50 or less', '0.50 to 1.00', 'above 1.00'],
  temperature: ['20 to 32', '15–20 or 32–36', 'below 15 or above 36'],
  humidity: ['50 or more', '40 to 50', 'below 40'],
  soil_moisture: ['70 or more', '50 to 70', 'below 50'],
}

function Legend({ layer, anyPlanted }: { layer: Layer; anyPlanted: boolean }) {
  const level = useApp((s) => s.level)
  if (layer === 'natural') {
    return (
      <section className="legend float" aria-label="Legend">
        <h3>Natural colours</h3>
        <div className="legend-keys">
          <div className="legend-key"><span className="marker-station" style={{ width: 26, height: 26, borderWidth: 2 }}><Camera size={13} /></span> Sentinel Station, live with its camera</div>
          <div className="legend-key"><span className="tp-key"><Radio size={12} /></span> {SENSOR_POSTS.length - 1} more sensor posts across the forest</div>
          <div className="legend-key"><span className="key-dash" /> {anyPlanted ? 'Planted, grows next year' : 'Replant patches appear here once planted'}</div>
          <div className="legend-key"><span className="key-glow" /> {level === 'healthy' ? 'Red glow around any sensor whose readings turn dangerous' : 'Sensors with readings outside the healthy range'}</div>
        </div>
      </section>
    )
  }
  const spec = SENSOR_BY_ID[layer]
  const t = RANGE_TEXT[layer]
  return (
    <section className="legend float" aria-label="Legend">
      <h3>{spec.name} {spec.unit && <small>({spec.unit})</small>}</h3>
      <div className="ramp" style={{ background: stressGradientCss() }} />
      <div className="ramp-labels">
        <div><b style={{ color: 'var(--healthy-ink)' }}><BandIcon band="healthy" size={14} /> Healthy</b><span className="num">{t[0]}</span></div>
        <div><b style={{ color: 'var(--warning-ink)' }}><BandIcon band="warning" size={14} /> Warning</b><span className="num">{t[1]}</span></div>
        <div><b style={{ color: 'var(--danger-ink)' }}><BandIcon band="danger" size={14} /> Danger</b><span className="num">{t[2]}</span></div>
      </div>
      <div className="legend-keys">
        <div className="legend-key"><span className="tp-key"><Radio size={12} /></span> Each sensor colours the forest about {POST_RADIUS_M} m around it</div>
        <div className="legend-key"><span className="key-dash" /> {anyPlanted ? 'Planted, grows next year' : 'Replant patches appear here once planted'}</div>
      </div>
    </section>
  )
}

function PostCard({ post, values, pinned, layer }: { post: SensorPost; values: Reading; pinned: boolean; layer: Layer }) {
  const p = toLatLng(post.x, post.z)
  return (
    <>
      <div className="hc-head">
        <div>
          <div className="hc-name">{post.name}{post.live && <span className="hc-live">Live</span>}</div>
          <div className="hc-coords num"><span>{formatLat(p.lat)}</span><span>{formatLng(p.lng)}</span></div>
        </div>
        {pinned && <span className="hc-pin"><Pin size={12} /> Pinned</span>}
      </div>
      {SENSORS.map((s) => {
        const b = bandOf(s.id, values[s.id])
        return (
          <div className={`hc-row ${layer === s.id ? 'active' : ''}`} key={s.id}>
            <span>{s.name}</span>
            <span className="v num">{formatReading(s.id, values[s.id])}{s.unit && <small>{s.unit}</small>}</span>
            <StatusChip band={b} size="sm" />
          </div>
        )
      })}
      <div className="hc-foot">{pinned ? 'Press Esc or click the forest to release' : 'Click the sensor to pin this card'}</div>
    </>
  )
}

export function TwinPage() {
  const layer = useTwin((s) => s.layer)
  const pinned = useTwin((s) => s.pinned)
  const [view, setView] = useState<ForestView | null>(null)
  const [hover, setHover] = useState<string | null>(null)
  const [place, setPlace] = useState<Record<string, { left: boolean; v: 'up' | 'mid' | 'down' }>>({})
  const reading = useApp((s) => s.reading)
  const tickTime = useApp((s) => s.tickTime)
  const year = useApp((s) => s.year)
  const plantings = useApp((s) => s.plantings)
  const planted = Object.keys(plantings) as PatchId[]
  const plantedKey = planted.join(',')
  const hostRef = useRef<HTMLDivElement>(null)
  const postRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const patchRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const down = useRef<{ x: number; y: number } | null>(null)

  // Data exists only at the sensor posts: one Reading each, the station's being the live one.
  const posts = useMemo(() => postReadings(reading, healthyReading(tickTime)), [reading, tickTime])

  // Layer overlay: recomputed in the worker whenever the layer or the Readings change.
  useEffect(() => {
    if (!view) return
    let live = true
    requestOverlay(layer, posts).then((rgba) => {
      if (live) view.setOverlay(rgba, layer === 'natural' ? 1 : 0.86)
    })
    return () => { live = false }
  }, [view, layer, posts])

  useEffect(() => {
    view?.setPlantings(planted)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, plantedKey])

  // 3D anchors: sensor posts and planted patches.
  useEffect(() => {
    if (!view) return
    const els: HTMLElement[] = []
    for (const p of SENSOR_POSTS) {
      const el = postRefs.current[p.id]
      if (!el) continue
      view.addAnchor(el, p.x, view.groundHeight(p.x, p.z) + 5.4, p.z)
      els.push(el)
    }
    for (const p of REPLANT_PATCHES) {
      const el = patchRefs.current[p.id]
      if (el && planted.includes(p.id)) {
        view.addAnchor(el, p.centroid.x, view.groundHeight(p.centroid.x, p.centroid.z) + 1, p.centroid.z)
        els.push(el)
      }
    }
    return () => els.forEach((e) => view.removeAnchor(e))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, plantedKey])

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') useTwin.setState({ pinned: null }) }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [])

  /** Opens the card on the side of the sensor with more room, clear of the layer bar and the page bottom. */
  const measure = (id: string, el: HTMLElement) => {
    const host = hostRef.current?.getBoundingClientRect()
    const r = el.getBoundingClientRect()
    if (!host) return
    const cy = r.top + r.height / 2
    const v = cy - host.top < 340 ? 'down' : host.bottom - cy < 240 ? 'up' : 'mid'
    setPlace((f) => ({ ...f, [id]: { left: r.right + 400 > host.right, v } }))
  }

  return (
    <div className="twin" ref={hostRef}
      onPointerDown={(e) => { down.current = { x: e.clientX, y: e.clientY } }}
      onPointerUp={(e) => {
        // A click on the forest (not a drag) releases the pinned card.
        const d = down.current
        down.current = null
        if (d && Math.hypot(e.clientX - d.x, e.clientY - d.y) <= 5) useTwin.setState({ pinned: null })
      }}
    >
      <ForestScene mode="twin" onView={setView}>
        <div className="twin-top">
          <div className="layers float" role="group" aria-label="Colour layer">
            {(['natural', ...SENSORS.map((s) => s.id)] as Layer[]).map((id) => (
              <button
                key={id}
                className="layer"
                aria-pressed={layer === id}
                onClick={() => useTwin.setState({ layer: id })}
                onPointerDown={(e) => e.stopPropagation()}
                onPointerUp={(e) => e.stopPropagation()}
              >
                {id === 'natural' ? 'Natural' : SENSOR_BY_ID[id].name}
              </button>
            ))}
          </div>
        </div>
        <div className="twin-year float num">Year {year}</div>
        <div onPointerDown={(e) => e.stopPropagation()} onPointerUp={(e) => e.stopPropagation()}>
          <Legend layer={layer} anyPlanted={planted.length > 0} />
        </div>
        {!pinned && !hover && (
          <div className="twin-hint float"><MousePointer2 size={17} /> Point at a sensor to read it · Click to pin</div>
        )}

        {SENSOR_POSTS.map((p, k) => {
          const values = posts[k]
          const band = layer === 'natural' ? levelOf(values) : bandOf(layer, values[layer])
          const open = pinned === p.id || (hover === p.id && !pinned)
          return (
            <div key={p.id} className={`anchor post-anchor ${open ? 'post-card-anchor' : ''}`} ref={(el) => { postRefs.current[p.id] = el }}>
              <div className="anchor-inner" style={{ position: 'relative' }}>
                <button
                  className="twin-post"
                  aria-pressed={pinned === p.id}
                  aria-label={`${p.name}: ${band}`}
                  data-testid={`twin-post-${p.id}`}
                  onPointerEnter={(e) => { measure(p.id, e.currentTarget); setHover(p.id) }}
                  onPointerLeave={() => setHover((h) => (h === p.id ? null : h))}
                  onPointerDown={(e) => e.stopPropagation()}
                  onPointerUp={(e) => e.stopPropagation()}
                  onClick={(e) => { measure(p.id, e.currentTarget); useTwin.setState({ pinned: pinned === p.id ? null : p.id }) }}
                >
                  <span className={`tp-dot ${band}`}>{p.live ? <Camera size={12} strokeWidth={2.4} /> : <Radio size={12} strokeWidth={2.4} />}</span>
                  {layer === 'natural'
                    ? (p.live ? p.name : p.name.replace('Sensor post', 'Post'))
                    : <span className="num">{formatReading(layer, values[layer])}{SENSOR_BY_ID[layer].unit && <small> {SENSOR_BY_ID[layer].unit}</small>}</span>}
                </button>
                {open && (
                  <div
                    className={`hover-card float ${pinned === p.id ? 'pinned' : ''}`}
                    style={{
                      position: 'absolute',
                      left: place[p.id]?.left ? 'auto' : 'calc(100% + 12px)',
                      right: place[p.id]?.left ? 'calc(100% + 12px)' : 'auto',
                      top: place[p.id]?.v === 'down' ? -6 : place[p.id]?.v === 'up' ? 'auto' : '50%',
                      bottom: place[p.id]?.v === 'up' ? -6 : 'auto',
                      transform: !place[p.id] || place[p.id].v === 'mid' ? 'translateY(-50%)' : 'none',
                    }}
                    data-testid="hover-card"
                    onPointerDown={(e) => e.stopPropagation()}
                    onPointerUp={(e) => e.stopPropagation()}
                  >
                    <PostCard post={p} values={values} pinned={pinned === p.id} layer={layer} />
                  </div>
                )}
              </div>
            </div>
          )
        })}
        {REPLANT_PATCHES.map((p) => (
          <div key={p.id} className="anchor anchor-patch" ref={(el) => { patchRefs.current[p.id] = el }} style={{ display: planted.includes(p.id) ? undefined : 'none' }}>
            <div className="anchor-inner"><span className="anchor-label">Planted, grows next year</span></div>
          </div>
        ))}
      </ForestScene>
    </div>
  )
}
