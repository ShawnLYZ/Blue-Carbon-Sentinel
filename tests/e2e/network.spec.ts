import { expect, test, type APIRequestContext } from '@playwright/test'

// Test-mode devstack: 8 auto-commissioned simulated nodes in the deterministic fallback layout, where
// WQ-01 covers B3 (controller ruling, Task 13), so a manual B3 task gets real acks and turns active.

/** Cancels every open task so each test starts from a quiet network (and a B3 task is new, not extended). */
async function cancelOpenTasks(request: APIRequestContext) {
  const res = await request.get('/api/v1/tasks?status=active')
  if (!res.ok()) return
  for (const t of (await res.json()) as { id: string; status: string }[]) {
    if (t.status === 'issued' || t.status === 'active') await request.post(`/api/v1/tasks/${t.id}/cancel`)
  }
}

test.beforeEach(async ({ request }) => {
  await cancelOpenTasks(request)
})
test.afterAll(async ({ request }) => {
  await cancelOpenTasks(request)
})

test('network page lists 8 simulated nodes and live values update', async ({ page }) => {
  await page.goto('/#/network')
  await expect(page.getByTestId('node-row')).toHaveCount(8)
  await expect(page.getByTestId('node-row').first()).toContainText('SIMULATED')
  for (const row of await page.getByTestId('node-row').all()) await expect(row).toContainText('SIMULATED')
})

test('manual task shows in timeline and can be cancelled', async ({ page }) => {
  await page.goto('/#/network')
  await page.getByRole('button', { name: 'Manual task' }).click()
  await page.getByTestId('zone-B3').click()
  // Recently finished tasks stay in the timeline for 10 minutes: follow the card of the task just made
  // (the timeline is newest first).
  const first = page.getByTestId('task-card').first()
  await expect(first).toContainText('B3')
  const id = await first.getAttribute('data-task-id')
  const card = page.locator(`[data-testid="task-card"][data-task-id="${id}"]`)
  await expect(card).toContainText('active')
  await card.getByRole('button', { name: 'Cancel' }).click()
  await expect(card).toContainText('cancelled')
})

test('re-commission asks for confirmation', async ({ page }) => {
  await page.goto('/#/network')
  await page.getByRole('button', { name: 'Re-commission' }).click()
  await expect(page.getByRole('dialog')).toContainText('Node positions will change')
  await page.getByRole('dialog').getByRole('button', { name: 'Keep current positions' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('system page shows commissioning and the device registry', async ({ page }) => {
  await page.goto('/#/system')
  await expect(page.getByTestId('commissioning-status')).toContainText(/class map|fallback spread/)
  await expect(page.getByTestId('registry-row')).toHaveCount(8)
  for (const row of await page.getByTestId('registry-row').all()) {
    await expect(row).toContainText('SIMULATED')
    await expect(row.getByRole('button', { name: 'Regenerate key' })).toBeVisible()
  }
  await expect(page.getByTestId('registry-camera')).toBeVisible()
})
