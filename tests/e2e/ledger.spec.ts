import { expect, test } from '@playwright/test'
import { openEvidenceLedger } from './helpers'
import { reconnectNodes, seedAppliedPlanScene, seedProjectedRecord } from './seed'

test.setTimeout(90_000) // a cold stack commissions its nodes first

// The seeds reset the store, which re-commissions the nodes with keys the simulator does not know:
// leave the stack as later specs (network, ...) expect it.
test.afterAll(async ({ request }) => {
  test.setTimeout(120_000) // re-keying the nodes can take a minute; hooks do not inherit the file-level timeout
  expect((await request.post('/api/v1/test/reset')).ok()).toBeTruthy()
  await reconnectNodes(request)
})

test('generate projected record then verify chain shows intact', async ({ page, request }) => {
  await seedAppliedPlanScene(request); await openEvidenceLedger(page)
  await page.getByRole('button', { name: 'Generate Projected record' }).click()
  await expect(page.getByTestId('record-row')).toHaveCount(1); await expect(page.getByTestId('record-row')).toContainText('Projected')
  await page.getByRole('button', { name: 'Verify chain' }).click(); await expect(page.getByTestId('chain-status')).toContainText('intact')
})

test('evidence pack downloads as PDF', async ({ page, request }) => {
  await seedProjectedRecord(request); await openEvidenceLedger(page); await page.getByTestId('record-row').first().click()
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download evidence pack' }).click()])
  expect(dl.suggestedFilename()).toMatch(/^BC-2026-\d{5}\.pdf$/)
})

test('eligibility tracker shows the four rules for a planted zone and the demo disclaimer', async ({ page, request }) => {
  await seedProjectedRecord(request); await openEvidenceLedger(page)
  await expect(page.getByText('Demo record — not a certified carbon credit').first()).toBeVisible()
  const zone = page.getByTestId('eligibility-zone').first()
  await expect(zone).toContainText('/3 captures'); await expect(zone).toContainText('healthy'); await expect(zone).toContainText('chain')
  await expect(zone).toContainText(/0\.\d\d [≥<] 0\.80/)
  await page.getByTestId('record-row').first().click()
  await expect(page.getByTestId('record-hash')).toHaveText(/^[0-9a-f]{64}$/)
  await expect(page.getByTestId('evidence-telemetry-link')).toBeVisible()
})
