// Carbon Ledger (design §26): totals, the evidence checklist of the selected plan, per-zone Verified eligibility,
// the hash-chained records and a record's detail. Live: ledger.appended, ledger.verified and plan.updated.
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { Button, Chip } from '@bcs/ui'
import type { CarbonSummary, ChainVerification, CoverageGap, EvidenceChecklist, LedgerRecord, PlanSummary, ZoneEligibility } from '@bcs/api-types'
import { api } from '../../data/client'
import { apiErrorText, networkErrorText } from '../../data/apiError'
import { onLiveEvent } from '../../data/live'
import { useAppStore } from '../../data/store'
import { useZoneLabels } from '../SatelliteIntel/shared'
import { Checklist } from './Checklist'
import { EligibilityTracker } from './EligibilityTracker'
import { RecordDetail } from './RecordDetail'
import { RecordsList } from './RecordsList'
import { Summary } from './Summary'
import { DISCLAIMER, isNoCoverage } from './format'

/** Eligibility is evaluated by the Ground Station when asked (the sensor window runs in demo time). */
export const ELIGIBILITY_POLL_MS = 5000

/** The plan to show by default: the newest applied one (the list is newest first), else the newest. */
export function defaultPlan(plans: PlanSummary[]): string | null {
  return (plans.find((p) => p.status === 'applied') ?? plans[0])?.plan_id ?? null
}

