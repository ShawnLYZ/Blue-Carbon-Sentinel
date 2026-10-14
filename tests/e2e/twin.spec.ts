import { expect, test } from '@playwright/test'
import { seedFlagAndAssessment } from './seed'

// Test-mode stack: the simulator's 8 nodes, a seeded baseline + flag (each seeding test resets the
// store first) and the rules tier answering every AI role, so the source chip reads "Rules".

test('zone card shows all sections with source chip and confidence bars', async ({ page, request }) => {
  await seedFlagAndAssessment(request, 'KSL-B3'); await page.goto('/#/twin')
  await page.getByTestId('zone-hit-KSL-B3').click()
  const card = page.getByTestId('zone-card')
  for (const s of ['KSL-B3', 'Canopy', 'NDVI-proxy', 'Dieback', 'Stressors', 'Risk', 'Confidence', 'Root cause']) await expect(card).toContainText(s)
  await expect(card.getByTestId('source-chip')).toContainText('Rules')
  await expect(card.getByTestId('confidence-bar')).toHaveCount(4)
})

test('layer toggles change visible layers', async ({ page }) => {
  await page.goto('/#/twin'); await page.getByRole('switch', { name: 'Turbidity' }).click()
  await expect(page.getByTestId('legend')).toContainText('NTU')
})

test('carbon layer toggles its legend; Open in Time Travel opens the zone plan', async ({ page, request }) => {
  await seedFlagAndAssessment(request, 'KSL-B3'); await page.goto('/#/twin')
  const carbon = page.getByRole('switch', { name: 'Carbon columns' })
  await expect(carbon).toBeEnabled()
  await carbon.click()
  await expect(page.getByTestId('carbon-legend')).toContainText('60 m')
  await page.getByTestId('zone-hit-KSL-B3').click()
  const card = page.getByTestId('zone-card')
  await expect(card).toContainText('Carbon stock')
  await card.getByRole('button', { name: 'Open in Time Travel' }).click()
  await expect(page).toHaveURL(/#\/time-travel$/)
  await expect(page.getByTestId('zone-plan-panel')).toContainText('KSL-B3')
})

test('request AI analysis twice shows the rate-limited toast', async ({ page, request }) => {
  await seedFlagAndAssessment(request, 'KSL-B3'); await page.goto('/#/twin')
  await page.getByTestId('zone-hit-KSL-B3').click()
  const card = page.getByTestId('zone-card')
  const analyze = card.getByRole('button', { name: 'Request AI analysis' })
  // A request in the last 30 s (an earlier run against a reused server) is already rate limited.
  await analyze.click()
  await expect(card.getByRole('status')).toContainText(/Analysis requested|rate limited/)
  await analyze.click()
  await expect(card.getByRole('status')).toContainText('rate limited')
})
