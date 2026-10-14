// The Digital Twin zone card (design §26): opens on a zone click and shows every field of the zone.
import { useEffect, useState, type ReactNode } from 'react'
import type { Assessment, Node, Zone, ZoneDetail } from '@bcs/api-types'
import { Button, Chip, SourceChip, formatMYTDateTime, riskColor } from '@bcs/ui'
import { api } from '../../data/client'
import { apiErrorCode, apiErrorText, networkErrorText } from '../../data/apiError'
import { useSettledRev } from '../../data/hooks'
import { TYPE_PARAMS, TYPE_SHORT, fmtNum, paramMeta } from '../../data/network'
import { useAppStore } from '../../data/store'
import { navigate } from '../../shell/router'
import { fmtTco2e } from '../CommandCenter/carbonFormat'
import { fmt, signed } from '../SatelliteIntel/shared'

export const STRESSOR_LABELS: Record<string, string> = {
  vegetation: 'Vegetation decline',
  salinity: 'Salinity',
  porewater_salinity: 'Porewater salinity',
  turbidity: 'Turbidity',
  do: 'Dissolved O₂',
  temperature: 'Temperature',
  ph: 'pH',
}

export const CONFIDENCE_KEYS = ['camera', 'sensor', 'prediction', 'overall'] as const

const MESSAGE_MS = 6000

/** Zone detail (metrics, last capture), refetched when capture events settle. */
function useZoneDetail(zoneId: string): { detail: ZoneDetail | null; error: string | null } {
  const rev = useSettledRev('captures')
  const [state, setState] = useState<{ id: string; detail: ZoneDetail | null; error: string | null } | null>(null)
  useEffect(() => {
    let live = true
    api.GET('/api/v1/zones/{zone_id}', { params: { path: { zone_id: zoneId }, query: { limit: 2 } } }).then(
      (r) => {
        if (live) setState({ id: zoneId, detail: r.data ?? null, error: r.data ? null : apiErrorText(r.error, 'Could not load the zone.') })
      },
      (e: unknown) => {
        if (live) setState({ id: zoneId, detail: null, error: networkErrorText(e) })
      },
    )
    return () => {
      live = false
    }
  }, [zoneId, rev])
  return state?.id === zoneId ? { detail: state.detail, error: state.error } : { detail: null, error: null }
}

/** The WQ and SP nodes covering a zone (coverage snapshot), in registry order. */
function useCoveringNodes(zoneId: string): Node[] {
  const coverage = useAppStore((s) => s.coverage.coverage)
  const nodes = useAppStore((s) => s.nodes.items)
  const cz = coverage?.zones.find((z) => z.zone_id === zoneId)
  const ids = new Set([...(cz?.water ?? []), ...(cz?.soil ?? [])])
  return nodes.filter((n) => ids.has(n.id) && n.status !== 'decommissioned')
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="zone-card__section">
      <h4 className="zone-card__heading">{title}</h4>
      {children}
    </section>
  )
}

