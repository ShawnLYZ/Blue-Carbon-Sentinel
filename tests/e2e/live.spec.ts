import { expect, test } from '@playwright/test'

// Test mode never starts the camera link, so the Ground Station reports the camera offline and
// /ws/live sends nothing: the banner must show and no frame may be substituted.
test('camera offline banner shows and nothing is substituted', async ({ page }) => {
  await page.goto('/#/satellite')
  await expect(page.getByText(/CAMERA OFFLINE since \d\d:\d\d:\d\d \(MYT\)/)).toBeVisible()
  await expect(page.getByTestId('reality-surface-texture')).toHaveAttribute('data-has-frame', 'false')
})

// The frame-to-screen readout is honest without a camera: no numbers until a real frame arrives.
test('system page live readout waits for a real frame', async ({ page }) => {
  await page.goto('/#/system')
  await expect(page.getByTestId('live-stats-empty')).toBeVisible()
  await expect(page.getByTestId('live-stats')).toHaveCount(0)
})
