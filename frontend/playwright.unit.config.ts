import { defineConfig } from '@playwright/test'

/**
 * Unit-test project for the pure modules under `src/utils` and friends.
 *
 * Deliberately a SECOND config rather than a third project in
 * `playwright.config.ts`: `webServer` there is global to the run, so a
 * `--project=unit` on that config would still boot Flask and vite to run
 * assertions against pure functions. This one starts nothing.
 *
 * Deliberately the Playwright runner rather than vitest: it is already a
 * devDependency, already transpiles TS, and already ships `expect`. These
 * tests request no browser fixture, so no browser is launched.
 *
 * Why this lane exists at all: `src/utils/*` had no test whose import path
 * reaches it, so every change to those modules arrived unverified and the
 * only gate was `tsc`. Types do not catch a diff parser that drops a hunk.
 */
export default defineConfig({
  testDir: './tests/unit',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [['list']] : [['list']]
})
