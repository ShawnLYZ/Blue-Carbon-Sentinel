import { expect, type APIRequestContext } from '@playwright/test'

/**
 * Clears the store, seeds an evidence-grade baseline (KSL-B3 canopy 60 %), sets it as the baseline,
 * then seeds a capture with 15 pp canopy loss in KSL-B3 (above the 10 pp threshold, so B3 is flagged).
 * Numbers only: seeded captures have no media.
 */
export async function seedBaselineAndFlag(request: APIRequestContext): Promise<void> {
  expect((await request.post('/api/v1/test/reset')).ok()).toBeTruthy()
  const base = await request.post('/api/v1/test/seed/capture', {
    data: { zone_metrics: { 'KSL-B3': { canopy_pct: 60 } }, evidence_grade: true },
  })
  expect(base.status()).toBe(201)
  const { id } = (await base.json()) as { id: string }
  expect((await request.post('/api/v1/baseline', { data: { capture_id: id } })).ok()).toBeTruthy()
  const flagged = await request.post('/api/v1/test/seed/capture', {
    data: { zone_metrics: { 'KSL-B3': { canopy_pct: 45, canopy_loss_pp: 15 } }, evidence_grade: true },
  })
  expect(flagged.status()).toBe(201)
}

/**
 * Clears the store, then seeds a baseline and a flagged capture for `zoneId` (15 pp canopy loss),
 * and waits until the flag's AI assessment is stored. In test mode the AI answers with the rules tier.
 */
export async function seedFlagAndAssessment(request: APIRequestContext, zoneId: string): Promise<void> {
  expect((await request.post('/api/v1/test/reset')).ok()).toBeTruthy()
  const base = await request.post('/api/v1/test/seed/capture', {
    data: { zone_metrics: { [zoneId]: { canopy_pct: 60 } }, evidence_grade: true },
  })
  expect(base.status()).toBe(201)
  const { id } = (await base.json()) as { id: string }
  expect((await request.post('/api/v1/baseline', { data: { capture_id: id } })).ok()).toBeTruthy()
  const flagged = await request.post('/api/v1/test/seed/capture', {
    data: { zone_metrics: { [zoneId]: { canopy_pct: 45, canopy_loss_pp: 15 } }, evidence_grade: true },
  })
  expect(flagged.status()).toBe(201)
  await expect
    .poll(
      async () => {
        const r = await request.get(`/api/v1/zones/${zoneId}/assessments?limit=5`)
        if (!r.ok()) return false
        const list = (await r.json()) as { narrative: string; root_causes: unknown[] }[]
        return list.some((a) => a.narrative.length > 0 && a.root_causes.length > 0)
      },
      { timeout: 20_000 },
    )
    .toBe(true)
}

async function simBase(request: APIRequestContext): Promise<string> {
  const cfg = (await (await request.get('/api/v1/system/config')).json()) as { sim_url?: string }
  return String(cfg.sim_url ?? 'http://127.0.0.1:8701').replace(/\/+$/, '')
}

interface AlertRow { type: string; node_id?: string | null; occurrences: number; severity: string }

async function nodeAlert(request: APIRequestContext, type: string, node: string): Promise<AlertRow | undefined> {
  const r = await request.get('/api/v1/alerts?limit=200')
  if (!r.ok()) return undefined
  return ((await r.json()) as AlertRow[]).find((a) => a.type === type && a.node_id === node)
}

/** Waits until the stack's startup commissioning registered all 8 nodes. */
export async function waitForNodes(request: APIRequestContext): Promise<void> {
  // A cold stack is still auto-commissioning at startup; a reset in the middle of it loses nodes.
  await expect
    .poll(async () => ((await (await request.get('/api/v1/nodes')).json()) as unknown[]).length, { timeout: 60_000 })
    .toBe(8)
}

/**
 * `POST /test/reset` re-commissions the nodes with fresh keys that the simulator does not know, so every
 * node stays `unknown` ("broker refused the connection"). Regenerating a key re-provisions the simulator
 * for that node; this does it for all of them and waits until they report online again.
 */
export async function reconnectNodes(request: APIRequestContext): Promise<void> {
  const list = async () => (await (await request.get('/api/v1/nodes')).json()) as { id: string; status: string }[]
  await expect.poll(async () => (await list()).length, { timeout: 30_000 }).toBe(8)
  const nodes = await list()
  for (const n of nodes) expect((await request.post(`/api/v1/nodes/${n.id}/regenerate-key`)).ok()).toBeTruthy()
  await expect
    .poll(
      async () => (await list()).filter((n) => n.status === 'online').length,
      { timeout: 60_000 },
    )
    .toBe(nodes.length)
}

/** Clears the simulator faults `raiseCritical` injects (best effort; the simulator keeps its world between tests). */
export async function clearCritical(request: APIRequestContext, node: string): Promise<void> {
  try {
    await request.fetch(`${await simBase(request)}/api/v1/nodes/${node}/faults/offline`, { method: 'DELETE' })
  } catch {
    // simulator not listening: nothing to clear
  }
}

/**
 * Makes the simulator's `offline` fault fire for `node`, which the Ground Station turns into a critical
 * `node_offline` alert (there is no fake alert route). Each call first clears the fault, so a second call
 * is a fresh offline transition that the alert service must dedupe (occurrences up), then injects it and
 * waits until the alert exists (first call) or its `occurrences` grew (later calls).
 */
