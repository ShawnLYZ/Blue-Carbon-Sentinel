import { Component, Suspense, lazy, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { buildTrees, DEFAULT_ENV, type Environment } from './model'
import { KSL, type Raster } from './satellite'
import { useObservation, useObservationStore, refreshObservation, selectObservation, sceneDate as date } from './observation'
import './preview.css'

const ForestScene = lazy(() => import('./ForestScene'))
export class SceneBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? <p className="mp-empty">3D unavailable on this device. Satellite imagery and controls remain available.</p> : this.props.children }
}

function RasterView({ raster, mode }: { raster: Raster; mode: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const rgba = new Uint8ClampedArray(raster.rgb)
    if (mode === 'ndvi') for (let i = 0; i < raster.ndvi.length; i++) {
      const v = raster.ndvi[i]!
      rgba.set(raster.valid[i] ? [Math.round(185 - v * 140), Math.round(110 + v * 80), 60, 255] : [43, 53, 65, 255], i * 4)
    }
    ref.current?.getContext('2d')?.putImageData(new ImageData(rgba, raster.width, raster.height), 0, 0)
  }, [raster, mode])
  return <canvas ref={ref} width={raster.width} height={raster.height} aria-label={mode === 'ndvi' ? 'Cloud-masked vegetation index' : 'True-colour Sentinel-2 imagery'} />
}

