import { useEffect, useRef, useState } from 'react'
import { Box, Navigation2, Satellite, Scan } from 'lucide-react'
import { FootprintMap } from '../../maps/FootprintMap'
import { ForestScene } from '../../forest/ForestScene'
import { takeHandover } from '../../app/handover'
import { navigate } from '../../app/router'
import { useApp } from '../../state/store'
import { SENSOR_POSTS } from '../../site/catalogue'
import { BAND_WORD } from '../../ui/components'
import { prefersReducedMotion } from '../../ui/hooks'
import type { ForestView } from '../../forest/view'

const LIVE_POST = SENSOR_POSTS.find((p) => p.live)!

export function SatellitePage() {
  const [handover] = useState(() => takeHandover())
  const year = useApp((s) => s.year)
  const level = useApp((s) => s.level)
  const [view, setView] = useState<ForestView | null>(null)
  const [touched, setTouched] = useState(false)
  const [diving, setDiving] = useState(false)
  const postRefs = useRef<Record<string, HTMLDivElement | null>>({})

  // Sensor posts float over the 3D forest, a little above each pole.
  useEffect(() => {
    if (!view) return
    const els: HTMLElement[] = []
    for (const p of SENSOR_POSTS) {
      const el = postRefs.current[p.id]
      if (!el) continue
      view.addAnchor(el, p.x, view.groundHeight(p.x, p.z) + 5.4, p.z)
      els.push(el)
    }
    return () => els.forEach((e) => view.removeAnchor(e))
  }, [view])

  // Only the Sentinel Station is live: clicking it dives down to the post, then opens Sentinel Network.
  const dive = () => {
    if (diving) return
    if (!view || prefersReducedMotion()) {
      navigate('network', 'slow-fade')
      return
    }
    setDiving(true)
    view.diveTo(LIVE_POST.x, LIVE_POST.z).then(() => navigate('network', 'dive'))
  }

  return (
    <div className="split">
      <section className="panel" aria-label="Real satellite image">
        <div className="panel-view satellite">
          <FootprintMap handover={handover} padding={28} />
          <div className="north" aria-label="North is up"><Navigation2 size={16} fill="currentColor" strokeWidth={0} />N</div>
        </div>
        <div className="panel-cap">
          <span><Satellite size={19} /> Real satellite image · Mapbox Satellite</span>
          <span className="muted num">500 × 500 m · north up</span>
        </div>
      </section>
      <section className="panel" aria-label="3D model of the same forest">
        <div className={`panel-view forest-dive ${diving ? 'diving posts-hidden' : ''}`} onPointerDown={() => setTouched(true)} onWheel={() => setTouched(true)}>
          <ForestScene mode="natural" onView={setView}>
            {year > 1 && <span className="pill growth-chip">Includes simulated growth since Year 1</span>}
            <button className="icon-btn view-reset" title="Back to the whole forest" aria-label="Back to the whole forest" onClick={() => view?.frameAll(true)}>
              <Scan size={19} />
            </button>
            <div className={`view-hint ${touched ? 'gone' : ''}`}>Drag to turn · Scroll to zoom · Click the Sentinel Station for live readings</div>

            {SENSOR_POSTS.map((p) => (
              <div key={p.id} className="anchor post-anchor" ref={(el) => { postRefs.current[p.id] = el }} style={p.live ? { zIndex: 5 } : undefined}>
                <div className="anchor-inner">
                  {p.live ? (
                    <button
                      className={`post-live ${level}`}
                      aria-label={`${p.name}: ${BAND_WORD[level]}. Open Sentinel Network`}
                      onClick={dive}
                      onPointerDown={(e) => e.stopPropagation()}
                      data-testid="post-live"
                    >
                      <span className="pin-dot" />
                      <span className="pin-label">{p.name}<small>Live · open readings</small></span>
                    </button>
                  ) : (
                    <span className="post-idle" title={p.name} />
                  )}
                </div>
              </div>
            ))}
          </ForestScene>
        </div>
        <div className="panel-cap">
          <span><Box size={19} /> 3D model of the same forest · Year {year}</span>
          <span className="muted">{SENSOR_POSTS.length} sensor posts</span>
        </div>
      </section>
    </div>
  )
}
