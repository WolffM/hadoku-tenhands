import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright configuration for VibeDispatch E2E tests.
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
    baseURL: 'http://localhost:5175',
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
        baseURL: 'http://localhost:5175',
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
      command: 'PORT=5001 python3 -m backend.app',
      url: 'http://localhost:5001/dispatch/api/healthcheck',
      reuseExistingServer: !process.env.CI,
      cwd: '..',
      timeout: 60_000
    },
    {
      command: 'BACKEND_PORT=5001 pnpm dev',
      url: 'http://localhost:5175',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000
    }
  ]
})
