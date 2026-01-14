import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright configuration for VibeDispatch E2E tests.
 * https://playwright.dev/docs/test-configuration
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
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] }
    }
  ],

  // Start both Flask backend and Vite dev server before running tests
  webServer: [
    {
      command: 'python -m backend.app',
      port: 5000,
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
