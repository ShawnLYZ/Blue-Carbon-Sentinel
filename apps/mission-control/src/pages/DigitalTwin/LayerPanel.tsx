// The Digital Twin layer panel (design §26) with the legend of what is drawn.
import { Panel, Toggle, riskColor, type RiskClass } from '@bcs/ui'
import { useAppStore } from '../../data/store'
import { CARBON_TEAL } from '../../twin/CarbonColumns'
import { COLUMN_MAX_M } from '../../twin/columnMath'
import { paramMeta } from '../../data/network'
import {
  CLASS_PALETTE,
  FIELD_RAMP,
  NDVI_RAMP,
  NDVI_RANGE,
  RISK_COLUMNS_KEY,
  SOIL_FIELDS,
  WATER_FIELDS,
  activeOverlay,
  fieldLegend,
  isFieldKey,
  layerChanges,
  layerOn,
  rampCss,
  useOverlayStatus,
} from '../../twin/layers'

interface Row {
  key: string
  label: string
  disabled?: string
}

const GROUPS: { title: string; rows: Row[] }[] = [
  {
    title: 'Surface',
    rows: [
      { key: 'reality', label: 'Reality surface' },
      { key: 'ndvi', label: 'NDVI-proxy' },
      { key: 'classes', label: 'Land-cover classes' },
      { key: 'grid', label: 'Field contours' },
    ],
  },
  {
    title: 'Risk and carbon',
    rows: [
      { key: 'risk', label: 'Risk tiles' },
      { key: RISK_COLUMNS_KEY, label: 'Risk columns' },
      { key: 'carbon', label: 'Carbon columns' },
    ],
  },
  { title: 'Water fields (WQ)', rows: WATER_FIELDS.map((p) => ({ key: `water:${p}`, label: paramMeta(p).label })) },
  { title: 'Soil fields (SP)', rows: SOIL_FIELDS.map((p) => ({ key: `soil:${p}`, label: paramMeta(p).label })) },
  {
    title: 'Network and site',
    rows: [
      { key: 'nodes', label: 'Nodes' },
      { key: 'coverage', label: 'Coverage' },
      { key: 'tasking', label: 'Tasking pulses' },
      { key: 'trees', label: 'Trees' },
      { key: 'alerts', label: 'Alert markers' },
    ],
  },
]

const RISK_CLASSES: RiskClass[] = ['low', 'medium', 'high', 'critical']

function fmtTick(v: number, dp: number): string {
  return v.toFixed(dp)
}

export function Legend() {
  const layers = useAppStore((s) => s.ui.layers)
  const status = useOverlayStatus()
  const overlay = activeOverlay(layers)
  const treesOn = layerOn(layers, 'trees')
  const hasTrees = useAppStore((s) => (s.trees.points?.points.length ?? 0) > 0)

  return (
    <div className="twin-legend" data-testid="legend">
      {isFieldKey(overlay) &&
        (() => {
          const l = fieldLegend(overlay)
          const water = overlay.startsWith('water:')
          return (
            <div className="twin-legend__block">
              <div className="twin-legend__title">
                {l.label} ({l.unit})
              </div>
              <div className="twin-legend__ramp" style={{ background: rampCss(FIELD_RAMP) }} />
              <div className="twin-legend__ticks">
                <span>
                  {fmtTick(l.min, l.dp)} {l.unit}
                </span>
                <span>
                  {fmtTick(l.max, l.dp)} {l.unit}
                </span>
              </div>
              <p className="hint">
                IDW from {status.points} {water ? 'WQ' : 'SP'} node{status.points === 1 ? '' : 's'};{' '}
                {status.classMap === 'ok'
                  ? `clipped to ${water ? 'water' : 'land'} in the latest class map`
                  : status.classMap === 'loading'
                    ? 'loading the class map…'
                    : 'no class map yet — drawn unclipped'}
              </p>
            </div>
          )
        })()}
      {overlay === 'ndvi' && (
        <div className="twin-legend__block">
          <div className="twin-legend__title">NDVI-proxy (VARI)</div>
          <div className="twin-legend__ramp" style={{ background: rampCss(NDVI_RAMP) }} />
          <div className="twin-legend__ticks">
            <span>{NDVI_RANGE[0].toFixed(1)}</span>
            <span>{NDVI_RANGE[1].toFixed(1)}</span>
          </div>
          {status.ndvi !== 'ok' && <p className="hint">{status.ndvi === 'loading' ? 'Loading…' : 'No NDVI-proxy map in the recent captures.'}</p>}
        </div>
      )}
      {overlay === 'classes' && (
        <div className="twin-legend__block">
          <div className="twin-legend__title">Land-cover classes</div>
          <ul className="twin-legend__swatches">
            {CLASS_PALETTE.filter((c) => c.code > 0).map((c) => (
              <li key={c.code}>
                <span className="twin-legend__swatch" style={{ background: `rgb(${c.rgb.join(' ')})` }} />
                {c.label}
              </li>
            ))}
          </ul>
          {status.classMap !== 'ok' && <p className="hint">{status.classMap === 'loading' ? 'Loading…' : 'No class map in the recent captures.'}</p>}
        </div>
      )}
      {layerOn(layers, 'risk') && (
        <div className="twin-legend__block">
          <div className="twin-legend__title">Risk</div>
          <ul className="twin-legend__swatches">
            {RISK_CLASSES.map((c) => (
              <li key={c}>
                <span className="risk-chip" data-testid={`risk-chip-sample-${c}`} style={{ background: riskColor(c) }}>
                  {c}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {layerOn(layers, 'carbon') && (
        <div className="twin-legend__block" data-testid="carbon-legend">
          <div className="twin-legend__title">Carbon stock (tCO₂e)</div>
          <ul className="twin-legend__swatches">
            <li>
              <span className="twin-legend__swatch" style={{ background: CARBON_TEAL }} />
              column height ∝ the zone's tCO₂e (tallest zone = {COLUMN_MAX_M} m)
            </li>
          </ul>
        </div>
      )}
      {treesOn && !hasTrees && <p className="hint">No trees located yet.</p>}
    </div>
  )
}

export function LayerPanel() {
  const layers = useAppStore((s) => s.ui.layers)
  const toggleLayer = useAppStore((s) => s.toggleLayer)
  const set = (key: string, on: boolean) => {
    for (const [k, v] of Object.entries(layerChanges(key, on))) toggleLayer(k, v)
  }
  return (
    <Panel title="Layers" className="twin-layers">
      {GROUPS.map((g) => (
        <fieldset key={g.title} className="twin-layers__group">
          <legend>{g.title}</legend>
          {g.rows.map((r) => (
            <div key={r.key} className="twin-layers__row" data-layer={r.key}>
              <Toggle
                label={r.label}
                checked={!r.disabled && layerOn(layers, r.key)}
                disabled={!!r.disabled || (r.key === RISK_COLUMNS_KEY && !layerOn(layers, 'risk'))}
                onChange={(v) => set(r.key, v)}
              />
              {r.disabled && <span className="twin-layers__note">{r.disabled}</span>}
            </div>
          ))}
        </fieldset>
      ))}
      <Legend />
    </Panel>
  )
}
