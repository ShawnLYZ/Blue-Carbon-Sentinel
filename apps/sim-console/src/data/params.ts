/** Display metadata per reading (G4 names). Slider ranges stay inside the G4 validation ranges. */
export interface ParamMeta {
  label: string
  unit: string
  min: number
  max: number
  step: number
  dp: number
}

export const PARAMS: Record<string, ParamMeta> = {
  salinity_psu: { label: 'Salinity', unit: 'PSU', min: 0, max: 60, step: 0.1, dp: 1 },
  turbidity_ntu: { label: 'Turbidity', unit: 'NTU', min: 0, max: 1000, step: 1, dp: 1 },
  do_mg_l: { label: 'Dissolved O₂', unit: 'mg/L', min: 0, max: 20, step: 0.05, dp: 2 },
  temp_c: { label: 'Temperature', unit: '°C', min: 0, max: 45, step: 0.1, dp: 2 },
  ph: { label: 'pH', unit: '', min: 0, max: 14, step: 0.01, dp: 2 },
  porewater_salinity_psu: { label: 'Porewater salinity', unit: 'PSU', min: 0, max: 120, step: 0.5, dp: 1 },
  soil_moisture_pct: { label: 'Soil moisture', unit: '%', min: 0, max: 100, step: 0.5, dp: 1 },
  water_level_cm: { label: 'Water level', unit: 'cm', min: -500, max: 500, step: 1, dp: 0 },
}

export function paramMeta(name: string): ParamMeta {
  return PARAMS[name] ?? { label: name, unit: '', min: 0, max: 100, step: 0.1, dp: 2 }
}

export const TYPE_SHORT: Record<string, string> = { water_quality: 'WQ', soil_probe: 'SP', tide_gauge: 'TG' }
export const TYPE_LABEL: Record<string, string> = {
  water_quality: 'Water quality',
  soil_probe: 'Soil probe',
  tide_gauge: 'Tide gauge',
}

/** Coverage radii (global constraints): WQ 150 m, SP 100 m; the TG is site-wide. */
export const COVERAGE_RADIUS_M: Record<string, number> = { water_quality: 150, soil_probe: 100 }

/** F5 fault kinds with their toggle labels. */
export const FAULTS: { kind: string; label: string }[] = [
  { kind: 'offline', label: 'Offline' },
  { kind: 'stuck', label: 'Stuck' },
  { kind: 'spikes', label: 'Spikes' },
  { kind: 'drift', label: 'Drift' },
  { kind: 'low_battery', label: 'Low battery' },
  { kind: 'late', label: 'Late' },
  { kind: 'duplicate', label: 'Duplicate' },
  { kind: 'out_of_order', label: 'Out of order' },
  { kind: 'malformed', label: 'Malformed' },
]
/** Faults that act on one parameter (params.parameter). */
export const PARAM_FAULTS = new Set(['stuck', 'spikes', 'drift'])
