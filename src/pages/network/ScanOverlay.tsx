import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Camera, Info, LoaderCircle, Sparkles, Sprout, X } from 'lucide-react'
import { create } from 'zustand'
import { useRoute } from '../../app/router'
import { FootprintMap } from '../../maps/FootprintMap'
import { nextPatch, useApp } from '../../state/store'
import { sensorsAt } from '../../sim/field'
import { healthyReading } from '../../sim/engine'
import { replantSuggestion } from '../../sim/insights'
import { sendNotice } from '../../state/notifications'
import { SENSORS, bandOf, formatReading } from '../../sim/ranges'
import { Lightbox, StatusChip } from '../../ui/components'
import { usePrefersReducedMotion } from '../../ui/hooks'
import type { PatchId, ReplantPatch } from '../../site/catalogue'

const SWEEP_MS = 4000
// After the sweep, the camera photographs the spot to show it is still bare mud.
const SHOT_MS = 2200
const EMPTY_PHOTO = {
  src: '/scan-photos/empty-area.jpg',
  alt: 'Sample photo of a bare mudflat at low tide with mangroves only at its edge, standing in for the camera in this demo',
  credit: 'Bernard DUPONT · CC BY-SA 2.0 · Wikimedia Commons (resized)',
}

// Opened from the top bar's "More" menu, shown by the network page.
export const useScanOverlay = create<{ open: boolean }>(() => ({ open: false }))
useRoute.subscribe((s) => { if (s.route !== 'network') useScanOverlay.setState({ open: false }) })

export function ScanOverlay({ onClose }: { onClose(): void }) {
  const reduced = usePrefersReducedMotion()
  const [target] = useState<ReplantPatch | null>(() => nextPatch(useApp.getState().plantings))
  const [phase, setPhase] = useState<'scanning' | 'found' | 'none'>('scanning')
  const [progress, setProgress] = useState(0)
  const [shot, setShot] = useState(false)
  const [zoom, setZoom] = useState(false)
  const [mapH, setMapH] = useState(600)
  const mapRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  const plantings = useApp((s) => s.plantings)
  const reading = useApp((s) => s.reading)
  const tickTime = useApp((s) => s.tickTime)

  useLayoutEffect(() => {
    if (mapRef.current) setMapH(mapRef.current.clientHeight)
  }, [])

  useEffect(() => {
    const t0 = performance.now()
    let raf = 0
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / SWEEP_MS)
      setProgress(p)
      if (p < 1) raf = requestAnimationFrame(tick)
      else {
        if (target) {
          useApp.getState().plantPatch(target.id)
          setPhase('found')
          timer = window.setTimeout(() => setShot(true), SHOT_MS)
        } else setPhase('none')
      }
    }
    let timer = 0
    raf = requestAnimationFrame(tick)
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape' && !document.querySelector('dialog[open]')) closeRef.current() }
    window.addEventListener('keydown', esc)
    return () => { cancelAnimationFrame(raf); clearTimeout(timer); window.removeEventListener('keydown', esc) }
  }, [target])

  const planted = (Object.keys(plantings) as PatchId[]).filter((id) => phase === 'found' || id !== target?.id)
  const values = target ? sensorsAt(target.centroid.x, target.centroid.z, reading, healthyReading(tickTime)) : null
  const area = target ? Math.round(target.areaM2 / 10) * 10 : 0

  return (
    <div className="scan-wrap" role="dialog" aria-modal="true" aria-label="Satellite scan">
      <div className="scan float">
        <div className="scan-head">
          <div>
            <h2>Satellite scan</h2>
            <p>Looking for an empty area where conditions are healthy</p>
          </div>
          {phase === 'none' ? (
            <button className="btn" onClick={onClose}><X size={18} /> Close</button>
          ) : (
            <button
              className={`btn btn-plant ${phase === 'found' ? 'btn-primary' : ''}`}
              disabled={!shot}
              title={shot ? undefined : phase === 'found' ? 'Available when the camera’s photo arrives' : 'Available when the scan is done'}
              onClick={() => { sendNotice('replanting'); onClose() }}
            >
              <Sprout size={18} /> Plant Lah!
            </button>
          )}
        </div>
        <div className="scan-map" ref={mapRef} style={{ ['--h' as string]: `${mapH}px`, ['--sweep' as string]: `${SWEEP_MS}ms` }}>
          <FootprintMap padding={18} interactive={false} showStation planted={planted} highlight={phase === 'found' ? target?.id ?? null : null} />
          {phase === 'scanning' && (reduced
            ? <div className="scan-fade" />
            : <><div className="scan-trail" /><div className="scan-line" /></>)}
        </div>
        <div className="scan-side">
          {phase === 'scanning' && (
            <div className="scan-progress" aria-live="polite">
              <span>Predicting Habitat Success, Powering Coastal Resilience! <b className="num">{Math.round(progress * 100)}%</b></span>
              <div className="bar"><i style={{ width: `${progress * 100}%` }} /></div>
            </div>
          )}
          {phase === 'none' && (
            <div className="none-left" role="status">
              <Info size={20} style={{ flex: 'none', marginTop: 2 }} />
              <span>No empty area suitable for replanting found right now.</span>
            </div>
          )}
          {phase === 'found' && (
            <div className="scan-photo">
              {shot ? (
                <button className="photo" onClick={() => setZoom(true)} aria-label="Open the empty area photo full size">
                  <img src={EMPTY_PHOTO.src} alt={EMPTY_PHOTO.alt} className="photo-new" />
                  <span className="badge badge-sample">Sample photo</span>
                  <span className="photo-time">Empty area · no mangrove planted yet</span>
                </button>
              ) : (
                <div className="photo">
                  <div className="photo-empty">
                    <div>
                      <Camera size={30} />
                      <span>Waiting for the camera’s photo…</span>
                    </div>
                  </div>
                </div>
              )}
              <div className="cam-line" aria-live="polite">
                {shot
                  ? <><Camera size={20} style={{ color: 'var(--healthy)' }} /><span>Camera photo shows bare mud with no seedlings, ready for new mangrove seeds.</span></>
                  : <><LoaderCircle size={20} style={{ animation: 'spin 0.9s linear infinite', color: 'var(--primary)' }} /><span>Asking the camera to photograph this spot…</span></>}
              </div>
            </div>
          )}
          {phase === 'found' && target && values && (
            <>
              <div className="result" role="status">
                <h3><Sprout size={20} /> Suitable for replanting</h3>
                <div className="result-big">
                  <div><strong className="num">{area.toLocaleString('en-MY')} m²</strong><span>Empty area</span></div>
                  <div><strong className="num">{area.toLocaleString('en-MY')}</strong><span>Seedlings that fit, about (1 m apart)</span></div>
                </div>
                <div className="ai-note">
                  <div className="ai-tag"><Sparkles size={15} /> AI Suggestion</div>
                  <p>{replantSuggestion(target, values)}</p>
                </div>
              </div>
              <div className="readings">
                <h3>Readings at this spot</h3>
                {SENSORS.map((s) => (
                  <div className="reading-row" key={s.id}>
                    <span>{s.name}</span>
                    <span className="v num">{formatReading(s.id, values[s.id])}{s.unit && <small>{s.unit}</small>}</span>
                    <StatusChip band={bandOf(s.id, values[s.id])} size="sm" />
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
      <Lightbox
        src={zoom ? EMPTY_PHOTO.src : null}
        alt={EMPTY_PHOTO.alt}
        caption="Sample photo · empty area, no mangrove planted yet"
        credit={EMPTY_PHOTO.credit}
        onClose={() => setZoom(false)}
      />
    </div>
  )
}
