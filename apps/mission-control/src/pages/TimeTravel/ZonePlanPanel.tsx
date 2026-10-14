// The zone panel of the "with restoration" map (US 151): add or remove interventions, choose the species
// and adjust the saplings of the clicked zone. Every change is a PUT of the whole plan (a new draft
// version). The API's validation answers show here: a 422 (e.g. planting with no mud) as an error with the
// plan unchanged and still editable, and warnings (e.g. the species switch above 40 PSU, whose text names
// no zone) in the panel of the zone the edit came from (Review Focus 2).
import { useEffect, useState } from 'react'
import { Button } from '@bcs/ui'
import type { Intervention, PlanVersion } from '@bcs/api-types'
import type { ZoneNote } from './useTimeTravel'

export type Kind = Intervention['kind']

export const DENSITY_PER_HA = 4400
export const PLANT_KINDS: Kind[] = ['plant_rhizophora', 'plant_avicennia']
export const KIND_LABELS: Record<Kind, string> = {
  plant_rhizophora: 'Rhizophora apiculata',
  plant_avicennia: 'Avicennia marina',
  silt_fence: 'Silt fence',
  reopen_channel: 'Reopen tidal channel',
  stop_pollution: 'Stop pollution source',
}
const KIND_ORDER: Kind[] = ['plant_rhizophora', 'plant_avicennia', 'silt_fence', 'reopen_channel', 'stop_pollution']

export function isPlanting(k: Kind): boolean {
  return PLANT_KINDS.includes(k)
}

/** Default saplings for a new planting: min(mud fraction, 0.5) ha of the 1 ha zone at 4,400/ha (§20). */
export function defaultSaplings(mudPct: number | undefined): number {
  const area = mudPct === undefined || !Number.isFinite(mudPct) ? 0.25 : Math.min(Math.max(mudPct, 0) / 100, 0.5)
  return Math.max(100, Math.round((area * DENSITY_PER_HA) / 10) * 10)
}

function SaplingInput({ value, disabled, onCommit }: { value: number; disabled: boolean; onCommit: (n: number) => void }) {
  const [draft, setDraft] = useState(String(value))
  useEffect(() => setDraft(String(value)), [value])
  const commit = () => {
    const n = Math.round(Number(draft))
    if (!Number.isFinite(n) || n < 0) setDraft(String(value))
    else if (n !== value) onCommit(n)
  }
  return (
    <input
      className="tt-zone__saplings"
      type="number"
      aria-label="Saplings"
      min={0}
      step={100}
      value={draft}
      disabled={disabled}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit()
      }}
    />
  )
}

export interface ZonePlanPanelProps {
  zoneId: string
  plan: PlanVersion | null
  note: ZoneNote | undefined
  busy: boolean
  mudPct: number | undefined
  onChange: (interventions: Intervention[]) => void
  onClose: () => void
}

export function ZonePlanPanel({ zoneId, plan, note, busy, mudPct, onChange, onClose }: ZonePlanPanelProps) {
  const ivs = plan?.items.find((i) => i.zone_id === zoneId)?.interventions ?? []
  const disabled = !plan || busy
  const has = (k: Kind) => ivs.some((iv) => iv.kind === k)

  const add = (k: Kind) => {
    if (isPlanting(k)) {
      const n = defaultSaplings(mudPct)
      onChange([...ivs, { kind: k, sapling_count: n, planted_area_ha: n / DENSITY_PER_HA }])
    } else onChange([...ivs, { kind: k }])
  }
  const replace = (i: number, iv: Intervention) => onChange(ivs.map((x, j) => (j === i ? iv : x)))
  const remove = (i: number) => onChange(ivs.filter((_, j) => j !== i))

  return (
    <section className="bcs-panel tt-zone" data-testid="zone-plan-panel" aria-label={`Plan for ${zoneId}`}>
      <header className="tt-zone__head">
        <h3 className="bcs-panel__title">{zoneId} plan</h3>
        <Button aria-label="Close zone plan" onClick={onClose}>
          ×
        </Button>
      </header>
      {!plan && <p className="hint">Propose a plan first (the AI drafts version 1), then edit it zone by zone here.</p>}
      {ivs.length === 0 ? (
        plan && <p className="hint">No interventions in this zone.</p>
      ) : (
        <ul className="tt-zone__list">
          {ivs.map((iv, i) => (
            <li key={`${iv.kind}-${i}`} className="tt-zone__row">
              {isPlanting(iv.kind) ? (
                <>
                  <select
                    aria-label="Species"
                    value={iv.kind}
                    disabled={disabled}
                    onChange={(e) => replace(i, { ...iv, kind: e.target.value as Kind })}
                  >
                    {PLANT_KINDS.map((k) => (
                      <option key={k} value={k}>
                        {KIND_LABELS[k]}
                      </option>
                    ))}
                  </select>
                  <SaplingInput
                    value={iv.sapling_count ?? Math.round((iv.planted_area_ha ?? 0) * DENSITY_PER_HA)}
                    disabled={disabled}
                    onCommit={(n) => replace(i, { ...iv, sapling_count: n, planted_area_ha: n / DENSITY_PER_HA })}
                  />
                  <span className="hint">saplings</span>
                </>
              ) : (
                <span className="tt-zone__kind">{KIND_LABELS[iv.kind]}</span>
              )}
              <Button aria-label={`Remove ${KIND_LABELS[iv.kind]}`} disabled={disabled} onClick={() => remove(i)}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="row-actions">
        {KIND_ORDER.map((k) => (
          <Button key={k} disabled={disabled || (!isPlanting(k) && has(k))} onClick={() => add(k)}>
            Add {KIND_LABELS[k]}
          </Button>
        ))}
      </div>
      {note?.error && (
        <p className="tt-zone__error" role="alert">
          {note.error}
        </p>
      )}
      {note && note.warnings.length > 0 && (
        <ul className="tt-zone__warnings" role="status">
          {note.warnings.map((w) => (
            <li key={w}>
              {zoneId}: {w}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
