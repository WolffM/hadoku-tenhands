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

// Ports are overridable because several agents work this repo at once, often
// from separate worktrees. On the defaults, `reuseExistingServer` happily
// attaches to whichever checkout started a dev server first — so a run in one
// tree silently tests another tree's code. Give a worktree its own pair:
//   PW_FRONTEND_PORT=5186 PW_BACKEND_PORT=5002 pnpm test
const FRONTEND_PORT = process.env.PW_FRONTEND_PORT ?? '5184'
const BACKEND_PORT = process.env.PW_BACKEND_PORT ?? '5001'
const FRONTEND_URL = `http://localhost:${FRONTEND_PORT}`

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
    baseURL: FRONTEND_URL,
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
        baseURL: FRONTEND_URL,
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
      // Two env vars the suite cannot run without:
      //   PIPELINE_LOOP_ENABLED=false — a test run must not start a background
      //     thread that advances real pipelines against real repos.
      //   WHOAMI_TEST_OVERRIDES — the tier gate resolves `X-User-Key` through
      //     hadoku.me/session/whoami, which does not know `test-key` and
      //     answers 403. The specs all browse as `?key=test-key`, so without
      //     this the real-backend tests only pass when some *other* server
      //     happens to be listening on this port with an override already set.
      //     `middleware/whoami.py` documents this var for exactly this case.
      command:
        `PORT=${BACKEND_PORT} PIPELINE_LOOP_ENABLED=false ` +
        `WHOAMI_TEST_OVERRIDES='{"test-key":"admin"}' ${PYTHON} -m backend.app`,
      url: `http://localhost:${BACKEND_PORT}/tenhands/api/healthcheck`,
      reuseExistingServer: !process.env.CI,
      cwd: '..',
      timeout: 60_000
    },
    {
      command: `BACKEND_PORT=${BACKEND_PORT} pnpm exec vite --port ${FRONTEND_PORT} --strictPort`,
      url: FRONTEND_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000
    }
  ]
})
