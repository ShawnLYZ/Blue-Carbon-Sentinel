import { ATTRIBUTE_META, ATTRIBUTES, classify, type Attribute, type RiskZone } from './scenarioRisk'
import type { Raster } from './satellite'

export const ATTRIBUTE_LABEL: Record<Attribute, string> = { ndvi: 'Vegetation', salinity: 'Salinity', oxygen: 'Oxygen', turbidity: 'Turbidity', temperature: 'Temperature', ph: 'pH', soilSalinity: 'Soil salinity', soilMoisture: 'Soil moisture' }
const CONCERNS: Record<Attribute, string> = {
  ndvi: 'Vegetation index falls below the preview’s low-stress range.',
  salinity: 'Water salinity exceeds the configured low-stress band.',
  oxygen: 'Dissolved oxygen falls below the configured low-stress band.',
  turbidity: 'Turbidity exceeds the configured low-stress band.',
  temperature: 'Water temperature exceeds the configured low-stress band.',
  ph: 'pH falls outside the configured low-stress range.',
  soilSalinity: 'Soil salinity exceeds the configured low-stress band.',
  soilMoisture: 'Soil moisture falls outside the illustrative low-stress range.',
}
export function wellnessSummary(zone: RiskZone, active: readonly Attribute[], raster: Raster | null) {
  const rows = ATTRIBUTES.map(key => {
    const value = key === 'ndvi' ? zone.ndvi : zone.inputs[key]
    const enabled = active.includes(key)
    const stress = enabled ? zone.stress[key] : undefined
    const pct = stress === undefined ? null : Math.round(stress * 100)
    const dp = key === 'ndvi' ? 2 : ['ph', 'oxygen', 'temperature'].includes(key) ? 1 : 0
    return { key, label: ATTRIBUTE_LABEL[key], enabled, pct, rawScore: stress === undefined ? null : stress * 100, risk: classify(stress === undefined ? null : stress * 100), value: value === null ? 'No data' : `${value.toFixed(dp)}${ATTRIBUTE_META[key].unit ? ` ${ATTRIBUTE_META[key].unit}` : ''}`, source: key === 'ndvi' ? 'Satellite' : 'Scenario' }
  })
  const assessed = rows.filter(r => r.pct !== null)
  const worst = [...assessed].sort((a, b) => b.rawScore! - a.rawScore!)[0]
  const score = worst?.pct ?? null
  const good = assessed.filter(r => r.rawScore! < 30)
  let vegetated = 0, total = 0
  if (raster) for (let y = Math.floor(zone.row * raster.height / 5); y < Math.floor((zone.row + 1) * raster.height / 5); y++) {
    for (let x = Math.floor(zone.col * raster.width / 5); x < Math.floor((zone.col + 1) * raster.width / 5); x++) {
      const i = y * raster.width + x; total++
      if (raster.valid[i] && raster.ndvi[i]! >= 0.35) vegetated++
    }
  }
  return {
    rows, score, risk: classify(worst?.rawScore ?? null), clearPct: Math.round(zone.usable * 100), vegetationPct: total ? Math.round(vegetated / total * 100) : null,
    concern: score === null ? 'Insufficient clear satellite data or no enabled attributes: wellness is unassessed.' : worst!.rawScore! < 30 ? 'No elevated stress among the enabled attributes in this preview.' : `${CONCERNS[worst!.key]} It is the largest enabled stress contributor (${score}%).`,
    good: good.length ? `${good.slice(0, 3).map(r => r.label).join(', ')} ${good.length === 1 ? 'is' : 'are'} in the preview’s low-stress range${good.length > 3 ? ` (${good.length} attributes in total)` : ''}.` : 'No enabled attribute is currently assessed in the low-stress range.',
  }
}
