import { expect, test } from '@playwright/test'
import { contrastRatio, openEvidenceLedger } from './helpers'
import { reconnectNodes, seedAppliedPlanScene, seedFlagAndAssessment } from './seed'

test.setTimeout(120_000) // a cold stack commissions its nodes first

test.afterAll(async ({ request }) => {
  test.setTimeout(120_000) // re-keying the nodes can take a minute; hooks do not inherit the file-level timeout
  expect((await request.post('/api/v1/test/reset')).ok()).toBeTruthy()
  await reconnectNodes(request)
})

// seedAppliedPlanScene leaves an applied plan; Time Travel keeps "Apply plan" rendered for the editable draft.
for (const vp of [{ width: 1920, height: 1080 }, { width: 1366, height: 768 }]) {
  test(`primary actions visible at ${vp.width}x${vp.height}`, async ({ page, request }) => {
    // Review Focus 5
    await page.setViewportSize(vp)
    await seedAppliedPlanScene(request)
    for (const [hash, name] of [['#/time-travel', 'Apply plan'], ['#/ledger', 'Verify chain'], ['#/ledger', 'Generate Projected record']]) {
      if (hash === '#/ledger') await openEvidenceLedger(page)
      else await page.goto('/' + hash)
      await expect(page.getByRole('button', { name })).toBeInViewport()
    }
    await page.keyboard.press('d')
    await expect(page.getByRole('button', { name: 'Start' })).toBeInViewport()
  })
}

test('risk colours meet AA contrast with labels', async ({ page, request }) => {
  await seedFlagAndAssessment(request, 'KSL-B3')
  await page.goto('/#/twin')
  for (const cls of ['low', 'medium', 'high', 'critical']) {
    const chip = page.getByTestId(`risk-chip-sample-${cls}`) // legend samples rendered by the Twin page
    await expect(chip).toHaveText(new RegExp(cls, 'i'))
    const [fg, bg] = await chip.evaluate((el) => [getComputedStyle(el).color, getComputedStyle(el).backgroundColor])
    expect(contrastRatio(fg, bg)).toBeGreaterThanOrEqual(4.5)
  }
})

// Final review C1: the page-transition wrapper must not turn a page root back into an input-capturing layer
// over the persistent map. The map may be absent in test mode, so this checks the CSS, not a drag.
test('page roots over the map let input through to it', async ({ page }) => {
  for (const [hash, root] of [['#/command', '.page'], ['#/satellite', '.sat-page'], ['#/network', '.net-page'], ['#/twin', '.twin-page'], ['#/ledger', '.ledger-page']]) {
    if (hash === '#/ledger') await openEvidenceLedger(page)
    else await page.goto('/' + hash)
    const el = page.locator(`.page-transition > ${root}`)
    await expect(el).toHaveCount(1)
    expect(await el.evaluate((e) => getComputedStyle(e).pointerEvents), `${hash} ${root}`).toBe('none')
  }
})

/** True when the centre of the button hits the button itself (not the Director panel or anything else on top). */
async function topmostAtCentre(page: import('@playwright/test').Page, name: string): Promise<boolean> {
  const btn = page.getByRole('button', { name })
  await btn.scrollIntoViewIfNeeded()
  return btn.evaluate((el) => {
    const r = el.getBoundingClientRect()
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
    return hit !== null && el.contains(hit)
  })
}

// Final review I2: with the Director open, its own steps' controls stay clickable beside the panel.
for (const vp of [{ width: 1920, height: 1080 }, { width: 1366, height: 768 }]) {
  test(`director panel leaves page actions clickable at ${vp.width}x${vp.height}`, async ({ page, request }) => {
    await page.setViewportSize(vp)
    await seedAppliedPlanScene(request)
    await page.goto('/#/time-travel')
    await page.keyboard.press('d')
    await expect(page.getByTestId('director-panel')).toBeVisible()
    await expect(page.locator('.shell')).toHaveClass(/director-open/)
    // A running Director shows its full step list (the tall panel the operator actually sees during the demo).
    expect((await request.post('/api/v1/director/start', { data: { branch: 'main' } })).ok()).toBeTruthy()
    try {
      await expect(page.getByTestId('step-predict')).toBeVisible()
      for (const [hash, name] of [['#/time-travel', 'Apply plan'], ['#/ledger', 'Generate Projected record']]) {
        await page.evaluate((h) => { location.hash = h }, hash)
        if (hash === '#/ledger') await page.getByRole('button', { name: 'Evidence & original ledger ↗', exact: true }).click()
        await expect(page.getByRole('button', { name })).toBeVisible()
        await expect(page.getByTestId('director-panel')).toBeVisible()
        // elementFromPoint, not a trial click: "Apply plan" is disabled once the seeded plan is applied.
        expect(await topmostAtCentre(page, name), `${name} is topmost`).toBe(true)
      }
    } finally {
      await request.post('/api/v1/director/stop')
    }
  })
}
