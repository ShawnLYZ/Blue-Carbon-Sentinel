import { expect, test } from '@playwright/test'
import { seedBaseline } from './seed'

test('history chart labels the AI baseline and draws it dashed', async ({ page, request }) => {
  await seedBaseline(request)
  await page.goto('/#/satellite')
  const chart = page.getByTestId('history-chart')
  await expect(chart).toContainText('AI-generated baseline — stand-in for the Sentinel-2 archive')
  await expect(chart).toHaveAttribute('data-y-axis', 'Canopy cover (%)')
  await expect(chart).toHaveAttribute('data-baseline-style', 'dashed')
  await expect(chart.locator('canvas')).toHaveCount(1)
})

test('observations and tree markers panels render their empty states', async ({ page, request }) => {
  await seedBaseline(request)
  await page.goto('/#/satellite')
  await expect(page.getByTestId('observations')).toBeVisible()
  await expect(page.getByTestId('tree-count')).toContainText('0 trees')
})

test('system AI section shows tiers and no provider switches', async ({ page }) => {
  await page.goto('/#/system')
  const s = page.getByTestId('ai-section')
  await expect(s).toContainText('vision_analyst')
  await expect(s).toContainText('tree_locator')
  await expect(s.getByTestId('ai-keys')).toBeVisible()
  await expect(s.getByTestId('ai-ollama')).toContainText('vision')
  await expect(s.getByRole('switch')).toHaveCount(0)
  await expect(s.getByRole('combobox')).toHaveCount(0)
})
