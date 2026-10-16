import { useEffect, useMemo, useState } from 'react'
import { useObservation } from '../../../preview/observation'
import { LazyEChart } from '../../../lib/LazyEChart'
import { reportCSV } from './model'
import { CreditVisuals, SectionBars } from './CreditVisuals'
import { SellCredits } from './SellCredits'
import { createSale, withSales, type LocalSale } from './sales'
import { CCP_CHECKLIST, SECTION_IDS, decisionReport, validateRequest, validateResponse, type VerificationRequest, type VerifierResponse } from './verification'
import { SnapshotStack } from './SnapshotStack'
import { conditionRevision, coverageChanges, getSnapshots, saveSnapshot, type OverviewSnapshot } from './snapshots'
import { SIMULATION_MS, simulateResponse, simulationStage } from './simulation'
import { VerificationMap } from './VerificationMap'
import '../../../preview/preview.css'
import './generator.css'

const REQUESTS = 'bcs-verifier-requests-v1', RESPONSES = 'bcs-verifier-responses-v1', SALES = 'bcs-carbon-local-sales-v1'
const fmt = (v: number) => v.toLocaleString('en-MY', { maximumFractionDigits: 2 })
function read<T>(key: string): T[] { const value: unknown = JSON.parse(localStorage.getItem(key) ?? '[]'); if (!Array.isArray(value)) throw new Error('Stored records could not be read.'); return value as T[] }
function save<T>(key: string, records: T[]) { localStorage.setItem(key, JSON.stringify(records)) }
function download(value: string, filename: string, type = 'application/json') { const url = URL.createObjectURL(new Blob([value], { type })); const a = document.createElement('a'); a.href = url; a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) }
export function Generator({ onEvidence }: { onEvidence: () => void }) {
  const { region, raster, sceneId, scenes, busy: observationBusy } = useObservation()
  const [requests, setRequests] = useState<VerificationRequest[]>(() => { try { return read<VerificationRequest>(REQUESTS).map(validateRequest) } catch { return [] } })
  const [responses, setResponses] = useState<VerifierResponse[]>(() => { try { return read<VerifierResponse>(RESPONSES) } catch { return [] } })
  const [sales, setSales] = useState<LocalSale[]>(() => { try { return read<LocalSale>(SALES) } catch { return [] } })
  const matching = requests.filter(r => r.lat === region.lat && r.lng === region.lng)
  const [snapshots, setSnapshots] = useState<OverviewSnapshot[]>([])
  const [snapshotError, setSnapshotError] = useState('')
  const [capturing, setCapturing] = useState(false)
  useEffect(() => { let active = true; getSnapshots(requests.flatMap(r => r.snapshot ? [r.snapshot.id] : [])).then(images => { if (active) { setSnapshots(images); setSnapshotError('') } }).catch(e => { if (active) setSnapshotError(String(e)) }); return () => { active = false } }, [requests])
  const [simulation, setSimulation] = useState(true)
  const [now, setNow] = useState(Date.now())
  const [requestId, setRequestId] = useState<string | null>(null)
  const request = matching.find(r => r.id === requestId) ?? matching[0] ?? null
  const response = useMemo(() => { if (!request) return null; const r = responses.find(r => r.requestId === request.id); if (!r) return null; try { return validateResponse(r, request) } catch { return null } }, [request, responses])
  const running = requests.some(r => r.simulation && !responses.some(s => s.requestId === r.id))
  useEffect(() => { if (!running) return; const timer = setInterval(() => setNow(Date.now()), 300); return () => clearInterval(timer) }, [running])
  useEffect(() => {
    const due = requests.filter(r => r.simulation && simulationStage(r, now) === 'complete' && !responses.some(s => s.requestId === r.id))
    if (!due.length) return
    try {
      const fresh = read<VerifierResponse>(RESPONSES)
      const generated = due.filter(r => !fresh.some(s => s.requestId === r.id)).map(r => simulateResponse(r, new Date().toISOString()))
      const updated = [...generated, ...fresh]; save(RESPONSES, updated); setResponses(updated)
    } catch (e) { setError(e instanceof Error ? e.message : 'Simulation failed; report could not be saved.') }
  }, [requests, responses, now])
  const stage = request?.simulation && !response ? simulationStage(request, now) : null
  const baseReport = request && response ? decisionReport(request, response) : null
  const report = baseReport ? withSales(baseReport, sales) : null
  const [selected, setSelected] = useState('C3')
  const [start, setStart] = useState(`${new Date().getFullYear()}-01-01`), [end, setEnd] = useState(`${new Date().getFullYear() + 1}-01-01`)
  const [verifier, setVerifier] = useState(''), [notes, setNotes] = useState('')
  const [reportText, setReportText] = useState(''), [error, setError] = useState(''), [message, setMessage] = useState('')
  const [scope, setScope] = useState('all')
  const select = (id: string) => { setSelected(id); setScope(report?.sections.some(s => s.id === id) ? id : 'all') }
  const image = useMemo(() => { if (!raster) return ''; const c = document.createElement('canvas'); c.width = raster.width; c.height = raster.height; c.getContext('2d')!.putImageData(new ImageData(new Uint8ClampedArray(raster.rgb), raster.width, raster.height), 0, 0); return c.toDataURL() }, [raster])
  async function submit() {
    if (capturing || running) return
    setError(''); setMessage(''); setCapturing(true)
    try {
      if (!image || !raster || observationBusy) throw new Error('Wait for the current satellite overview to finish loading before submitting a capture.')
      const created = new Date().toISOString(), id = crypto.randomUUID()
      const acquiredAt = scenes.find(s => s.id === sceneId)?.properties.datetime ?? ''
      const revision = simulation ? conditionRevision(matching) : 0
      const snapshot = { id, capturedAt: created, sceneId, acquiredAt, conditionRevision: revision }
      const r = validateRequest({ snapshot, simulation, version: 1, id, created, verifier, site: region.name, lat: region.lat, lng: region.lng, scene: sceneId, start, end, sections: [...SECTION_IDS], purpose: 'area-validation', scope: 'whole-farm', notes, framework: 'ICVCM Core Carbon Principles', status: 'pending' })
      await saveSnapshot({ id, capturedAt: created, sceneId, acquiredAt, image, width: raster.width, height: raster.height, lat: region.lat, lng: region.lng })
      const updated = [r, ...read<VerificationRequest>(REQUESTS)]
      save(REQUESTS, updated); setRequests(updated); setRequestId(r.id); setReportText(''); setScope('all')
      setNow(Date.now())
      setMessage(simulation ? 'Simulation request sent. Demo verifier processing will return a sample report automatically.' : 'Request saved as pending. Verifier is unassigned; no external delivery has occurred. No credits are assigned until a report is received.')
    } catch (e) { setError(e instanceof Error ? e.message : 'Request could not be saved.') } finally { setCapturing(false) }
  }
  function receive() {
    setError(''); setMessage('')
    try {
      if (!request) throw new Error('Submit a section request first.')
      const r = validateResponse(JSON.parse(reportText), request)
      const existing = responses.find(s => s.requestId === request.id)
      if (existing && r.sections.some(s => existing.sections.some(e => e.id === s.id))) throw new Error('A decision already exists for one of these sections. Submit a new request for a revision.')
      const combined = existing ? validateResponse({ ...r, reportReference: `${existing.reportReference}; ${r.reportReference}`, sections: [...existing.sections, ...r.sections] }, request) : r
      const updated = [combined, ...read<VerifierResponse>(RESPONSES).filter(s => s.requestId !== request.id)]
      save(RESPONSES, updated); setResponses(updated); setMessage('Report received. Only reported sections contribute credits. Report authenticity and registry issuance have not been validated.')
    } catch (e) { setError(e instanceof Error ? e.message : 'Report could not be received.') }
  }
  function sell(amount: number) {
    if (!baseReport) throw new Error('A verifier report is required first.')
    const fresh = read<LocalSale>(SALES), sale = createSale(withSales(baseReport, fresh), amount, crypto.randomUUID(), new Date().toISOString()), updated = [sale, ...fresh]
    save(SALES, updated); setSales(updated)
  }
  function undoSale(id: string) { const updated = read<LocalSale>(SALES).filter(s => s.id !== id); save(SALES, updated); setSales(updated) }
  const decision = response?.sections.find(s => s.id === selected), section = report?.sections.find(s => s.id === selected)
  const eligible = decision ? decision.mask.join('').split('').filter(c => c === '1').length : 0
  const claimedArea = decision ? decision.mask.join('').split('').filter(c => c === '2').length : 0
  const points = report?.timeline.map(p => { const s = report.sections.find(s => s.id === scope); if (!s) return p; const fraction = (Date.parse(p.date) - Date.parse(report.input.start)) / (report.days * 86400000); return { ...p, potential: s.potential * fraction, available: Math.max(0, s.potential * fraction - s.claimed) } }) ?? []
  const previousCapture = request ? matching.slice(matching.findIndex(r => r.id === request.id) + 1).find(r => r.snapshot && !!r.simulation === !!request.simulation && responses.some(s => s.requestId === r.id)) : undefined
  const previousResponse = previousCapture ? responses.find(s => s.requestId === previousCapture.id) : undefined
  const changes = previousResponse && response ? coverageChanges(previousResponse.sections, response.sections) : null
  const template = request ? { requestId: request.id, verifier: 'VERIFIER NAME', reportReference: 'REPORT REFERENCE', issuedAt: new Date().toISOString(), sections: request.sections.map(id => ({ id, mask: Array(10).fill('0000000000'), creditableTco2e: 0, claimedTco2e: 0, reason: 'Replace with the verifier decision and spatial eligibility mask.' })) } : null
  return <div className="mp cl"><div className="mp-content"><header className="mp-heading"><div><h1 className="page__title">Carbon Ledger</h1><p>Validate farm area → Automatically assess every sector → Deduct exclusions → Map creditable coverage</p></div><button onClick={onEvidence}>Evidence & original ledger ↗</button></header>
    <div className="cl-banner"><span className="mp-pill">{request?.simulation ? "SIMULATION · DEMO DATA" : "ICVCM · CCP blueprint"}</span><span>{request?.simulation ? "Simulated processing and results · no external verifier or issued credits" : "Verifier unassigned · pending areas earn no credits · no CCP certification claimed"}</span></div>
    <section className="cl-panel cl-verification-request"><header><h2>01 · Validate farm area</h2><span className="mp-pill">Whole farm · all 25 sectors</span></header><div className="cl-verification-form"><div className="cl-farm-scope"><h3>{region.name}</h3><div className="cl-live-capture">{image ? <img src={image} alt="Current overview to capture on next validation" /> : <span>Loading current overview…</span>}<span>Next capture · current observation<br />{scenes.find(s => s.id === sceneId)?.properties.datetime ? new Date(scenes.find(s => s.id === sceneId)!.properties.datetime).toLocaleString("en-MY", { timeZone: "Asia/Kuala_Lumpur" }) : "Awaiting imagery"}</span></div><strong>25 ha</strong><p>500 × 500 m study area · every sector assessed automatically</p><div className="cl-deduction-flow"><span>Entire farm</span><span>− Ineligible coverage</span><span>− Already-claimed coverage</span><span>= Unclaimed creditable area</span></div><p>This request validates credit eligibility. It does not purchase land or credits.</p></div><div><div className="cl-fields"><label>Verifier (leave blank)<input aria-label="Verifier" value={verifier} onChange={e => setVerifier(e.target.value)} placeholder="Unassigned" /></label><label>Start (inclusive)<input aria-label="Request start" type="date" value={start} onChange={e => setStart(e.target.value)} /></label><label>End (exclusive)<input aria-label="Request end" type="date" value={end} onChange={e => setEnd(e.target.value)} /></label></div><label>Evidence / request notes<textarea aria-label="Verification request notes" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Monitoring reports, prior claims and survey references" /></label><label className="cl-simulation-toggle"><input type="checkbox" aria-label="Simulate verifier processing" checked={simulation} onChange={e => setSimulation(e.target.checked)} />Simulate verifier processing · automatic demo report</label><button className="cl-primary" disabled={running || capturing || !image || !!observationBusy} onClick={submit}>{capturing ? "Capturing overview…" : running ? "Validating farm area…" : "Submit farm validation request"}</button><p>{simulation ? "Simulation: one farm request → all sectors assessed → automatic eligibility deductions → report in about 8 seconds." : "Saved locally as pending. No external verifier service connected."}</p></div></div>
    <details><summary>ICVCM Core Carbon Principles · evidence blueprint</summary><div className="cl-ccp-list">{CCP_CHECKLIST.map(([title, detail], i) => <div key={title}><b>{i + 1}. {title}</b><small>{detail}</small></div>)}</div><p>Reference checklist only. ICVCM assesses programmes and credit categories; this app does not issue a CCP label.</p><a href="https://icvcm.org/core-carbon-principles/" target="_blank" rel="noreferrer">Core Carbon Principles ↗</a> · <a href="https://icvcm.org/assessment-framework/" target="_blank" rel="noreferrer">Assessment Framework ↗</a></details></section>
    <SnapshotStack requests={matching} responses={responses} snapshots={snapshots} selectedId={request?.id} onSelect={id => { setRequestId(id); setScope("all"); setMessage(""); setError("") }} />
    {snapshotError && <p className="cl-error" role="alert">{snapshotError}</p>}
    {(message || error) && <div className="cl-panel">{message && <p role="status">{message}</p>}{error && <p role="alert" className="cl-error">{error}</p>}</div>}
    <section className="cl-panel"><header><h2>Request & report status</h2>{matching.length > 0 && <select aria-label="Verification request history" value={request?.id ?? ''} onChange={e => { setRequestId(e.target.value); setReportText(''); setScope('all'); setMessage(''); setError('') }}>{matching.map(r => <option key={r.id} value={r.id}>{r.id.slice(0, 8)} · {r.sections.length === 25 ? 'Whole farm · 25 sectors' : `${r.sections.length} sectors (earlier request)`} · {r.simulation ? 'SIM · ' : ''}{responses.some(s => s.requestId === r.id) ? 'Report received' : r.simulation ? 'Processing' : 'Pending'}</option>)}</select>}</header>{request?.simulation && <div className="cl-sim-status" role="status"><strong>{response ? '✓ Simulation complete · demo report received' : stage === 'sent' ? '↗ Request sent to simulated verifier' : stage === 'processing' ? '◌ Assessing all farm sectors…' : '◌ Checking eligibility and prior claims…'}</strong><progress aria-label="Simulation progress" max="100" value={response ? 100 : Math.min(98, Math.max(0, (now - Date.parse(request.created)) / SIMULATION_MS * 100))} /><small>Demo only · no external request or actual verification</small></div>}<div className="cl-flow-status"><span data-active={!!request}>① Request sent</span><span data-active={!!request && (!response || response.sections.length < request.sections.length)}>② {stage ? 'Processing' : 'Pending verifier'}</span><span data-active={!!response}>③ Report received</span><span data-active={!!report}>④ Credit coverage</span></div>{request ? <><p>Request {request.id} · {request.sections.length === 25 ? 'Whole farm · 25 sectors' : `${request.sections.length} sectors (earlier request)`} · {request.start} → {request.end} · Verifier: {request.verifier || 'Unassigned'}{response ? ` · Report: ${response.reportReference}` : ' · Awaiting report'}</p><div className="cl-actions"><button onClick={() => download(JSON.stringify({ ...request, overviewCapture: snapshots.find(s => s.id === request.snapshot?.id), spatialReference: { crs: 'EPSG:4326', centre: [request.lng, request.lat], extentMeters: [500, 500], sectionMeters: [100, 100], maskCellMeters: [10, 10], rows: 'north to south', columns: 'west to east' }, evidenceBlueprint: CCP_CHECKLIST }, null, 2), `verification-request-${request.id}.json`)}>Export request</button>{template && <button onClick={() => download(JSON.stringify(template, null, 2), `verifier-response-template-${request.id}.json`)}>Download report template</button>}</div>{!request.simulation && (!response || response.sections.length < request.sections.length) && <details><summary>{response ? "Receive remaining section decisions" : "Receive a verifier report"}</summary><p>Paste the matching JSON report. Each section needs a 10 × 10 mask: 1 = unclaimed creditable, 2 = already claimed, 0 = not creditable, north to south / west to east. Quantities are tCO₂e after verifier deductions. Omitted sections remain pending.</p><textarea className="cl-report-json" aria-label="Verifier report JSON" value={reportText} onChange={e => setReportText(e.target.value)} placeholder="Paste received verifier report JSON" /><button disabled={!reportText.trim()} onClick={receive}>Receive report</button></details>}{response && <p>Reported by {response.verifier}. {response.simulation ? "Simulated mask and quantities; no real verifier decision or CCP certification." : "Imported report authenticity is not validated; this is not registry issuance."}</p>}</> : <p>No validation requests yet. Submit one request for the entire farm to begin. Existing planning estimates do not establish eligibility.</p>}</section>
    <CreditVisuals report={report} reportMode saleControls={<SellCredits report={report} sales={sales} onSell={sell} onUndo={undoSale} />} />
    <div className="cl-main"><section className="cl-panel"><header><h2>02 · Captured overview · report coverage</h2><span className="mp-pill">{response ? `${response.simulation ? "SIM · " : ""}${response.sections.length}/${request!.sections.length} sections reported` : 'Awaiting verifier'}</span></header>{changes && changes.compared > 0 && <div className="cl-capture-change"><span>↑ {fmt(changes.gainedPct)}% newly creditable</span><span>↓ {fmt(changes.lostPct)}% no longer creditable</span><small>Compared with preceding capture · matched sectors only{request?.simulation ? ' · simulated change' : ''}</small></div>}<div className="cl-map-layout"><VerificationMap image={snapshots.find(s => s.id === request?.snapshot?.id)?.image ?? ""} request={request} response={response} selected={selected} onSelect={select} /><div className="cl-detail"><h3>Section {selected}</h3>{request?.snapshot ? <p>Captured {new Date(request.snapshot.capturedAt).toLocaleString("en-MY", { timeZone: "Asia/Kuala_Lumpur" })}</p> : <p>Earlier request: no archived image.</p>}{decision && section ? <><div className="cl-coverage-bar"><i style={{ width: `${eligible}%`, background: '#24cd8b' }} /><i style={{ width: `${claimedArea}%`, background: "#efbb54" }} /><i className="cl-ineligible-swatch" style={{ width: `${100 - eligible - claimedArea}%` }} /></div><div className="cl-coverage-values"><span>{eligible}% unclaimed creditable</span><span>{claimedArea}% already claimed</span><span>{100 - eligible - claimedArea}% not creditable</span></div><strong className="cl-big">{fmt(section.available)}<small>tCO₂e unclaimed</small></strong><p>{decision.reason}</p><p>{fmt(section.claimed)} tCO₂e claimed / locally sold</p></> : <><span className="mp-pill mp-amber">{request?.sections.includes(selected) ? 'Pending verification' : 'Not assessed'}</span><p>No credit eligibility assigned.</p><p>The next farm validation request will include this sector automatically.</p></>}<a href="#/twin">Explore Digital Twin ↗</a></div></div></section>
    <section className="cl-panel"><header><div><h2>Cumulative carbon credits</h2><p>{report ? `${report.input.start} → ${report.input.end}` : 'Awaiting verifier report'}</p></div><select aria-label="Graph section" value={scope} onChange={e => setScope(e.target.value)}><option value="all">Reported sections</option>{report?.sections.map(s => <option key={s.id} value={s.id}>{s.id}</option>)}</select></header>{report ? <><LazyEChart height={260} option={{ tooltip: { trigger: 'axis' }, legend: { top: 0 }, grid: { left: 55, right: 15, top: 45, bottom: 35 }, xAxis: { type: 'category', data: points.map(p => p.date) }, yAxis: { type: 'value', name: 'tCO₂e' }, series: [{ name: 'Report quantity', type: 'line', data: points.map(p => +p.potential.toFixed(4)), symbol: 'none', lineStyle: { type: 'dashed' } }, { name: 'Unclaimed', type: 'line', data: points.map(p => +p.available.toFixed(4)), symbol: 'none', areaStyle: { opacity: .1 } }] }} /><p>Illustrative constant-rate distribution of report quantities, not a measured issuance timeline.</p></> : <div className="cl-empty">Pending sections contribute no credits.</div>}</section></div>
    <SectionBars report={report} selected={selected} onSelect={select} />
    {report && request && response && <section className="cl-panel"><header><h2>Report exports</h2><div className="cl-actions"><button onClick={() => download(reportCSV(report), `carbon-${request.id}.csv`, 'text/csv;charset=utf-8')}>Download CSV</button><button onClick={() => download(JSON.stringify({ snapshot: snapshots.find(s => s.id === request.snapshot?.id), request, verifierReport: response, accounting: report, localSales: sales }, null, 2), `carbon-${request.id}.json`)}>Download report JSON</button><button onClick={() => window.print()}>Print / PDF</button></div></header><p>Values originate from the received report; local sales are deducted separately. Prior planning snapshots are retained in browser storage and do not count as verification.</p></section>}
  </div></div>
}