function EvidenceLedger() {
  const zoneLabel = useZoneLabels()
  const connection = useAppStore((s) => s.system.connection)
  const [summary, setSummary] = useState<CarbonSummary | null>(null)
  const [records, setRecords] = useState<LedgerRecord[]>([])
  const [plans, setPlans] = useState<PlanSummary[]>([])
  const [planId, setPlanId] = useState<string | null>(null)
  const [checklist, setChecklist] = useState<EvidenceChecklist | null>(null)
  const [eligibility, setEligibility] = useState<ZoneEligibility[]>([])
  const [gaps, setGaps] = useState<CoverageGap[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [chain, setChain] = useState<ChainVerification | null>(null)
  const [busy, setBusy] = useState(false)
  const [genError, setGenError] = useState<string | null>(null)
  const [verifying, setVerifying] = useState(false)
  const [verifyError, setVerifyError] = useState<string | null>(null)
  const planIdRef = useRef<string | null>(null)
  planIdRef.current = planId
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const loadSummary = useCallback(async () => {
    const r = await api.GET('/api/v1/carbon/summary')
    if (alive.current && r.data) setSummary(r.data)
  }, [])
  const loadRecords = useCallback(async () => {
    const r = await api.GET('/api/v1/ledger/records')
    if (alive.current && r.data) setRecords(r.data)
  }, [])
  const loadEligibility = useCallback(async () => {
    const r = await api.GET('/api/v1/ledger/eligibility')
    if (!alive.current || !r.data) return
    setEligibility(r.data)
    if (r.data.some((z) => isNoCoverage(z.sensors))) {
      const c = await api.GET('/api/v1/coverage')
      if (alive.current && c.data) setGaps(c.data.gaps)
    }
  }, [])
  const loadChecklist = useCallback(async () => {
    const id = planIdRef.current
    if (!id) {
      setChecklist(null)
      return
    }
    const r = await api.GET('/api/v1/ledger/checklist', { params: { query: { plan_id: id } } })
    if (alive.current && planIdRef.current === id && r.data) setChecklist(r.data)
  }, [])
  const loadPlans = useCallback(async () => {
    const r = await api.GET('/api/v1/plans')
    if (!alive.current || !r.data) return
    const list = r.data
    setPlans(list)
    // Keep the operator's choice while it exists; otherwise the newest applied plan.
    setPlanId((cur) => (cur && list.some((p) => p.plan_id === cur) ? cur : defaultPlan(list)))
  }, [])

  const refreshAll = useCallback(() => {
    const quiet = () => undefined
    loadSummary().catch(quiet)
    loadRecords().catch(quiet)
    loadEligibility().catch(quiet)
    loadPlans().catch(quiet)
    loadChecklist().catch(quiet)
  }, [loadSummary, loadRecords, loadEligibility, loadPlans, loadChecklist])

  // Snapshot on mount and after every reconnect.
  useEffect(() => {
    refreshAll() // on mount and whenever the connection state changes
  }, [connection, refreshAll])

  useEffect(() => {
    loadChecklist().catch(() => undefined)
  }, [planId, loadChecklist])

  useEffect(() => {
    const quiet = () => undefined
    return onLiveEvent((e) => {
      if (e.type === 'ledger.appended') {
        loadRecords().catch(quiet)
        loadSummary().catch(quiet)
        loadEligibility().catch(quiet)
        loadChecklist().catch(quiet)
      } else if (e.type === 'ledger.verified') {
        setChain(e.data as ChainVerification)
        loadRecords().catch(quiet)
        loadEligibility().catch(quiet)
      } else if (e.type === 'plan.updated') {
        loadPlans().catch(quiet)
        loadChecklist().catch(quiet)
      }
    })
  }, [loadRecords, loadSummary, loadEligibility, loadChecklist, loadPlans])

  useEffect(() => {
    const t = setInterval(() => loadEligibility().catch(() => undefined), ELIGIBILITY_POLL_MS)
    return () => clearInterval(t)
  }, [loadEligibility])

  const generate = async () => {
    if (!planId || busy) return
    setBusy(true)
    setGenError(null)
    try {
      const r = await api.POST('/api/v1/ledger/projected', { body: { plan_id: planId } })
      if (r.data) {
        setSelected(r.data.record_id)
        await Promise.all([loadRecords(), loadSummary(), loadEligibility(), loadChecklist()])
      } else {
        setGenError(apiErrorText(r.error, 'The Projected record could not be created.'))
        loadChecklist().catch(() => undefined)
      }
    } catch (e) {
      setGenError(networkErrorText(e))
    }
    setBusy(false)
  }

  const verify = async () => {
    setVerifying(true)
    setVerifyError(null)
    try {
      const r = await api.POST('/api/v1/ledger/verify')
      if (r.data) {
        setChain(r.data)
        await Promise.all([loadRecords(), loadEligibility()])
      } else setVerifyError(apiErrorText(r.error, 'The chain could not be verified.'))
    } catch (e) {
      setVerifyError(networkErrorText(e))
    }
    setVerifying(false)
  }

  const record = records.find((r) => r.record_id === selected) ?? null

  return (
    <div className="net-page ledger-page">
      <div className="net-page__col ledger-page__left">
        <header className="sat-header">
          <h1 className="page__title">Carbon Ledger</h1>
          <div className="sat-header__chips">
            <Chip title="Records are tamper-evident demo records">{DISCLAIMER}</Chip>
          </div>
        </header>
        <div className="row-actions ledger-verify">
          <Button onClick={verify} disabled={verifying}>
            Verify chain
          </Button>
          <span className="ledger-chain bcs-mono" data-testid="chain-status" data-intact={chain ? String(chain.intact) : ''} role="status">
            {chain
              ? chain.intact
                ? `Chain intact · ${chain.checked} record${chain.checked === 1 ? '' : 's'} checked`
                : `Chain broken at index ${chain.first_broken_index}`
              : 'Chain not verified yet'}
          </span>
        </div>
        {verifyError && (
          <p className="form-error" role="alert">
            {verifyError}
          </p>
        )}
        <RecordsList records={records} selectedId={selected} onSelect={setSelected} />
        <RecordDetail record={record} zoneLabel={zoneLabel} />
      </div>
      <div className="net-page__col ledger-page__right">
        <Summary summary={summary} />
        <Checklist
          plans={plans}
          planId={planId}
          onSelectPlan={setPlanId}
          checklist={checklist}
          busy={busy}
          error={genError}
          onGenerate={generate}
        />
        <EligibilityTracker zones={eligibility} zoneLabel={zoneLabel} gaps={gaps} />
      </div>
    </div>
  )
}

const Generator = lazy(() => import('./generator/Generator').then(m => ({ default: m.Generator })))

export function CarbonLedger() {
  const [evidence, setEvidence] = useState(false)
  return evidence ? <><div className="cl-evidence-return"><Button onClick={() => setEvidence(false)}>← Credit generator</Button></div><EvidenceLedger /></> : <Suspense fallback={<div className="stage-loading">Loading credit generator…</div>}><Generator onEvidence={() => setEvidence(true)} /></Suspense>
}
