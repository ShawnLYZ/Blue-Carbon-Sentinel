import { expect, test, type Page } from '@playwright/test'
import { seedReadyScene } from './seed'

// Test-mode stack: the forecast parameters come from the rules tier, and the illustrator is disabled
// (it raises "unavailable"), so every illustration ends failed and only the code-only repaint shows.
// Without a real MAPBOX_TOKEN the two maps show "Map unavailable"; numbers, slider, plan editor, zone
// grid and the texture preload work without them.

/** Runs a forecast from the page and waits for its numbers (ruling R12). */
async function runForecast(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Run forecast' }).click()
  await expect(page.getByTestId('numbers-without')).toContainText('tCO₂e', { timeout: 30_000 })
  await expect(page.getByTestId('numbers-with')).toContainText('tCO₂e')
}

/** Waits until every future texture and height has loaded (or the illustrations are terminal and the one retry ran). */
async function waitForPreload(page: Page): Promise<void> {
  await expect(page.getByTestId('futures-preload')).toHaveAttribute('data-settled', 'true', { timeout: 30_000 })
}

test('slider updates numbers under both maps', async ({ page, request }) => {
  await seedReadyScene(request); await page.goto('/#/time-travel')
  await runForecast(page)
  const without2026 = await page.getByTestId('numbers-without').innerText()
  await page.getByRole('slider', { name: 'Year' }).fill('2035')
  // innerText on both sides: the labels are upper-cased by CSS, which textContent would not show.
  await expect(page.getByTestId('numbers-without')).not.toHaveText(without2026, { useInnerText: true })
  await expect(page.getByTestId('numbers-with')).toContainText('tCO₂e')
  await expect(page.getByTestId('numbers-with')).toContainText('whole ecosystem incl. soil')
  await expect(page.getByTestId('numbers-with')).not.toContainText('provisional')
})

test('plan edit and apply changes "with restoration" numbers', async ({ page, request }) => {
  await seedReadyScene(request); await page.goto('/#/time-travel')
  await runForecast(page)
  await page.getByRole('slider', { name: 'Year' }).fill('2035')
  await page.getByRole('button', { name: 'Propose plan (AI)' }).click()
  await expect(page.getByTestId('plan-status')).toContainText('Plan v1', { timeout: 30_000 })
  const before = await page.getByTestId('numbers-with').innerText()
  await page.getByTestId('zone-hit-with-KSL-B3').click(); await page.getByRole('button', { name: 'Add Avicennia marina' }).click()
  await expect(page.getByTestId('plan-status')).toContainText('Plan v2')
  await page.getByRole('button', { name: 'Apply plan' }).click()
  await expect(page.getByTestId('numbers-with')).not.toHaveText(before, { useInnerText: true, timeout: 30_000 })
  await expect(page.getByTestId('plan-status')).toContainText('Plan v2 · applied')
})

test('planting where the zone has no mud is rejected and the plan stays editable', async ({ page, request }) => {   // Review Focus 2
  await seedReadyScene(request)
  // KSL-A1 becomes all water: no mud, no eroded edge.
  expect((await request.post('/api/v1/test/seed/capture', {
    data: { zone_metrics: { 'KSL-A1': { canopy_pct: 0, water_pct: 100, mud_pct: 0, other_pct: 0 } }, evidence_grade: true },
  })).status()).toBe(201)
  await page.goto('/#/time-travel')
  await page.getByRole('button', { name: 'Propose plan (AI)' }).click()
  await expect(page.getByTestId('plan-status')).toContainText('Plan v1', { timeout: 30_000 })
  await page.getByTestId('zone-hit-with-KSL-A1').click()
  const panel = page.getByTestId('zone-plan-panel')
  await panel.getByRole('button', { name: 'Add Rhizophora apiculata' }).click()
  await expect(panel.getByRole('alert')).toContainText('planting needs mud or an eroded edge in KSL-A1')
  await expect(page.getByTestId('plan-status')).toContainText('Plan v1')
  await panel.getByRole('button', { name: 'Add Silt fence' }).click()
  await expect(page.getByTestId('plan-status')).toContainText('Plan v2')
})

test('works without NVIDIA and shows no AI-illustrated badge', async ({ page, request }) => {   // Review Focus 1
  await seedReadyScene(request); await page.goto('/#/time-travel')
  await runForecast(page)
  await waitForPreload(page)
  await page.getByRole('slider', { name: 'Year' }).fill('2035')
  await expect(page.getByTestId('numbers-with')).toContainText('2035')
  await expect(page.getByText('AI-illustrated')).toHaveCount(0)
})

test('slider scrubbing issues no requests after preload', async ({ page, request }) => {        // Review Focus 5
  await seedReadyScene(request); await page.goto('/#/time-travel')
  await runForecast(page)
  await waitForPreload(page)
  // All 20 textures + 20 heights (and the real capture) arrived: scrubbing below has everything it needs.
  await expect(page.getByTestId('futures-preload')).toHaveAttribute('data-missing', '0')
  // The shell polls status in the background, so 'networkidle' may never settle; count only the data the scrub could need.
  let n = 0; page.on('request', (r) => { if (/\/api\/v1\/(media|forecasts|plans)\//.test(r.url())) n++ })
  for (const y of ['2027', '2029', '2031', '2033', '2035']) await page.getByRole('slider', { name: 'Year' }).fill(y)
  await expect(page.getByTestId('numbers-without')).toContainText('2035')
  expect(n).toBe(0)
})

test('a forecast before any baseline explains what to do', async ({ page, request }) => {   // Review Focus 3
  expect((await request.post('/api/v1/test/reset')).ok()).toBeTruthy()
  await page.goto('/#/time-travel')
  await expect(page.getByText(/no forecast yet/i)).toBeVisible()
  await page.getByRole('button', { name: 'Run forecast' }).click()
  await expect(page.getByRole('alert')).toContainText(/Take a capture first|Set a baseline first/)
})
