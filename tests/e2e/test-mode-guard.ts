// Ruling R28: the e2e suite resets and seeds the Ground Station it talks to, so it must never run against a
// normal (non-test) stack. Playwright starts (or reuses, `reuseExistingServer`) the web server first and
// then runs this global setup, before any spec or hook: a reused normal-mode server is refused, not mutated.
//
// The probe is one read-only GET of the OpenAPI document: the test-only routes (addendum I4) are mounted,
// and so listed, only in test mode. (A GET of a POST-only test route is no probe: the static "/" mount
// answers it 404 in either mode.)

export const OPENAPI_PATH = '/openapi.json'
export const TEST_ROUTE = '/api/v1/test/reset'

/** null when `baseURL` is a test-mode Ground Station, else why the suite must not run. */
export async function testModeProblem(baseURL: string, fetchImpl: typeof fetch = fetch): Promise<string | null> {
  const url = new URL(OPENAPI_PATH, baseURL).toString()
  const advice =
    'The e2e suite resets and seeds the Ground Station it targets, so it only runs against a test-mode stack. ' +
    'Stop the normal stack on that port, or set E2E_GS_PORT (and E2E_SIM_PORT) to free ports so Playwright ' +
    'starts its own test-mode stack, e.g. E2E_GS_PORT=8710 E2E_SIM_PORT=8711.'
  let paths: Record<string, unknown> | undefined
  try {
    const r = await fetchImpl(url, { method: 'GET', signal: AbortSignal.timeout(10_000) })
    if (!r.ok) return `Refusing to run: GET ${url} answered ${r.status}, so the Ground Station at ${baseURL} cannot be confirmed to be in test mode. ${advice}`
    paths = ((await r.json()) as { paths?: Record<string, unknown> }).paths
  } catch (e) {
    return `Refusing to run: could not read ${url} (${e instanceof Error ? e.message : String(e)}). ${advice}`
  }
  if (paths && TEST_ROUTE in paths) return null
  return `Refusing to run: the Ground Station at ${baseURL} is not in test mode (${url} lists no ${TEST_ROUTE}; it is 404 there). ${advice}`
}

export function targetBaseURL(): string {
  return `http://127.0.0.1:${process.env.E2E_GS_PORT || '8700'}`
}

export default async function globalSetup(config?: { projects?: { use?: { baseURL?: string } }[] }): Promise<void> {
  const baseURL = config?.projects?.[0]?.use?.baseURL ?? targetBaseURL()
  const problem = await testModeProblem(baseURL)
  if (problem) throw new Error(problem)
}
