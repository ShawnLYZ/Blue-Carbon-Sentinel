// The Digital Twin page's map layers (design §26), each behind its layer-panel switch: the surface
// overlay (NDVI-proxy, classes, water and soil fields), zone grid, risk tiles, the network layers,
// trees, alert markers and the zone hit targets.
import type { Site } from '@bcs/api-types'
import { useAppStore } from '../data/store'
import { AlertMarkers } from './AlertMarkers'
import { CarbonColumns } from './CarbonColumns'
import { CoverageRings } from './CoverageRings'
import { FieldOverlay } from './FieldOverlay'
import { NodePins } from './NodePins'
import { RiskTiles } from './RiskTiles'
import { TaskingPulses } from './TaskingPulses'
import { Trees } from './Trees'
import { ZoneHits } from './ZoneHits'
import { RISK_COLUMNS_KEY, layerOn } from './layers'

export function TwinLayers({ site }: { site: Site }) {
  const layers = useAppStore((s) => s.ui.layers)
  const on = (k: string) => layerOn(layers, k)
  return (
    <>
      <FieldOverlay />
      <ZoneHits zones={site.zones} />
      {on('risk') && <RiskTiles zones={site.zones} columns={on(RISK_COLUMNS_KEY)} />}
      {on('carbon') && <CarbonColumns zones={site.zones} />}
      {on('coverage') && <CoverageRings />}
      {on('nodes') && <NodePins />}
      {on('tasking') && <TaskingPulses />}
      {on('trees') && <Trees />}
      {on('alerts') && <AlertMarkers zones={site.zones} />}
    </>
  )
}