export async function raiseCritical(request: APIRequestContext, type: 'node_offline', node: string): Promise<void> {
  const sim = await simBase(request)
  const before = (await nodeAlert(request, type, node))?.occurrences ?? 0
  if (before > 0) {
    await request.fetch(`${sim}/api/v1/nodes/${node}/faults/offline`, { method: 'DELETE' })
    // let the node come back online, so the next fault is a new offline transition
    await expect
      .poll(async () => (await (await request.get(`/api/v1/nodes/${node}`)).json()).status, { timeout: 60_000 })
      .toBe('online')
  }
  const inj = await request.fetch(`${sim}/api/v1/nodes/${node}/faults`, { method: 'POST', data: { kind: 'offline' } })
  expect(inj.ok(), `inject offline fault: ${inj.status()} ${await inj.text()}`).toBeTruthy()
  await expect.poll(async () => (await nodeAlert(request, type, node))?.occurrences ?? 0, { timeout: 60_000 }).toBeGreaterThan(before)
}

/**
 * Clears the store, seeds an evidence-grade baseline and waits for the one-off AI history generation
 * (background priority, rules tier in test mode) to be stored.
 */
export async function seedBaseline(request: APIRequestContext): Promise<void> {
  expect((await request.post('/api/v1/test/reset')).ok()).toBeTruthy()
  const base = await request.post('/api/v1/test/seed/capture', {
    data: { zone_metrics: { 'KSL-B3': { canopy_pct: 60 } }, evidence_grade: true },
  })
  expect(base.status()).toBe(201)
  const { id } = (await base.json()) as { id: string }
  expect((await request.post('/api/v1/baseline', { data: { capture_id: id } })).ok()).toBeTruthy()
  await expect
    .poll(
      async () => {
        const r = await request.get('/api/v1/history')
        if (!r.ok()) return 0
        return Object.keys(((await r.json()) as { series: Record<string, unknown> }).series).length
      },
      { timeout: 30_000 },
    )
    .toBeGreaterThan(0)
}

/**
 * Clears the store and seeds a scene Time Travel can forecast from: an evidence-grade baseline (every
 * zone at the seeding defaults, KSL-B3 canopy 60 %) and a flagged evidence-grade capture where KSL-B3 lost
 * 15 pp of canopy to mud (30 % mud, so planting validates there). Test-mode seeded captures carry
 * synthetic image, class and height media (ruling R22a), so future textures render too.
 */
export async function seedReadyScene(request: APIRequestContext): Promise<void> {
  expect((await request.post('/api/v1/test/reset')).ok()).toBeTruthy()
  const base = await request.post('/api/v1/test/seed/capture', {
    data: { zone_metrics: { 'KSL-B3': { canopy_pct: 60, mud_pct: 15 } }, evidence_grade: true },
  })
  expect(base.status()).toBe(201)
  const { id } = (await base.json()) as { id: string }
  expect((await request.post('/api/v1/baseline', { data: { capture_id: id } })).ok()).toBeTruthy()
  const flagged = await request.post('/api/v1/test/seed/capture', {
    data: { zone_metrics: { 'KSL-B3': { canopy_pct: 45, mud_pct: 30, canopy_loss_pp: 15 } }, evidence_grade: true },
  })
  expect(flagged.status()).toBe(201)
}

/**
 * Seeds a ready scene, proposes a plan (AI, rules tier in test mode), applies it and waits until the forecast
 * run for the applied version is ready. Returns the plan ID. All through the public API (no extra test route).
 */
export async function seedAppliedPlanScene(request: APIRequestContext): Promise<string> {
  await waitForNodes(request) // a cold stack is still commissioning; a reset in the middle of it loses nodes
  await seedReadyScene(request)
  const proposed = await request.post('/api/v1/plans/propose', { data: { zone_ids: ['KSL-B3'] } })
  expect(proposed.status()).toBe(202)
  const { request_id: planId } = (await proposed.json()) as { request_id: string }
  await expect.poll(async () => (await request.get(`/api/v1/plans/${planId}`)).status(), { timeout: 30_000 }).toBe(200)
  // The rules tier may propose nothing: plant Avicennia in KSL-B3 (mud, covered by WQ-01) so the plan has a zone.
  const edited = await request.put(`/api/v1/plans/${planId}`, {
    data: {
      items: [
        {
          zone_id: 'KSL-B3',
          interventions: [{ kind: 'plant_avicennia', sapling_count: 400, planted_area_ha: 0.2 }],
          priority: 1,
          rationale: 'E2E seed',
          expected_uplift: { canopy_pp_2035: 0, tco2e_2035: 0 },
        },
      ],
    },
  })
  expect(edited.ok(), `edit plan: ${edited.status()} ${await edited.text()}`).toBeTruthy()
  const applied = await request.post(`/api/v1/plans/${planId}/apply`, { data: {} })
  expect(applied.ok(), `apply plan: ${applied.status()} ${await applied.text()}`).toBeTruthy()
  const { forecast_id: forecastId } = (await applied.json()) as { forecast_id: string }
  await expect
    .poll(async () => ((await (await request.get(`/api/v1/forecasts/${forecastId}`)).json()) as { status: string }).status, { timeout: 30_000 })
    .toBe('ready')
  return planId
}

/** An applied plan scene plus its Projected record (created through the ledger route). */
export async function seedProjectedRecord(request: APIRequestContext): Promise<string> {
  const planId = await seedAppliedPlanScene(request)
  const r = await request.post('/api/v1/ledger/projected', { data: { plan_id: planId } })
  expect(r.ok(), `projected: ${r.status()} ${await r.text()}`).toBeTruthy()
  return ((await r.json()) as { record_id: string }).record_id
}

/** Creates a manual task for `zoneId` (its covering nodes) through the public API; returns the task id. */
export async function createManualTask(request: APIRequestContext, zoneId: string): Promise<string> {
  const res = await request.post('/api/v1/tasks', { data: { zone_id: zoneId, reason: 'e2e manual task' } })
  expect(res.ok()).toBeTruthy()
  return ((await res.json()) as { id: string }).id
}
