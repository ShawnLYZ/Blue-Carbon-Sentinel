import { useCallback, useState } from 'react'
import { Camera, HeartPulse, Navigation, Trees, X } from 'lucide-react'
import { GlobeMap } from '../../maps/GlobeMap'
import { MapMarker } from '../../maps/mapbox'
import { COMING_SOON_SITES, LIVE_SITE, MALAYSIA_VIEW } from '../../site/catalogue'
import { cameraOnline, lastHeard, useApp } from '../../state/store'
import { useForestData } from '../../forest/forestData'
import { BandIcon, BAND_WORD, StatusChip } from '../../ui/components'
import { formatArea, timeAgo } from '../../ui/time'
import { navigate } from '../../app/router'
import { setHandover } from '../../app/handover'
import { prefersReducedMotion } from '../../ui/hooks'

const FLY_MS = 3000
const PADDING: mapboxgl.PaddingOptions = { top: 150, left: 420, right: 20, bottom: 20 }

function useMangroveArea() {
  const model = useForestData((s) => s.model)
  return model ? formatArea(model.areaM2) : null
}

export function CommandPage() {
  const [map, setMap] = useState<mapboxgl.Map | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [flying, setFlying] = useState(false)
  const level = useApp((s) => s.level)
  const online = useApp(cameraOnline)
  const heard = useApp(lastHeard)
  const now = useApp((s) => s.now)
  const area = useMangroveArea()

  const onReady = useCallback((m: mapboxgl.Map | null) => setMap(m), [])

  const fly = useCallback(() => {
    setSelected(null)
    if (!map || prefersReducedMotion()) {
      navigate('satellite', 'slow-fade')
      return
    }
    setFlying(true)
    map.flyTo({
      center: [LIVE_SITE.centre.lng, LIVE_SITE.centre.lat], zoom: 16.25, bearing: 0, pitch: 0,
      padding: { top: 0, left: 0, right: 0, bottom: 0 }, duration: FLY_MS, curve: 1.5, essential: true,
    })
    map.once('moveend', () => {
      // Hold the last frame so the satellite panel can start exactly where the flight ended.
      map.once('render', () => {
        try {
          const canvas = map.getCanvas()
          const c = map.getCenter()
          setHandover({
            image: canvas.toDataURL('image/jpeg', 0.9),
            center: [c.lng, c.lat],
            zoom: map.getZoom(),
            width: canvas.clientWidth,
            height: canvas.clientHeight,
          })
        } catch {
          setHandover(null)
        }
        navigate('satellite', 'handover')
      })
      map.triggerRepaint()
    })
  }, [map])

  const selectedSoon = COMING_SOON_SITES.find((s) => s.id === selected) ?? null
  const flyLabel = 'Fly to Kuala Selangor'

  return (
    <div className="command">
      <GlobeMap onReady={onReady} padding={PADDING}>
        {map && (
          <>
            {COMING_SOON_SITES.map((s) => (
              <MapMarker key={s.id} map={map} lngLat={[s.centre.lng, s.centre.lat]} zIndex={1}>
                <button
                  className="pin pin-soon"
                  aria-label={`${s.name}, ${s.region}: Coming Soon`}
                  onClick={() => setSelected(selected === s.id ? null : s.id)}
                >
                  <span className="pin-dot" />
                </button>
              </MapMarker>
            ))}
            <MapMarker map={map} lngLat={[LIVE_SITE.centre.lng, LIVE_SITE.centre.lat]} zIndex={2}>
              <button
                className={`pin pin-live ${level} ${level === 'danger' ? 'pin-pulse' : ''}`}
                aria-label={`${LIVE_SITE.name}: ${BAND_WORD[level]}`}
                onClick={() => setSelected(selected === 'ksl' ? null : 'ksl')}
              >
                <span className="pin-dot" />
                {!flying && <span className="pin-label">{LIVE_SITE.shortName}</span>}
              </button>
            </MapMarker>
            {selected === 'ksl' && !flying && (
              <MapMarker map={map} lngLat={[LIVE_SITE.centre.lng, LIVE_SITE.centre.lat]} anchor="bottom" offset={[0, -24]} zIndex={5}>
                <div className="popup float" role="dialog" aria-label={LIVE_SITE.name} data-testid="site-popup">
                  <button className="icon-btn x" aria-label="Close" onClick={() => setSelected(null)}><X size={18} /></button>
                  <div>
                    <div className="site-name">{LIVE_SITE.name}</div>
                    <div className="site-region">{LIVE_SITE.region}, Malaysia</div>
                  </div>
                  <div className="popup-facts">
                    <StatusChip band={level} />
                    <span>Mangrove area <strong className="num">{area ?? '—'}</strong></span>
                  </div>
                  <button className="btn btn-primary btn-block" onClick={fly} data-testid="popup-fly">
                    <Navigation size={18} /> {flyLabel}
                  </button>
                </div>
              </MapMarker>
            )}
            {selectedSoon && (
              <MapMarker map={map} lngLat={[selectedSoon.centre.lng, selectedSoon.centre.lat]} anchor="bottom" offset={[0, -16]} zIndex={5}>
                <div className="popup float" role="dialog" aria-label={selectedSoon.name} data-testid="site-popup">
                  <button className="icon-btn x" aria-label="Close" onClick={() => setSelected(null)}><X size={18} /></button>
                  <div>
                    <div className="site-name" style={{ paddingRight: 28 }}>{selectedSoon.name}</div>
                    <div className="site-region">{selectedSoon.region}, Malaysia</div>
                  </div>
                  <span className="soon" style={{ alignSelf: 'flex-start' }}>Coming Soon</span>
                </div>
              </MapMarker>
            )}
          </>
        )}
      </GlobeMap>

      <div className={`command-ui ${flying ? 'is-flying' : ''}`}>
        <div className="tiles">
          <section className="tile float" data-testid="tile-mangrove-area" aria-label="Mangrove area">
            <div className="tile-label"><Trees size={18} /> Mangrove area</div>
            <div className="tile-value num">
              {area ? <>{area.replace(' ha', '')}<small>ha</small></> : '—'}
            </div>
            <div className="tile-sub">Kuala Selangor, Year 1</div>
          </section>
          <section className="tile float" data-testid="tile-forest-health" aria-label="Forest health">
            <div className="tile-label"><HeartPulse size={18} /> Forest health</div>
            <div className={`tile-health ${level}`}><BandIcon band={level} size={30} />{BAND_WORD[level]}</div>
            <div className="tile-sub">From all nine sensors</div>
          </section>
          <section className="tile float" data-testid="tile-camera" aria-label="Camera">
            <div className="tile-label"><Camera size={18} /> Camera</div>
            <div className="tile-health" style={{ color: online ? 'var(--text)' : 'var(--muted)' }}>
              <span className={`dot ${online ? 'dot-on' : ''}`} style={{ width: 14, height: 14 }} />
              {online ? 'Online' : 'Offline'}
            </div>
            <div className="tile-sub num">Last heard {timeAgo(heard, now)}</div>
          </section>
        </div>

        <aside className="sites float" data-testid="sites-list" aria-label="Sites">
          <div className="sites-head">
            <h2>Sites</h2>
            <span>1 live · {COMING_SOON_SITES.length} coming soon</span>
          </div>
          <ul className="sites-list">
            <li className="site-live" data-testid="site-card-ksl">
              <div className="site-live-top">
                <div>
                  <div className="site-name">{LIVE_SITE.name}</div>
                  <div className="site-region">{LIVE_SITE.region}</div>
                </div>
                <StatusChip band={level} size="sm" />
              </div>
              <dl className="site-facts">
                <div><dt>Mangrove area</dt><dd className="num">{area ?? '—'}</dd></div>
                <div><dt>Monitored square</dt><dd className="num">500 × 500 m</dd></div>
              </dl>
              <button className="btn btn-primary btn-lg btn-block" onClick={fly} data-testid="fly-ksl">
                <Navigation size={19} /> {flyLabel}
              </button>
            </li>
            {COMING_SOON_SITES.map((s) => (
              <li key={s.id}>
                <button
                  className="site-soon"
                  data-testid={`site-card-${s.id}`}
                  aria-pressed={selected === s.id}
                  onClick={() => {
                    setSelected(selected === s.id ? null : s.id)
                    if (map && selected !== s.id) map.easeTo({ center: MALAYSIA_VIEW.center, zoom: MALAYSIA_VIEW.zoom, duration: 600 })
                  }}
                >
                  <span>
                    <span className="site-name" style={{ display: 'block' }}>{s.name}</span>
                    <span className="site-region">{s.region}</span>
                  </span>
                  <span className="soon">Coming Soon</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  )
}
