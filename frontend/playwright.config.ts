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
        trace: 'on',
        screenshot: 'on',
        video: 'on'
      }
    }
  ],

  // Start both Flask backend and Vite dev server before running tests
  webServer: [
    {
      command: 'python3 -m backend.app',
      port: 5001,
      reuseExistingServer: !process.env.CI,
      cwd: '..',
      timeout: 30000
    },
    {
      command: 'pnpm dev',
      port: 5175,
      reuseExistingServer: !process.env.CI,
      timeout: 30000
    }
  ]
})
