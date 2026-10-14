// Sentinel Network display helpers shared by the page, the map layers and the System sections.
import type { Node, Task } from '@bcs/api-types'

/** Display metadata per reading (addendum F3 names and units; resolutions from design §10). */
export interface ParamMeta {
  label: string
  unit: string
  dp: number
}

export const PARAMS: Record<string, ParamMeta> = {
  salinity_psu: { label: 'Salinity', unit: 'PSU', dp: 1 },
  turbidity_ntu: { label: 'Turbidity', unit: 'NTU', dp: 1 },
  do_mg_l: { label: 'Dissolved O₂', unit: 'mg/L', dp: 2 },
  temp_c: { label: 'Water temperature', unit: '°C', dp: 2 },
  ph: { label: 'pH', unit: 'pH', dp: 2 },
  porewater_salinity_psu: { label: 'Porewater salinity', unit: 'PSU', dp: 1 },
  soil_moisture_pct: { label: 'Soil moisture', unit: '% VWC', dp: 1 },
  water_level_cm: { label: 'Water level', unit: 'cm', dp: 0 },
}

export function paramMeta(name: string): ParamMeta {
  return PARAMS[name] ?? { label: name, unit: '', dp: 2 }
}

export type NodeType = Node['node_type']

/** Readings each node type reports (design §10), in display order. */
export const TYPE_PARAMS: Record<NodeType, string[]> = {
  water_quality: ['salinity_psu', 'turbidity_ntu', 'do_mg_l', 'temp_c', 'ph'],
  soil_probe: ['porewater_salinity_psu', 'soil_moisture_pct'],
  tide_gauge: ['water_level_cm'],
}

export const TYPE_SHORT: Record<NodeType, string> = { water_quality: 'WQ', soil_probe: 'SP', tide_gauge: 'TG' }
export const TYPE_LABEL: Record<NodeType, string> = {
  water_quality: 'Water quality',
  soil_probe: 'Soil probe',
  tide_gauge: 'Tide gauge',
}

/** Pin and ring colours by node type; offline nodes are grey. */
export const TYPE_COLOUR: Record<NodeType, string> = {
  water_quality: '#1aa7ff',
  soil_probe: '#e0a050',
  tide_gauge: '#f1c40f',
}
export const OFFLINE_COLOUR = '#6b7b82'

/** Coverage radii (global constraints): WQ 150 m, SP 100 m; the TG is site-wide (no ring). */
export const COVERAGE_RADIUS_M: Partial<Record<NodeType, number>> = { water_quality: 150, soil_probe: 100 }

export function isOnline(n: Pick<Node, 'status'>): boolean {
  return n.status === 'online'
}

export function sourceText(source: Node['source']): string {
  return source === 'simulated' ? 'SIMULATED' : 'HARDWARE'
}

export function fmtNum(v: number | null | undefined, dp: number, unit = ''): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return unit ? `${v.toFixed(dp)} ${unit}` : v.toFixed(dp)
}

/** Open tasks are still commanding their nodes. */
export function isOpenTask(t: Pick<Task, 'status'>): boolean {
  return t.status === 'issued' || t.status === 'active'
}

/** Nodes an open task still holds (released and never-acknowledged nodes drop out). */
export function heldNodes(t: Task): string[] {
  const gone = new Set(t.commands.filter((c) => c.ack_status === 'released' || c.ack_status === 'no_ack').map((c) => c.node_id))
  return t.node_ids.filter((id) => !gone.has(id))
}

export const METHOD_TEXT: Record<string, string> = { class_map: 'class map', fallback_spread: 'fallback spread' }

/** Re-commission confirmation copy (shared by Sentinel Network and System). */
export const RECOMMISSION_TEXT =
  'Re-commission the Sentinel Network from the latest capture? Node positions will change: every node is placed again, ' +
  'open tasks are cancelled and coverage is recomputed.'