function Stressors({ a }: { a: Assessment | undefined }) {
  if (!a) return <p className="hint">No assessment yet.</p>
  return (
    <ul className="zone-card__stressors">
      {Object.entries(a.stressors).map(([k, v]) => (
        <li key={k}>
          <span>{STRESSOR_LABELS[k] ?? k}</span>
          {v === null ? (
            <span className="hint">unmeasured</span>
          ) : (
            <span className="zone-card__meter" title={v.toFixed(2)}>
              <span style={{ width: `${Math.round(Math.min(1, Math.max(0, v)) * 100)}%` }} />
              <em>{v.toFixed(2)}</em>
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}

function ConfidenceBars({ a }: { a: Assessment | undefined }) {
  return (
    <ul className="zone-card__confidence">
      {CONFIDENCE_KEYS.map((k) => {
        const v = a?.confidence[k]
        const pct = v === undefined ? null : Math.round(Math.min(1, Math.max(0, v)) * 100)
        return (
          <li key={k} data-testid="confidence-bar" data-kind={k}>
            <span className="zone-card__conf-label">{k}</span>
            <span className="zone-card__meter">
              <span style={{ width: `${pct ?? 0}%` }} />
            </span>
            <span className="bcs-mono">{pct === null ? '—' : `${pct}%`}</span>
          </li>
        )
      })}
    </ul>
  )
}

function Readings({ nodes }: { nodes: Node[] }) {
  if (nodes.length === 0) return <p className="hint">No WQ or SP node covers this zone.</p>
  return (
    <ul className="zone-card__readings">
      {nodes.map((n) => (
        <li key={n.id}>
          <span className="node-type">
            {n.id} · {TYPE_SHORT[n.node_type]}
          </span>
          {n.status !== 'online' && <span className="hint"> ({n.status})</span>}
          <span className="zone-card__values">
            {TYPE_PARAMS[n.node_type].map((p) => {
              const m = paramMeta(p)
              return (
                <span key={p}>
                  {m.label} {fmtNum(n.latest?.readings[p], m.dp, m.unit)}
                </span>
              )
            })}
          </span>
        </li>
      ))}
    </ul>
  )
}

type Message = { kind: 'ok' | 'error'; text: string }

export function ZoneCard({ zone, onClose }: { zone: Zone; onClose: () => void }) {
  const { detail, error } = useZoneDetail(zone.id)
  const assessment = useAppStore((s) => s.assessments.byZone[zone.id])
  const covering = useCoveringNodes(zone.id)
  const upsertTask = useAppStore((s) => s.upsertTask)
  const [busy, setBusy] = useState<'task' | 'analyze' | null>(null)
  const [message, setMessage] = useState<Message | null>(null)

  useEffect(() => {
    if (!message) return
    const t = setTimeout(() => setMessage(null), MESSAGE_MS)
    return () => clearTimeout(t)
  }, [message])

  const m = detail?.metrics ?? null
  const ndviChange = m?.vari_drop === null || m?.vari_drop === undefined ? null : -m.vari_drop

  const taskNodes = async () => {
    setBusy('task')
    try {
      const r = await api.POST('/api/v1/tasks', { body: { zone_id: zone.id } })
      if (r.data) {
        upsertTask(r.data)
        setMessage({ kind: 'ok', text: `Task issued to ${r.data.node_ids.length} node${r.data.node_ids.length === 1 ? '' : 's'}.` })
      } else setMessage({ kind: 'error', text: apiErrorText(r.error, 'The task was not created.') })
    } catch (e) {
      setMessage({ kind: 'error', text: networkErrorText(e) })
    }
    setBusy(null)
  }

  const analyze = async () => {
    setBusy('analyze')
    try {
      const r = await api.POST('/api/v1/zones/{zone_id}/analyze', { params: { path: { zone_id: zone.id } } })
      if (r.response.status === 202) setMessage({ kind: 'ok', text: 'Analysis requested — the narrative updates when it arrives.' })
      else if (r.response.status === 429 || apiErrorCode(r.error) === 'rate_limited') {
        const wait = (r.error as { error?: { details?: { retry_after_s?: number } | null } } | undefined)?.error?.details?.retry_after_s
        setMessage({ kind: 'error', text: `AI analysis rate limited${wait ? ` — try again in ${Math.ceil(wait)} s` : ''}.` })
      } else setMessage({ kind: 'error', text: apiErrorText(r.error, 'The analysis was not requested.') })
    } catch (e) {
      setMessage({ kind: 'error', text: networkErrorText(e) })
    }
    setBusy(null)
  }

  return (
    <article className="bcs-panel zone-card" data-testid="zone-card" aria-label={`Zone ${zone.id}`}>
      <header className="zone-card__head">
        <div>
          <h3 className="zone-card__title">{zone.id}</h3>
          <div className="hint">
            {zone.coordinate_id} · {zone.area_ha.toFixed(2)} ha
          </div>
        </div>
        <button type="button" className="link-button zone-card__close" aria-label="Close zone card" onClick={onClose}>
          ✕
        </button>
      </header>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <Section title="Vegetation">
        <dl className="kv-list">
          <dt>Canopy</dt>
          <dd>{fmt(m?.canopy_pct, 1, '%')}</dd>
          <dt>NDVI-proxy</dt>
          <dd>
            {fmt(m?.vari_mean, 3)}
            {ndviChange !== null && <span className="hint"> ({signed(ndviChange, 3)} vs baseline)</span>}
          </dd>
          <dt>Dieback</dt>
          <dd>{fmt(m?.dieback_pct, 1, '%')}</dd>
          <dt>New growth</dt>
          <dd>{fmt(m?.new_growth_pct, 1, '%')}</dd>
        </dl>
      </Section>

      <Section title="Readings (covering nodes)">
        <Readings nodes={covering} />
      </Section>

      <Section title="Stressors">
        <Stressors a={assessment} />
      </Section>

      <Section title="Risk">
        {assessment ? (
          <div className="zone-card__risk">
            <span className="zone-card__risk-score bcs-mono">{assessment.risk_score.toFixed(0)}</span>
            <Chip color={riskColor(assessment.risk_class)}>{assessment.risk_class}</Chip>
            {assessment.early_warning && (
              <Chip color="#ffcf66" title="Sub-canopy stress — not yet visible from orbit">
                Early warning
              </Chip>
            )}
          </div>
        ) : (
          <p className="hint">Not assessed yet.</p>
        )}
      </Section>

      <Section title="Confidence">
        <ConfidenceBars a={assessment} />
      </Section>

      <Section title="Carbon stock">
        <p className="zone-card__carbon">
          {detail?.carbon_stock_tco2e == null ? '—' : `${fmtTco2e(detail.carbon_stock_tco2e)} tCO₂e`}{' '}
          <span className="hint">standing stock, not a credit</span>
        </p>
      </Section>

      <Section title="Root cause">
        {assessment ? (
          <div className="zone-card__narrative">
            <div className="zone-card__source">
              <SourceChip tier={assessment.source.tier} model={assessment.source.model} cached={assessment.source.cached} />
            </div>
            {assessment.narrative ? <p>{assessment.narrative}</p> : <p className="hint">No AI narrative yet.</p>}
            {assessment.root_causes.length > 0 && (
              <ol className="zone-card__causes">
                {[...assessment.root_causes]
                  .sort((x, y) => x.rank - y.rank)
                  .map((c) => (
                    <li key={`${c.rank}-${c.driver}`}>
                      <strong>{c.driver}</strong> — {c.why}
                    </li>
                  ))}
              </ol>
            )}
          </div>
        ) : (
          <p className="hint">No assessment yet.</p>
        )}
      </Section>

      <p className="hint zone-card__capture">
        Last capture: {detail?.last_capture_at ? formatMYTDateTime(detail.last_capture_at) : '—'}
      </p>

      <div className="row-actions">
        <Button variant="primary" disabled={busy !== null} onClick={taskNodes}>
          Task nodes
        </Button>
        <Button disabled={busy !== null} onClick={analyze}>
          Request AI analysis
        </Button>
        <Button title="Time Travel opens with this zone's plan panel" onClick={() => navigate('time-travel')}>
          Open in Time Travel
        </Button>
      </div>
      {message && (
        <div className="zone-card__toast" role="status" data-kind={message.kind}>
          {message.text}
        </div>
      )}
    </article>
  )
}
