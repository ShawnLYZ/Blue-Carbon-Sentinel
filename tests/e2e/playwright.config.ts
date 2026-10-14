import { defineConfig, devices } from '@playwright/test'
import { fileURLToPath } from 'node:url'

const repoRoot = fileURLToPath(new URL('../..', import.meta.url))
const env: Record<string, string> = {}
// Test-mode devstack never reads .env; the map-dependent checks get the public token from the process env.
// Without a real MAPBOX_TOKEN a dummy token is served instead, so the map still starts and the
// "token rejected" test exercises the intercepted-401 path rather than the missing-token panel
// (that panel is covered by the MapStage vitest render test). The real-map test skips on the dummy.
export const E2E_DUMMY_MAPBOX_TOKEN = 'pk.e2e-dummy'
env.BCS_MAPBOX_PUBLIC_TOKEN = process.env.MAPBOX_TOKEN || E2E_DUMMY_MAPBOX_TOKEN
// The test-mode stack's ports; override them when a normal stack already holds 8700/8701 on this machine
// (otherwise `reuseExistingServer` would reuse that stack, and the global setup would refuse to run).
const gsPort = process.env.E2E_GS_PORT || '8700'
const simPort = process.env.E2E_SIM_PORT || '8701'
// The simulator only allows the default Ground Station origin (addendum K3); widen it for another port.
if (gsPort !== '8700') env.BCS_CORS_ORIGINS = JSON.stringify([`http://127.0.0.1:${gsPort}`, `http://localhost:${gsPort}`])

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  // Ruling R28: refuses to run unless the target Ground Station is in test mode (runs after the web server
  // is started or reused, before any spec).
  globalSetup: fileURLToPath(new URL('./test-mode-guard.ts', import.meta.url)),
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  outputDir: fileURLToPath(new URL('../../test-results', import.meta.url)),
  use: { baseURL: `http://127.0.0.1:${gsPort}`, trace: 'retain-on-failure' },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        launchOptions: { args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] },
      },
    },
  ],
  webServer: {
    // Children's stderr lands in var/logs/e2e (CI uploads it on failure); a failed start quotes its tail.
    command: `uv run bcs-gs devstack --test-mode --gs-port ${gsPort} --sim-port ${simPort} --log-dir var/logs/e2e`,
    url: `http://127.0.0.1:${gsPort}/api/v1/system/status`,
    reuseExistingServer: !process.env.CI,
    cwd: repoRoot,
    env,
    timeout: 120_000,
  },
})
