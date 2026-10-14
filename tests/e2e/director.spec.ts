import { expect, test, type APIRequestContext } from '@playwright/test'
import { createManualTask, reconnectNodes } from './seed'

// Test-mode devstack: no camera, so the detect step is blocked; 8 simulated nodes accept a B3 task.

async function cancelOpenTasks(request: APIRequestContext) {
  const res = await request.get('/api/v1/tasks?status=active')
  if (!res.ok()) return
  for (const t of (await res.json()) as { id: string; status: string }[]) {
    if (t.status === 'issued' || t.status === 'active') await request.post(`/api/v1/tasks/${t.id}/cancel`)
  }
}

test.beforeEach(async ({ request }) => {
  expect((await request.post('/api/v1/test/reset')).ok()).toBeTruthy()
  await reconnectNodes(request) // the reset leaves the nodes with keys the simulator does not know; a manual task needs them
  await cancelOpenTasks(request)
})
test.afterEach(async ({ request }) => {
  await request.post('/api/v1/director/stop')
  await cancelOpenTasks(request)
})

test('director shows blocked camera step and advances on manual task', async ({ page, request }) => {
  await page.goto('/#/command')
  await page.keyboard.press('d')
  await page.getByRole('button', { name: 'Start' }).click()
  await expect(page.getByTestId('step-detect')).toContainText('Camera offline — step requires live captures')
  await expect(page.getByTestId('step-detect')).toContainText('Physical action on the model')
  await expect(page.getByTestId('step-detect')).toHaveAttribute('data-status', 'blocked')
  await page.getByRole('button', { name: 'Skip' }).click()
  await expect(page.getByTestId('step-detect')).toHaveAttribute('data-status', 'skipped')
  await createManualTask(request, 'KSL-B3')
  await expect(page.getByTestId('step-task')).toHaveAttribute('data-status', 'done', { timeout: 15_000 })
  await expect(page.getByTestId('step-task')).toContainText('accepted by')
})

test('d key toggles the panel and Exit stops the run', async ({ page }) => {
  await page.goto('/#/command')
  await expect(page.getByTestId('director-panel')).toHaveCount(0)
  await page.keyboard.press('d')
  await expect(page.getByTestId('director-panel')).toBeVisible()
  await page.getByRole('button', { name: 'Start' }).click()
  await expect(page.getByTestId('step-detect')).toBeVisible()
  await page.getByRole('button', { name: 'Exit' }).click()
  await expect(page.getByRole('button', { name: 'Start' })).toBeVisible()
  await page.keyboard.press('d')
  await expect(page.getByTestId('director-panel')).toHaveCount(0)
})

test('predict step opens Time Travel once and shows the scrub hint', async ({ page, request }) => {
  await page.goto('/#/command')
  await page.keyboard.press('d')
  await page.getByRole('button', { name: 'Start' }).click()
  await expect(page.getByTestId('director-status')).toBeVisible() // the run is active; before this the state still reads current: null
  for (let i = 0; i < 8; i++) {
    const cur = ((await (await request.get('/api/v1/director')).json()) as { current: string | null }).current
    if (cur === 'predict' || cur === null) break
    await page.getByRole('button', { name: 'Skip' }).click()
    await expect.poll(async () => ((await (await request.get('/api/v1/director')).json()) as { current: string | null }).current).not.toBe(cur)
  }
  await expect(page).toHaveURL(/#\/time-travel$/)
  await expect(page.getByTestId('step-predict')).toContainText('Run forecast, then scrub to 2035')
  await page.keyboard.press('1')
  await expect(page).toHaveURL(/#\/command$/) // navigated once, not pinned
})
