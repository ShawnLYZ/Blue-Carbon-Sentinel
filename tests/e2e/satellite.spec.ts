import { expect, test } from '@playwright/test'
import { seedBaselineAndFlag } from './seed'

// Seeds captures through POST /api/v1/test/seed/capture (numbers; test mode adds synthetic media, R22a).
test('timeline lists seeded captures with flag badges and metrics table', async ({ page, request }) => {
  await seedBaselineAndFlag(request)
  await page.goto('/#/satellite')
  await expect(page.getByTestId('capture-thumb')).toHaveCount(2)
  await expect(page.getByTestId('flag-badge-KSL-B3')).toContainText('canopy loss')
  await expect(page.getByRole('row', { name: /B3/ })).toContainText('pp')
})

test('header shows the model scale and calibration type; seeded captures show no substitute image', async ({ page, request }) => {
  await seedBaselineAndFlag(request)
  // Since M5 (ruling R22a) test-mode seeded captures carry synthetic media of their own. A capture whose
  // image file is missing (the M2 seeded case) answers 404 "no_media": the thumb must say so, not substitute.
  await page.route('**/api/v1/media/captures/*/image', (r) =>
    r.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'Capture has no image file.', details: { reason: 'no_media' } } } }),
  )
  await page.goto('/#/satellite')
  await expect(page.getByText('Model scale 1:500 (1 cm = 5 m)')).toBeVisible()
  await expect(page.getByText('Default calibration')).toBeVisible()
  await expect(page.getByText('NDVI-proxy (VARI) — RGB camera, no near-infrared; true NDVI needs Sentinel-2 B4/B8')).toBeVisible()
  await expect(page.getByTestId('capture-thumb').first()).toContainText('no image (seeded)')
  await expect(page.getByTestId('capture-thumb').locator('img')).toHaveCount(0)
})

test('a new seeded capture appears live without reloading', async ({ page, request }) => {
  await seedBaselineAndFlag(request)
  await page.goto('/#/satellite')
  await expect(page.getByTestId('capture-thumb')).toHaveCount(2)
  const res = await request.post('/api/v1/test/seed/capture', {
    data: { zone_metrics: {}, evidence_grade: false, trigger: 'interval' },
  })
  expect(res.status()).toBe(201)
  await expect(page.getByTestId('capture-thumb')).toHaveCount(3)
  await expect(page.getByTestId('capture-thumb').filter({ hasText: 'not evidence-grade' })).toHaveCount(1)
})

test('corner picker is disabled while the camera is offline', async ({ page, request }) => {
  await request.post('/api/v1/test/reset')
  await page.goto('/#/satellite')
  await expect(page.getByRole('button', { name: 'Four-corner calibration…' })).toBeDisabled()
  await expect(page.getByText(/camera is offline/i).first()).toBeVisible()
})

test('System page shows camera and calibration sections', async ({ page, request }) => {
  await request.post('/api/v1/test/reset')
  await page.goto('/#/system')
  await expect(page.getByRole('heading', { name: 'Camera' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Calibration' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Reconnect' })).toBeVisible()
  await expect(page.getByText('Default calibration')).toBeVisible()
  await page.getByRole('button', { name: 'Reset to default' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Reset to the default calibration')
  await dialog.getByRole('button', { name: 'Reset to default' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByText('Default calibration')).toBeVisible()
})
