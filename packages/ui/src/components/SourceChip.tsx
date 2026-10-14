import { tierLabel } from '../lib/format'

export interface SourceChipProps {
  tier: string
  model?: string | null
  cached?: boolean
}

/** Shows which AI tier produced an answer (addendum F5 display names). */
export function SourceChip({ tier, model, cached = false }: SourceChipProps) {
  return (
    <span className="bcs-chip bcs-chip--source" title={model ?? undefined} data-tier={tier} data-cached={cached} data-testid="source-chip">
      {tierLabel(tier, cached)}
    </span>
  )
}