export default function MangrovePreview() {
  const { region, scenes, sceneId, raster, env, error, busy, catalogueBusy, checked, selectionNote } = useObservation()
  const [lat, setLat] = useState(String(region.lat)), [lng, setLng] = useState(String(region.lng))
  const [mode, setMode] = useState('rgb')
  const [illustrative, setIllustrative] = useState(false)
  const scene = scenes.find(s => s.id === sceneId)
  const setEnv = (value: Environment | ((e: Environment) => Environment)) => useObservationStore.setState({ env: typeof value === 'function' ? value(env) : value })
  const setError = (error: string) => useObservationStore.setState({ error })
  const setRegion = (region: typeof KSL) => { void refreshObservation(region) }
  const trees = useMemo(() => buildTrees(illustrative ? null : raster, env), [raster, env, illustrative])
  const shownTrees = raster || illustrative ? trees : []
  const set = (key: keyof Environment, value: number) => setEnv(e => ({ ...e, [key]: value }))
  const useLocation = () => {
    const a = Number(lat), b = Number(lng)
    if (!lat.trim() || !lng.trim() || !Number.isFinite(a) || !Number.isFinite(b) || a < -80 || a > 84 || b < -180 || b > 180) { setError('Enter a valid latitude (−80 to 84) and longitude (−180 to 180).'); return }
    setRegion({ name: a === KSL.lat && b === KSL.lng ? KSL.name : 'Custom mangrove site', lat: a, lng: b, size: 500 })
    setIllustrative(false)
  }

  return <div className="mp">
    <div className="mp-content">
      <div className="mp-heading"><div><p className="mp-eyebrow">OPEN SATELLITE / ENVIRONMENT MODEL</p><h1 className="page__title">Satellite Intelligence</h1><p>Open imagery and 3D mangrove modelling · local feature preview</p></div><button onClick={() => void refreshObservation()} disabled={catalogueBusy}>↻ Check latest imagery</button></div>
      <div className="mp-location"><div><strong>{region.name}</strong><small>500 × 500 m study area · WGS84 coordinates</small></div><label>Latitude<input aria-label="Latitude" value={lat} onChange={e => setLat(e.target.value)} /></label><label>Longitude<input aria-label="Longitude" value={lng} onChange={e => setLng(e.target.value)} /></label><button onClick={useLocation}>Explore site ↗</button></div>
      <div className="mp-grid">
        <section className="mp-card bcs-panel"><div className="mp-card-head"><div><span className="mp-eyebrow">01 / OBSERVE</span><h2>Open satellite imagery</h2></div><span className="mp-pill">Sentinel-2 L2A</span></div>
          <div className="mp-tabs"><button aria-pressed={mode === 'rgb'} onClick={() => setMode('rgb')}>True colour</button><button aria-pressed={mode === 'ndvi'} onClick={() => setMode('ndvi')}>Vegetation · NDVI</button></div>
          <div className="mp-image">{raster && raster.clearPct < 10 && <div className="mp-obscured">Cloud-obscured observation · select an earlier date</div>}{raster ? <RasterView raster={raster} mode={mode} /> : <div className="mp-empty"><span>◎</span><strong>{catalogueBusy ? busy || 'Finding recent acquisitions…' : busy || 'No satellite image loaded'}</strong><p>{error || 'Reading open Earth Search imagery directly from cloud-optimised GeoTIFFs.'}</p></div>}<span className="mp-north">N ↑</span><span className="mp-scale">Study area: 500 m</span>{raster && <span className="mp-image-label">{mode === 'rgb' ? 'Observed true colour · 10 m pixels' : 'NDVI · clouds, water & shadows masked'}</span>}</div>
          <div className="mp-source"><label>Acquisition <select aria-label="Satellite acquisition" value={sceneId} disabled={catalogueBusy || !scenes.length} onChange={e => void selectObservation(e.target.value)}>{!scenes.length && <option>No scenes loaded</option>}{scenes.map(s => <option key={s.id} value={s.id}>{date(s)} · {s.properties['eo:cloud_cover'].toFixed(0)}% tile cloud</option>)}</select></label><p className="mp-selection" role="status">{selectionNote}</p><p>Latest available observations, not continuous video. Catalogue checked {checked || '—'} MYT. Auto-check every 15 minutes while visible.</p>{scene && <a href={`https://browser.dataspace.copernicus.eu/?zoom=15&lat=${region.lat}&lng=${region.lng}`} target="_blank" rel="noreferrer">Explore location in Copernicus Browser ↗</a>}</div>
        </section>
        <section className="mp-card bcs-panel"><div className="mp-card-head"><div><span className="mp-eyebrow">02 / MODEL</span><h2>Mangrove digital twin</h2></div><span className="mp-pill mp-amber">Procedural estimate</span></div>
          <div className="mp-tabs"><button aria-pressed={env.layout === 'forest'} onClick={() => setEnv(e => ({ ...e, layout: 'forest' }))}>Natural forest</button><button aria-pressed={env.layout === 'farm'} onClick={() => setEnv(e => ({ ...e, layout: 'farm' }))}>Restoration farm</button></div>
          <div className="mp-scene"><SceneBoundary><Suspense fallback={<p className="mp-empty">Loading 3D scene…</p>}><ForestScene trees={shownTrees} raster={illustrative ? null : raster} env={env} /></Suspense></SceneBoundary><span className="mp-image-label">Drag to orbit · scroll to zoom</span><span className="mp-scene-badge">{illustrative ? 'ILLUSTRATIVE SCENARIO' : raster ? 'SATELLITE-GUIDED FOOTPRINT' : 'AWAITING OBSERVATIONS'}</span></div>
          <div className="mp-model-note">{raster && raster.clearPct < 10 && !illustrative && <p className="mp-cloud-warning">Site obscured: choose an earlier acquisition or enable an illustrative footprint.</p>}<strong>{shownTrees.length.toLocaleString()} visual tree instances</strong><p>{illustrative ? 'Assumed footprint for exploring the controls.' : 'Placed only on clear land pixels with NDVI ≥ 0.35. Vegetation is not a mangrove species classification.'} Tree positions, height, age and planting rows are estimates, not surveyed observations.</p><label className="mp-checkbox"><input type="checkbox" checked={illustrative} onChange={e => setIllustrative(e.target.checked)} /> Explore an illustrative footprint instead</label></div>
        </section>
      </div>
      <section className="mp-bottom bcs-panel"><div className="mp-controls"><span className="mp-eyebrow">SCENARIO ASSUMPTIONS</span><h2>Environment settings</h2><p>Adjust these inputs to explore appearance. They are manually set assumptions, not satellite or sensor measurements.</p><div className="mp-sliders">{([{ key: 'salinity', label: 'Salinity', unit: 'PSU', min: 0, max: 60 }, { key: 'inundation', label: 'Inundation', unit: '% of time', min: 0, max: 100 }, { key: 'age', label: 'Stand age', unit: 'years', min: 1, max: 40 }, { key: 'spacing', label: 'Planting / sample spacing', unit: 'm', min: 5, max: 30 }] as const).map(c => <label key={c.key}><span>{c.label}<b>{env[c.key]} <small>{c.unit}</small></b></span><input type="range" aria-label={c.label} min={c.min} max={c.max} value={env[c.key]} onChange={e => set(c.key, Number(e.target.value))} /></label>)}</div><button onClick={() => setEnv(DEFAULT_ENV)}>Reset assumptions</button></div>
      <div className="mp-evidence"><span className="mp-eyebrow">OBSERVATION QUALITY</span><div className="mp-stats"><div><strong>{raster ? `${raster.clearPct.toFixed(0)}%` : '—'}</strong><span>usable clear land</span></div><div><strong>{raster?.meanNdvi?.toFixed(2) ?? '—'}</strong><span>mean land NDVI</span></div><div><strong>{raster ? `${raster.vegetationPct.toFixed(0)}%` : '—'}</strong><span>vegetated study area</span></div></div><p>Cloud masking uses Sentinel-2 scene classes. NDVI uses red and near-infrared reflectance with each asset’s scale and offset. Masked pixels generate no trees; choose another acquisition if the site is obscured.</p><p>10 m imagery cannot resolve individual trees, roots or tree heights. The 3D view uses repeatable illustrative growth rules; it is not a calibrated ecological forecast.</p><p className="mp-credit">Contains modified Copernicus Sentinel data · Earth Search / Element 84 · AWS Open Data</p></div></section>
      {error && <p className="mp-error" role="alert">{error}</p>}
      <footer>BLUE CARBON SENTINEL <span>Preview only · no commits or deployment</span><a href="https://github.com/Element84/earth-search" target="_blank" rel="noreferrer">Data source & documentation ↗</a></footer>
    </div>
  </div>
}
