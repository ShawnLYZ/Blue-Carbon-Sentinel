import { expect, test, type APIRequestContext } from '@playwright/test'

const syncState = async (request: APIRequestContext) =>
  ((await (await request.get('/api/v1/system/status')).json()) as { sync: { state: string } }).sync.state

test.afterEach(async ({ request }) => {
  await request.post('/api/v1/test/cloud/fail', { data: { failing: false } })
  // leave the stack recovered (the cloud_offline alert cleared) for the next spec; back-off is at most a few s here
  await expect.poll(() => syncState(request), { timeout: 30_000 }).not.toBe('offline')
})

test('buffering badge appears once the cloud is offline', async ({ page, request }) => {
  await request.post('/api/v1/test/cloud/fail', { data: { failing: true } })
  // A failed pass needs unsent work. The stack's background rows
  // (startup commissioning) may already be drained, so queue a row of our own (a seeded capture).
  const seeded = await request.post('/api/v1/test/seed/capture', { data: { zone_metrics: { 'KSL-B3': { canopy_pct: 60 } }, evidence_grade: true } })
  expect(seeded.status()).toBe(201)
  await page.goto('/#/command')
  // The badge is the outage signal: three consecutive failed passes (H6), about 1 s + 2 s of back-off apart.
  await expect.poll(() => syncState(request), { timeout: 30_000 }).toBe('offline')
  await expect(page.getByText(/Buffering offline \(\d+ queued\)/)).toBeVisible()
  await expect(page.getByTestId('chip-cloud')).toContainText('Offline')
})
