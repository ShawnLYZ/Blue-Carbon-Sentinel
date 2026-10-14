import type { Assessment, SourceChip, VisionObservationView } from '@bcs/api-types'

export type ObservationKind = VisionObservationView['kind']

export const KIND_ICON: Record<ObservationKind, string> = {
  dieback: '\u25BC',
  clearing: '\u2702',
  new_growth: '\u25B2',
  discolouration: '\u25D0',
  none: '\u2713',
}

export interface ZoneObservations {
  zoneId: string
  observations: VisionObservationView[]
  /** The tier that produced the observations (the assessment's own chip when VisionAnalyst answered on the same tier). */
  source: SourceChip
}

/** Per zone, the newest assessment's observations; zones without any are left out. Sorted by zone id. */
export function observationsByZone(byZone: Record<string, Assessment>): ZoneObservations[] {
  return Object.values(byZone)
    .filter((a) => (a.observations ?? []).length > 0)
    .map((a) => ({ zoneId: a.zone_id, observations: a.observations ?? [], source: a.observations_source ?? a.source }))
    .sort((x, y) => x.zoneId.localeCompare(y.zoneId))
}
