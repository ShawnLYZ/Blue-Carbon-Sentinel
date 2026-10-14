import { expect, test, type APIRequestContext } from '@playwright/test'
import { clearCritical, raiseCritical, reconnectNodes, seedProjectedRecord, waitForNodes } from './seed'

test.describe.configure({ timeout: 180_000 })

interface AlertRow { id: string; type: string; node_id?: string | null; message: string; occurrences: number; acknowledged_at?: string | null }

async function alerts(request: APIRequestContext): Promise<AlertRow[]> {
  return (await (await request.get('/api/v1/alerts?limit=200')).json()) as AlertRow[]
}

/**
 * The test stack has no camera, so the Ground Station raises a critical `camera_offline` alert ("no frames
 * for 3 s") when the camera link first goes offline, which a reset right after startup catches (a later reset
 * sees no transition, so none is raised). That is expected: wait for it when it is coming, then acknowledge
 * everything through the API so each test starts with no open alerts.
 */
async function settleAlerts(request: APIRequestContext): Promise<void> {
  await expect
    .poll(async () => (await alerts(request)).some((a) => a.type === 'camera_offline'), { timeout: 10_000 })
    .toBe(true)
    .catch(() => undefined) // no transition this time: nothing to wait for
  for (const a of await alerts(request)) if (!a.acknowledged_at) await request.post(`/api/v1/alerts/${a.id}/ack`)
  expect((await alerts(request)).filter((a) => !a.acknowledged_at)).toHaveLength(0)
}

test.beforeEach(async ({ request }) => {
  await waitForNodes(request)
  await clearCritical(request, 'WQ-02')
  expect((await request.post('/api/v1/test/reset')).ok()).toBeTruthy()
  await reconnectNodes(request) // the reset leaves the nodes with keys the simulator does not know
  await settleAlerts(request)
})
test.afterAll(async ({ request }) => {
  await clearCritical(request, 'WQ-02')
})

test('critical alert toasts once on any page and can be acknowledged', async ({ page, request }) => {
  await page.goto('/#/ledger')
  const log = page.getByTestId('toast-log')
  await expect(log).toBeAttached()
  await expect(page.getByTestId('alert-bell-count')).toHaveText('0')

  await raiseCritical(request, 'node_offline', 'WQ-02')
  const wq02 = (await alerts(request)).find((a) => a.type === 'node_offline' && a.node_id === 'WQ-02')!
  await expect(log).toHaveAttribute('data-shown', new RegExp(wq02.id))
  await raiseCritical(request, 'node_offline', 'WQ-02')

  // The second offline transition was folded into the same alert (dedupe), not a new one ...
  const after = (await alerts(request)).filter((a) => a.type === 'node_offline' && a.node_id === 'WQ-02')
  expect(after.map((a) => a.id)).toEqual([wq02.id])
  expect(after[0]!.occurrences).toBeGreaterThanOrEqual(2)
  // ... and this alert ID was toasted exactly once over both raises, whether or not the toast was dismissed.
  const shown = ((await log.getAttribute('data-shown')) ?? '').split(',').filter(Boolean)
  expect(shown.filter((id) => id === wq02.id)).toHaveLength(1)

  await page.goto('/#/command')
  const item = page.locator('[data-testid="alert-feed"] li', { hasText: 'WQ-02 offline' })
  await expect(item).toContainText('×')
  await item.getByRole('button', { name: 'Acknowledge' }).click()
  await expect(item).toHaveAttribute('data-acked', 'true')

  // Whatever else is still open (a camera_offline that recurs after the acknowledgement above) is
  // acknowledged one by one in the UI; the bell must then read 0.
  const others = (await alerts(request)).filter((a) => !a.acknowledged_at)
  for (const a of others) {
    expect(a.type).toBe('camera_offline')
    await page.locator('[data-testid="alert-feed"] li', { hasText: a.message }).first().getByRole('button', { name: 'Acknowledge' }).click()
  }
  await expect(page.getByTestId('alert-bell-count')).toHaveText('0')
})

test('command center shows the KPI tiles with units and sources', async ({ page }) => {
  await page.goto('/#/command')
  await expect(page.getByTestId('kpi-network')).toContainText('/8')
  await expect(page.getByTestId('kpi-health')).toHaveAttribute('title', /NDVI-proxy/)
  await expect(page.getByTestId('kpi-risks')).toHaveAttribute('title', /60 and above/)
  await expect(page.getByTestId('kpi-carbon-stock')).toHaveAttribute('title', /\/carbon\/summary/)
  await expect(page.getByTestId('kpi-verified')).toHaveAttribute('title', /Demo credits only/)
  await expect(page.getByTestId('kpi-water')).toBeVisible()
})

test('planned sites are marked not yet monitored and explain why', async ({ page }) => {
  await page.goto('/#/command')
  await page.getByTestId('site-marker-KKP').click()
  const card = page.getByTestId('site-card')
  await expect(card).toContainText('planned — not yet monitored')
  await expect(card).toContainText('Straits of Malacca')
  await page.getByTestId('site-marker-KCH').click()
  await expect(card).toContainText('carbon-dense baselines')
  await expect(page.getByTestId('site-marker-KSL')).toContainText('live')
})

test('carbon KPI tiles show values from the ledger', async ({ page, request }) => {
  await seedProjectedRecord(request)
  await page.goto('/#/command')
  await expect(page.getByTestId('kpi-carbon-stock')).toContainText('tCO₂e')
  await expect(page.getByTestId('kpi-carbon-stock')).not.toContainText('—')
  await expect(page.getByTestId('kpi-verified')).toContainText('0.000')
})
