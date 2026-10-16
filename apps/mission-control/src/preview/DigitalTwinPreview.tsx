import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { Panel, Toggle } from '@bcs/ui'
import { SceneBoundary } from './MangrovePreview'
import { buildTrees } from './model'
import { refreshObservation, sceneDate, selectObservation, useObservation } from './observation'
import { ATTRIBUTE_META, ATTRIBUTES, BASE_INPUTS, INPUT_KEYS, RISK_PALETTE, zoneRisks, type Attribute, type Inputs } from './scenarioRisk'
import { ExtraLayers, EXTRA_DEFAULTS, type ExtraLayerFlags } from './ExtraLayers'
import { useLayerData } from './layerData'
import { paintSurface, type SurfacePaint } from './surfacePaint'
import { createSurfaceState } from '../twin/surfaceMaterial'
import { useHasLiveFrame } from '../twin/liveFeed'
import { WellnessCard } from './WellnessCard'
import './preview.css'
import './digitalTwin.css'

const ForestScene = lazy(() => import('./ForestScene'))
export default function DigitalTwinPreview() {
  const { raster, env, region, scenes, sceneId, busy, catalogueBusy, error } = useObservation()
  const [base, setBase] = useState<Inputs>(BASE_INPUTS)
  const [overrides, setOverrides] = useState<Record<string, Inputs>>({})
  const [active, setActive] = useState<Attribute[]>([...ATTRIBUTES])
  const [selected, setSelected] = useState<string | null>('C3')
  const [hoveredZone, setHoveredZone] = useState<string | null>(null)
  const [floor, setFloor] = useState<Attribute | 'combined'>('combined')
  const [layers, setLayers] = useState({ trees: true, satellite: true, risk: true, grid: true, water: false })
  const [extra, setExtra] = useState(EXTRA_DEFAULTS)
  const [examples, setExamples] = useState(false)
  const [paint, setPaint] = useState<SurfacePaint>('none')
  const [liveFields, setLiveFields] = useState(false)
  const [exaggeration, setExaggeration] = useState(1)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const { data, matches, captures, connection, nodes } = useLayerData(region, examples)
  const hasLiveFrame = useHasLiveFrame()
  const realityState = useMemo(createSurfaceState, [])
  const [opacity, setOpacity] = useState(0.7)
  useEffect(() => { setOverrides({}); setSelected('C3'); setHoveredZone(null) }, [region.lat, region.lng])
  const zones = useMemo(() => zoneRisks(raster, base, overrides, active, floor), [raster, base, overrides, active, floor])
  const floorRaster = useMemo(() => paintSurface(raster, zones, paint, captures, nodes, liveFields), [raster, zones, paint, captures, nodes, liveFields])
  const zone = zones.find(z => z.id === selected)
  const current = selected ? overrides[selected] ?? base : base
  const scene = scenes.find(s => s.id === sceneId)
  const trees = useMemo(() => {
    if (!raster) return []
    return buildTrees(raster, { ...env, salinity: base.salinity }).map(t => {
      const col = Math.max(0, Math.min(4, Math.floor((t.x + 250) / 100)))
      const row = Math.max(0, Math.min(4, Math.floor((t.z + 250) / 100)))
      const stress = Math.max(0, ...Object.values(zones[row * 5 + col]!.stress))
      return { ...t, height: t.height * (1 - 0.4 * stress), crown: t.crown * (1 - 0.3 * stress), stress }
    })
  }, [raster, env, base.salinity, zones])
  const counts = zones.reduce((out, z) => ({ ...out, [z.risk]: (out[z.risk] ?? 0) + 1 }), {} as Record<string, number>)
  const editInput = (key: keyof Inputs, value: number) => {
    if (selected) setOverrides(o => ({ ...o, [selected]: { ...(o[selected] ?? base), [key]: value } }))
    else { setBase(b => ({ ...b, [key]: value })); setOverrides(o => Object.fromEntries(Object.entries(o).map(([id, values]) => [id, { ...values, [key]: value }]))) }
  }
  const toggleAttribute = (key: Attribute, on: boolean) => {
    setActive(a => on ? [...a.filter(k => k !== key), key] : a.filter(k => k !== key))
    if (!on && floor === key) setFloor('combined')
  }
  const reset = () => { setBase(BASE_INPUTS); setOverrides({}); setActive([...ATTRIBUTES]); setFloor('combined') }

  return <div className="mp dt">
    <div className="dt-heading"><h1 className="page__title">Digital Twin</h1><span className="mp-pill">Satellite-guided 3D · scenario risk</span><button onClick={() => void refreshObservation()} disabled={catalogueBusy || !!busy}>↻ Refresh imagery</button></div>
    <div className="dt-layout">
      <aside className="dt-left">
        <Panel title="Layers">
          <div className="dt-toggles">{(['trees', 'satellite', 'risk', 'grid', 'water'] as const).map(k => <Toggle key={k} label={{ trees: '3D mangroves', satellite: 'Satellite floor', risk: 'Continuous risk field', grid: 'Risk contours', water: 'Water plane' }[k]} checked={layers[k]} onChange={on => setLayers(l => ({ ...l, [k]: on }))} />)}</div>
          <div className="dt-toggles dt-extra-controls">{([
            ['reality', 'Reality surface (live camera)'], ['riskColumns', 'Risk columns'], ['carbon', 'Carbon columns'], ['nodes', 'Sensor nodes'], ['coverage', 'Coverage rings'], ['tasking', 'Tasking pulses'], ['alerts', 'Alert markers'],
          ] as [keyof ExtraLayerFlags, string][]).map(([key, label]) => <Toggle key={key} label={label} checked={extra[key] && (key !== 'riskColumns' || layers.risk)} disabled={key === 'reality' ? !matches : key === 'riskColumns' && !layers.risk} onChange={on => setExtra(e => ({ ...e, [key]: on }))} />)}</div>
          <p className="hint">Camera: {matches ? hasLiveFrame ? 'frame available' : 'waiting for a live frame' : 'Ground Station site not connected / aligned'}. Carbon and network layers use {examples ? 'EXAMPLE data' : 'Ground Station data'}.</p>
          <label className="dt-range">Vertical exaggeration <b>{exaggeration}×</b><input aria-label="Reality surface exaggeration" type="range" min="1" max="5" step="0.25" value={exaggeration} onChange={e => setExaggeration(Number(e.target.value))} /></label>
          <label className="dt-range">Risk colour opacity <b>{Math.round(opacity * 100)}%</b><input aria-label="Risk colour opacity" type="range" min="0.1" max="1" step="0.05" value={opacity} onChange={e => setOpacity(Number(e.target.value))} /></label>
        </Panel>
        <Panel title="Surface overlays">
          <p className="hint">One overlay at a time. Selecting one clears the risk tint so its values are visible.</p>
          <div className="dt-toggles">{([['ndvi', 'NDVI (satellite)'], ['classes', 'Land-cover classes'], ['cameraNdvi', 'NDVI-proxy (camera)'], ['cameraClasses', 'Land-cover classes (camera)']] as [SurfacePaint, string][]).map(([key, label]) => <Toggle key={key} label={label} checked={paint === key} disabled={key.startsWith('camera') && (!matches || !captures)} onChange={on => { setPaint(on ? key : 'none'); setLayers(l => ({ ...l, risk: !on })) }} />)}</div>
          <label className="dt-select">Water / soil field<select aria-label="Surface field overlay" value={INPUT_KEYS.includes(paint as keyof Inputs) ? paint : 'none'} onChange={e => { const value = e.target.value as SurfacePaint; setPaint(value); setLayers(l => ({ ...l, risk: value === 'none' })) }}><option value="none">No field overlay</option>{INPUT_KEYS.map(k => <option value={k} key={k}>{ATTRIBUTE_META[k].label} ({ATTRIBUTE_META[k].unit})</option>)}</select></label>
          <label className="dt-select">Field data source<select aria-label="Field data source" value={liveFields ? 'live' : 'scenario'} onChange={e => setLiveFields(e.target.value === 'live')}><option value="scenario">Scenario inputs</option><option value="live">Live sensor interpolation (IDW)</option></select></label>
          <p className="hint">{liveFields ? `${nodes.filter(n => n.status === 'online').length} online nodes; fields are clipped to water or land. Grey means no matching reading.` : 'Field colours use your adjustable scenario values.'}</p>
          <p className="hint">Camera overlays need Ground Station capture maps and are unavailable until connected.</p>
        </Panel>
        <Panel title="Attribute layers">
          <p className="hint">Enabled attributes contribute to the risk floor.</p>
          <div className="dt-toggles">{ATTRIBUTES.map(k => <Toggle key={k} label={ATTRIBUTE_META[k].label} checked={active.includes(k)} onChange={on => toggleAttribute(k, on)} />)}</div>
          <label className="dt-select">Colour floor by<select aria-label="Colour floor by" value={floor} onChange={e => setFloor(e.target.value as Attribute | 'combined')}><option value="combined">Combined · highest stress</option>{active.map(k => <option value={k} key={k}>{ATTRIBUTE_META[k].label}</option>)}</select></label>
        </Panel>
        <Panel title={`Scenario inputs · ${selected ?? 'whole site'}`}>
          <p className="hint">{selected ? `Changes affect zone ${selected} only.` : 'Changes apply across all zones.'} These are assumed values, not satellite measurements.</p>
          {INPUT_KEYS.map(k => <label className="dt-range" key={k}>{ATTRIBUTE_META[k].label}<b>{current[k]} {ATTRIBUTE_META[k].unit}</b><input aria-label={`Scenario ${ATTRIBUTE_META[k].label}`} type="range" min={ATTRIBUTE_META[k].min} max={ATTRIBUTE_META[k].max} step={ATTRIBUTE_META[k].step} value={current[k]} disabled={!active.includes(k)} onChange={e => editInput(k, Number(e.target.value))} /></label>)}
          <div className="dt-actions">{selected && <button onClick={() => setSelected(null)}>Edit whole site</button>}<button onClick={reset}>Reset scenario</button></div>
        </Panel>
      </aside>
      <section className="dt-centre">
        <div className="dt-scene bcs-panel">
          <SceneBoundary><Suspense fallback={<p className="mp-empty">Loading 3D scene…</p>}><ForestScene cameraScale={1.2} trees={layers.trees ? trees : []} raster={layers.satellite ? raster : null} env={env} zones={zones} selectedZone={selected} hoveredZone={hoveredZone} onHoverZone={setHoveredZone} onSelectZone={id => setSelected(id)} showRisk={layers.risk} showGrid={layers.grid} showWater={layers.water} opacity={opacity} floorRaster={paint !== 'none' ? floorRaster : layers.satellite ? raster : null}>
            <ExtraLayers flags={{ ...extra, reality: extra.reality && matches, riskColumns: extra.riskColumns && layers.risk }} data={data} zones={zones} selectedZone={selected} realityState={realityState} exaggeration={exaggeration} onSelectNode={setSelectedNode} onSelectZone={setSelected} />
          </ForestScene></Suspense></SceneBoundary>
          <div className="dt-map-head"><strong>{region.name}</strong><span>{raster ? `${trees.length.toLocaleString()} visual trees · 25 zones` : 'Waiting for satellite imagery'}</span></div>
          {hoveredZone && zones.find(z => z.id === hoveredZone) && <div className="dt-hover-wellness"><WellnessCard zone={zones.find(z => z.id === hoveredZone)!} raster={raster} active={active} compact /></div>}
          {(busy || error) && <div className="dt-load" role="status">{error || busy}{error && <button onClick={() => void refreshObservation()}>Retry</button>}</div>}
          {examples && <span className="dt-example-badge">EXAMPLE network / carbon / alerts</span>}
          <div className="dt-map-foot"><span>Hover any area for wellness · drag to explore</span><span>{'500 × 500 m · N toward back'}</span></div>
        </div>
        <div className="dt-legend bcs-panel" aria-label="Risk legend">{(['low', 'medium', 'high', 'critical', 'unknown'] as const).map(k => <span key={k}><i style={{ background: RISK_PALETTE[k] }} />{k === 'unknown' ? 'No assessment' : k}<b>{counts[k] ?? 0}</b></span>)}</div>
        <div className="dt-layer-legend bcs-panel" aria-label="Active layer legends">

          {paint === 'classes' && <p>Sentinel-2 scene classes: <i style={{background:'#228b22'}} />Vegetation · <i style={{background:'#1e64c8'}} />Water · <i style={{background:'#8b653c'}} />Bare ground · grey Cloud / unknown. Not a mangrove species classification.</p>}
          {paint === 'cameraClasses' && <p>Camera classes: canopy (green), water (blue), mud (brown), other (grey).</p>}
          {(paint === 'ndvi' || paint === 'cameraNdvi') && <p>{paint === 'ndvi' ? 'Satellite NDVI' : 'Camera VARI / NDVI-proxy'}: brown → yellow → green · index −1 to 1 · grey no data.</p>}
          {INPUT_KEYS.includes(paint as keyof Inputs) && <p>{ATTRIBUTE_META[paint as keyof Inputs].label}: <span className="dt-field-ramp" />{ATTRIBUTE_META[paint as keyof Inputs].min}–{ATTRIBUTE_META[paint as keyof Inputs].max} {ATTRIBUTE_META[paint as keyof Inputs].unit} · {liveFields ? 'sensor IDW' : 'SCENARIO'}</p>}
          {extra.riskColumns && <p>Risk columns: height ∝ scenario score, maximum 65 m.</p>}
          {extra.carbon && <p>Carbon columns: teal, relative tCO₂e (maximum column 65 m). {Object.keys(data.carbon).length ? examples ? 'EXAMPLE figures.' : 'Ground Station summary.' : 'No carbon summary available.'}</p>}
          {(extra.nodes || extra.coverage || extra.tasking) && <p>{data.pins.length} {examples ? 'EXAMPLE' : 'registered'} nodes · WQ coverage 150 m (blue), soil 100 m (purple); tide gauges cover the site. {data.pulsing.length} tasked nodes.</p>}
          {extra.alerts && <p>{data.alerts.length} {examples ? 'EXAMPLE' : 'unacknowledged'} alert markers.</p>}
          {extra.reality && <p>Reality surface: {hasLiveFrame && matches ? 'latest camera colour + depth; holds last frame on disconnect' : 'no camera frame available; satellite remains visible'}.</p>}
        </div>
        <div className="dt-source bcs-panel"><label className="dt-select">Satellite acquisition<select aria-label="Twin satellite acquisition" value={sceneId} disabled={catalogueBusy || !!busy || !scenes.length} onChange={e => void selectObservation(e.target.value)}>{!scenes.length && <option>Loading…</option>}{scenes.map(s => <option key={s.id} value={s.id}>{sceneDate(s)} · {s.properties['eo:cloud_cover'].toFixed(0)}% tile cloud</option>)}</select></label><p className="hint">Shared with Satellite Intelligence. NDVI comes from this observation; water and soil risk attributes are scenario inputs. Tree geometry is estimated.</p><a href="?mangrove-preview#/satellite">View satellite observation ↗</a></div>
        <p className="dt-method">Risk colours blend continuously between analytical areas; hovering reports the underlying area. Soft edges show the study extent, not a surveyed coastline. Scenario screening: the floor uses the highest enabled attribute stress (0–100). Green &lt;30 · yellow 30–59 · orange 60–79 · red ≥80. Grey means insufficient clear land or no enabled attributes. This is separate from the Ground Station’s assessed risk.</p>
      </section>
      <aside className="dt-right">
        <Panel title={zone ? `Zone ${zone.id} · wellness` : 'Tile wellness'}>{zone ? <WellnessCard zone={zone} raster={raster} active={active} /> : <p className="hint">Hover a floor tile for a quick summary, or click a tile to pin its details here.</p>}</Panel>
        <Panel title="Zone selection"><div className="dt-zone-grid" role="group" aria-label="Digital twin zones">{zones.map(z => <button key={z.id} aria-pressed={selected === z.id} aria-label={`Zone ${z.id}: ${z.risk}${z.score === null ? '' : ` ${Math.round(z.score)}`}`} onClick={() => setSelected(z.id)} onMouseEnter={() => setHoveredZone(z.id)} onMouseLeave={() => setHoveredZone(null)} onFocus={() => setHoveredZone(z.id)} onBlur={() => setHoveredZone(null)} style={{ borderColor: RISK_PALETTE[z.risk], background: `${RISK_PALETTE[z.risk]}25` }}>{z.id}</button>)}</div><p className="hint">Select a zone here or on the 3D floor to inspect it and edit local conditions.</p></Panel>
        <Panel title={zone ? `Zone ${zone.id}` : 'Site overview'}>{zone ? <>
          <div className="dt-score" style={{ color: RISK_PALETTE[zone.risk] }}><strong>{zone.score === null ? '—' : Math.round(zone.score)}</strong><span>{zone.risk === 'unknown' ? 'No assessment' : `${zone.risk} scenario risk`}</span></div>
          <p className="hint">100 × 100 m · {(zone.usable * 100).toFixed(0)}% usable clear land</p>
          <dl className="dt-readings">{extra.carbon && <><dt>Carbon stock{examples ? " (EXAMPLE)" : ""}</dt><dd>{data.carbon[zone.id] === undefined ? "Unavailable" : `${data.carbon[zone.id]!.toFixed(1)} tCO₂e`}</dd></>}<dt>Observed NDVI</dt><dd>{zone.ndvi?.toFixed(2) ?? 'No clear data'}</dd><dt>Highest stress</dt><dd>{zone.driver ? ATTRIBUTE_META[zone.driver].label : '—'}</dd>{INPUT_KEYS.map(k => <div key={k}><dt>{ATTRIBUTE_META[k].label}</dt><dd>{zone.inputs[k]} {ATTRIBUTE_META[k].unit}</dd></div>)}</dl>
          <p className="hint">Water and soil values are {overrides[zone.id] ? 'zone-specific assumptions' : 'whole-site assumptions'}.</p>
        </> : <><p className="hint">Change an attribute to see the floor respond. Select a zone for local changes.</p><div className="dt-score"><strong>{raster ? `${raster.clearPct.toFixed(0)}%` : '—'}</strong><span>usable clear land</span></div><p className="hint">{scene ? sceneDate(scene) : 'No observation loaded'}</p></>}</Panel>
        <Panel title="Layer data">
          <Toggle label="Show example layer data" checked={examples} onChange={setExamples} />
          <p className="hint">{examples ? 'Example network, coverage, tasking, alerts and carbon are for visual testing only. They are not saved or sent to the backend.' : `Ground Station: ${connection}. No records are fabricated when data is unavailable.`}</p>
          {selectedNode && <p className="hint">Selected node: {selectedNode}</p>}
          <p className="hint">{matches ? 'Ground Station data matches this site.' : 'Ground Station layers are hidden until the registered site matches this satellite footprint.'}</p>
        </Panel>
        <Panel title="Data & assumptions"><p className="hint">Sensor stress breakpoints follow the project’s configured bands. Soil moisture uses an illustrative stress rule. NDVI screening uses an illustrative absolute-index rule, not a measured canopy-loss baseline.</p><p className="hint">Clouds and missing pixels stay unassessed. Scenario colours are not verified environmental alerts.</p></Panel>
      </aside>
    </div>
  </div>
}
