import { useEffect, useRef, useState } from 'react'
import { SENSORS, bandOf, formatReading, listSensors, sensorsIn, type Band, type SensorId, type SensorSpec } from '../../sim/ranges'
import { TICK_MS } from '../../sim/engine'
import { useApp } from '../../state/store'
import { AnimatedNumber, BandIcon, BAND_WORD, Sparkline, StatusChip } from '../../ui/components'
import { FootprintMap } from '../../maps/FootprintMap'
import { CameraPanel } from './CameraPanel'
import { ScanOverlay, useScanOverlay } from './ScanOverlay'
import type { PatchId } from '../../site/catalogue'

const HEALTHY_RANGE: Record<string, [number | null, number | null]> = {
  dissolved_oxygen: [5, null], salinity: [null, 35], turbidity: [null, 25], ph: [7, 8.5],
  wave_height: [null, 0.5], wave_velocity: [null, 0.5],
  temperature: [20, 32], humidity: [50, null], soil_moisture: [70, null],
}

function bannerSentence(level: Band, warning: string[], danger: SensorId[]) {
  if (level === 'healthy') return 'All readings are in the healthy range. The mangroves are doing well.'
  if (level === 'warning') return `Some readings are outside the healthy range: ${warning.join(', ')}. Keep an eye on them.`
  return `${listSensors(danger)} ${danger.length > 1 ? 'are' : 'is'} in the danger range. The camera has been asked to photograph the trees.`
}

function Banner() {
  const level = useApp((s) => s.level)
  const reading = useApp((s) => s.reading)
  const warn = sensorsIn(reading, 'warning').concat(sensorsIn(reading, 'danger'))
  const danger = sensorsIn(reading, 'danger')
  const warnNames = warn.map((id) => SENSORS.find((s) => s.id === id)!.name.replace(/^(.)/, (c) => c.toLowerCase()).replace(/^pH/i, 'pH'))
  return (
    <section className={`banner ${level}`} role="status" aria-live="polite" data-testid="level-banner">
      <div className="banner-icon"><BandIcon band={level} size={32} /></div>
      <div className="banner-text">
        <div className="banner-word">{BAND_WORD[level]}</div>
        <p className="banner-sentence">{bannerSentence(level, warnNames, danger)}</p>
      </div>
      <div className="banner-live"><span className="live-dot" /> Live · every 2 s</div>
    </section>
  )
}

function SensorCard({ spec }: { spec: SensorSpec }) {
  const value = useApp((s) => s.reading[spec.id])
  const history = useApp((s) => s.history[spec.id])
  const band = bandOf(spec.id, value)
  const prev = useRef<Band>(band)
  const [flash, setFlash] = useState(false)
  useEffect(() => {
    if (band === 'danger' && prev.current !== 'danger') {
      setFlash(true)
      const t = setTimeout(() => setFlash(false), 1000)
      prev.current = band
      return () => clearTimeout(t)
    }
    prev.current = band
  }, [band])
  return (
    <article className={`sensor ${spec.group} ${band} ${flash ? 'just-danger' : ''}`} data-testid={`sensor-${spec.id}`}>
      <div className="sensor-top">
        <h3 className="sensor-name">{spec.name}</h3>
        <StatusChip band={band} size="sm" />
      </div>
      <p className="sensor-hint">{spec.hint}</p>
      <div className="sensor-foot">
      <div className="sensor-value">
        <strong className="num"><AnimatedNumber value={value} decimals={spec.decimals} /></strong>
        {spec.unit && <span>{spec.unit}</span>}
      </div>
      <Sparkline
        values={history}
        healthy={HEALTHY_RANGE[spec.id]}
        minSpan={spec.wobble * 3}
        band={band}
        stepSeconds={TICK_MS / 1000}
        label={spec.name}
        format={(v) => `${formatReading(spec.id, v)}${spec.unit ? ` ${spec.unit}` : ''}`}
      />
      </div>
    </article>
  )
}

function StationCard() {
  const level = useApp((s) => s.level)
  const plantings = useApp((s) => s.plantings)
  const planted = Object.keys(plantings) as PatchId[]
  return (
    <section className="card station-card" aria-label="Station map">
      <div className="card-head">
        <h2>Station</h2>
        <span className="cam-status">Beside the river, Kuala Selangor</span>
      </div>
      <div className="station-map">
        <FootprintMap padding={10} interactive={false} showStation stationDanger={level === 'danger'} planted={planted} />
      </div>
    </section>
  )
}

export function NetworkPage() {
  const scanning = useScanOverlay((s) => s.open)
  return (
    <div className="network">
      <Banner />
      <div className="sensors" aria-label="Sensor readings">
        {SENSORS.map((s) => <SensorCard key={s.id} spec={s} />)}
      </div>
      <div className="side">
        <CameraPanel />
        <StationCard />
      </div>
      {scanning && <ScanOverlay onClose={() => useScanOverlay.setState({ open: false })} />}
    </div>
  )
}
