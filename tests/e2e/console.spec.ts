import { expect, test, type APIRequestContext } from '@playwright/test'
import { reconnectNodes } from './seed'

// Layout facts (controller ruling for Task 13): with no capture, the test-mode Ground Station
// auto-commissions the deterministic fallback layout (seed 0). There WQ-01 sits at (262.5, 262.5) and is
// the node that reaches B3 (WQ-02 is at the E1 corner), WQ-03 sits inside E5, and no WQ or SP node
// reaches A3. Hence B3 -> WQ-01 and A3 as the uncovered zone.
const B3_NODE = 'WQ-01'
const UNCOVERED_ZONE = 'A3'

async function simUrl(request: APIRequestContext): Promise<string> {
  const cfg = await (await request.get('/api/v1/system/config')).json()
  return String(cfg.sim_url ?? 'http://127.0.0.1:8701').replace(/\/+$/, '')
}

/**
 * The simulator keeps its world between tests: clear what these tests change. Best effort: Playwright's
 * readiness check is the Ground Station, so on a fresh stack the simulator may still be starting.
 */
async function resetSim(request: APIRequestContext) {
  const sim = await simUrl(request)
  const calls: [string, string][] = [
    ...['B3', UNCOVERED_ZONE].map((z): [string, string] => ['DELETE', `/zones/${z}/scenario`]),
    ['DELETE', '/nodes/SP-01/faults/malformed'],
    ['POST', '/replay/stop'],
    ['POST', '/recording/stop'], // 409 when none is running; fine
  ]
  for (const [method, path] of calls) {
    try {
      await request.fetch(`${sim}/api/v1${path}`, { method })
    } catch {
      // simulator not listening yet: nothing to reset
    }
  }
}

// Earlier specs reset the store, which leaves the nodes with keys the simulator does not know (only some
// reconnect by themselves): this spec needs all 8 online and sending packets.
test.beforeAll(async ({ request }) => {
  test.setTimeout(120_000) // re-keying the nodes can take a minute
  await reconnectNodes(request)
})
test.beforeEach(async ({ request }) => {
  await resetSim(request)
})
test.afterAll(async ({ request }) => {
  await resetSim(request)
})

test('console loads at /console/ with watermark and simulator status', async ({ page }) => {
  await page.goto('/console/')
  await expect(page.getByText('SIMULATED HARDWARE')).toBeVisible()
  await expect(page.getByTestId('sim-status')).toContainText(/Simulator: (online|offline)/)
})

test('console shows the simulator online and every region', async ({ page }) => {
  await page.goto('/console/')
  await expect(page.getByTestId('sim-status')).toContainText('Simulator: online')
  for (const id of ['minimap', 'nodes', 'scenarios', 'nature', 'lifecycle', 'inspector']) {
    await expect(page.getByTestId(`region-${id}`)).toBeVisible()
  }
})

test('console degrades to offline when the simulator is unreachable', async ({ page }) => {
  await page.route('**/api/v1/state', (r) => r.abort())
  await page.goto('/console/')
  await expect(page.getByTestId('sim-status')).toContainText('Simulator: offline')
  await expect(page.getByText('SIMULATED HARDWARE')).toBeVisible()
})

test('every node card is labelled SIMULATED and the mini-map never shows a substitute image', async ({ page }) => {
  await page.goto('/console/')
  const cards = page.getByTestId(/^node-card-/)
  await expect(cards).toHaveCount(8)
  for (const card of await cards.all()) await expect(card).toContainText('SIMULATED')
  const pins = page.getByTestId(/^marker-/)
  await expect(pins).toHaveCount(8)
  for (const pin of await pins.all()) await expect(pin.locator('.marker__meta')).toContainText('SIMULATED ·')
  // Test mode runs with --no-camera: no live raster, so the dark grid square says so.
  await expect(page.getByTestId('minimap-no-frame')).toHaveText('no camera frame')
  await expect(page.getByTestId('region-minimap').locator('img')).toHaveCount(0)
})

test(`scenario on B3 moves ${B3_NODE} turbidity within a second`, async ({ page }) => {
  await page.goto('/console/')
  const card = page.getByTestId(`node-card-${B3_NODE}`)
  const before = Number(await card.getByTestId('val-turbidity_ntu').innerText())
  await page.getByLabel('Ramp time (s)').fill('1')
  await page.getByTestId('zone-B3').click()
  await page.getByRole('button', { name: 'Sediment runoff' }).click()
  await expect
    .poll(async () => Number(await card.getByTestId('val-turbidity_ntu').innerText()), { timeout: 3000 })
    .toBeGreaterThan(before + 20)
})

test('uncovered zone shows no-node warning', async ({ page }) => {
  await page.goto('/console/')
  await page.getByLabel('Ramp time (s)').fill('1')
  await page.getByTestId(`zone-${UNCOVERED_ZONE}`).click()
  await page.getByRole('button', { name: 'Sediment runoff' }).click()
  await expect(page.getByText(`no node in range of ${UNCOVERED_ZONE}`)).toBeVisible()
})

test('fault toggle and inspector show invalid packets', async ({ page }) => {
  // Malformed affects the next telemetry sample; baseline sampling is every 30 s (demo time).
  test.setTimeout(75_000)
  await page.goto('/console/')
  await page.getByTestId('node-card-SP-01').getByRole('switch', { name: 'Malformed' }).click()
  await expect(page.getByTestId('node-card-SP-01').getByRole('switch', { name: 'Malformed' })).toBeChecked()
  await page.getByTestId('inspector-filter-invalid').click()
  await expect(page.getByTestId('packet-row').first()).toContainText('SP-01', { timeout: 45_000 })
})

test('record then replay is labelled simulated replay', async ({ page }) => {
  await page.goto('/console/')
  await page.getByRole('button', { name: 'Record' }).click()
  await page.waitForTimeout(5000)
  await page.getByRole('button', { name: 'Stop' }).click()
  await page.getByTestId('session-row').first().getByRole('button', { name: 'Replay' }).click()
  await expect(page.getByTestId('replay-banner')).toHaveText('REPLAY · SIMULATED')
})
