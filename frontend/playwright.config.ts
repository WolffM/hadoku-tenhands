import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'

// The backend's dependencies live in the repo's `.venv` (the pm2 wrapper uses
// it too); bare `python3` has none of them and the web server dies on import.
// Resolved absolutely — the server runs with `cwd: '..'`, so a relative path
// here would be interpreted against a different directory than it is written
// against.
const VENV_PYTHON = fileURLToPath(new URL('../.venv/bin/python', import.meta.url))
const PYTHON = existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3'

/**
 * Playwright configuration for TenHands E2E tests.
 * https://playwright.dev/docs/test-configuration
 *
 * Directory structure:
 *   e2e/local/   — dev/local tests (mocked APIs, fast)
 *   e2e/prod/    — production smoke tests (real APIs, slower)
 *   e2e/fixtures/ — shared test fixtures
 *
 * Run local:  pnpm exec playwright test --project local
 * Run prod:   pnpm exec playwright test --project prod
 */
export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['html', { open: 'never' }]],

  use: {
    baseURL: 'http://localhost:5184',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure'
  },

  projects: [
    {
      name: 'local',
      testDir: './e2e/local',
      use: { ...devices['Desktop Chrome'] }
    },
    {
      name: 'prod',
      testDir: './e2e/prod',
      timeout: 60_000,
      retries: 0,
      fullyParallel: false,
      use: {
        ...devices['Desktop Chrome'],
        baseURL: 'http://localhost:5184',
        actionTimeout: 10_000,
        navigationTimeout: 30_000,
        trace: 'on',
        screenshot: 'on',
        video: 'on'
      }
    }
  ],

  // Start both Flask backend and Vite dev server before running tests.
  // url= checks that the server actually responds, not just that the port is open.
  // This catches stale servers with wrong proxy configs immediately.
  webServer: [
    {
      // No pipeline loop: a test run must not start a background thread that
      // advances real pipelines against real repos.
      command: `PORT=5001 PIPELINE_LOOP_ENABLED=false ${PYTHON} -m backend.app`,
      url: 'http://localhost:5001/tenhands/api/healthcheck',
      reuseExistingServer: !process.env.CI,
      cwd: '..',
      timeout: 60_000
    },
    {
      command: 'BACKEND_PORT=5001 pnpm dev',
      url: 'http://localhost:5184',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000
    }
  ]
})
