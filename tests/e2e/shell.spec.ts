import { expect, test } from '@playwright/test'

// Only a real token counts; without one the webServer serves a dummy token (see playwright.config.ts).
const hasToken = Boolean(process.env.MAPBOX_TOKEN)

test('shell loads with chips and demo-time indicator, and keys navigate', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('chip-camera')).toBeVisible()
  await expect(page.getByText(/DEMO TIME/)).toBeVisible()
  for (const [key, title] of [
    ['1', 'Command Center'],
    ['2', 'Satellite Intelligence'],
    ['3', 'Sentinel Network'],
    ['4', 'Digital Twin'],
    ['5', 'Time Travel & Restoration'],
    ['6', 'Carbon Ledger'],
    ['7', 'System'],
  ]) {
    await page.keyboard.press(key)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(title)
  }
})

test('map unavailable message when token rejected', async ({ page }) => {
  // Review Focus 4: a token is always served here (real or dummy), so this exercises the 401 path,
  // never the missing-token panel.
  let intercepted = 0
  await page.route('**/api.mapbox.com/**', (r) => {
    intercepted += 1
    return r.fulfill({ status: 401, contentType: 'application/json', body: '{"message":"Not Authorized - Invalid Token"}' })
  })
  await page.goto('/#/command')
  await expect(page.getByText(/Map unavailable: Mapbox rejected the access token \(HTTP 401\)/)).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(/no Mapbox token is configured/)).toHaveCount(0)
  expect(intercepted).toBeGreaterThan(0)
  await expect(page.getByTestId('chip-camera')).toBeVisible()
})

test('about cover states the hardware position', async ({ page }) => {
  await page.goto('/#/about')
  await expect(page.getByText('Fixed, anchored edge nodes — no drones, no swarm robotics.')).toBeVisible()
  await expect(page.getByText('The Carbon Ledger tells us WHAT IT IS WORTH.')).toBeVisible()
})

test('persistent map renders the globe and survives navigation', async ({ page }) => {
  test.skip(!hasToken, 'MAPBOX_TOKEN is not set')
  await page.goto('/#/command')
  const canvas = page.locator('canvas.mapboxgl-canvas')
  await expect(canvas).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(/Map unavailable/)).toHaveCount(0)
  await canvas.evaluate((el) => el.setAttribute('data-persist', '1'))
  await page.keyboard.press('2')
  await page.keyboard.press('3')
  await expect(page.locator('canvas.mapboxgl-canvas[data-persist="1"]')).toBeVisible()
  await page.keyboard.press('5') // Time Travel hides the persistent map and shows its own two
  await expect(page.locator('canvas.mapboxgl-canvas[data-persist="1"]')).toBeHidden()
  await expect(page.locator('canvas.mapboxgl-canvas[data-persist="1"]')).toHaveCount(1)
  await page.keyboard.press('2')
  await expect(page.locator('canvas.mapboxgl-canvas[data-persist="1"]')).toBeVisible()
})
