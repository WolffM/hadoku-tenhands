import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Build target for the static, fixture-backed public demo (`dist-demo/`).
 *
 * Deliberately NOT a library build: no `build.lib`, no `rollupOptions.external`.
 * The published library externalizes react, themes, task-ui-components, and the
 * logger because the parent page (hadoku_site) provides them as singletons. The
 * demo has no parent — it is a standalone page — so EVERYTHING bundles. That is
 * the whole point of this artifact: open it anywhere, zero backend, zero deps.
 *
 * `vite.config.ts` (the library build) is untouched by this file.
 */
export default defineConfig({
  plugins: [react()],
  base: process.env.DEMO_BASE ?? '/hadoku-tenhands/',
  build: {
    outDir: 'dist-demo',
    target: 'es2022',
    rollupOptions: {
      input: 'demo.html'
    }
  },
  // Local preview port, recorded in hadoku-registry as `tenhands-demo-preview`.
  // 5185 sits next to the vite dev server (5184) and is deliberately off the
  // vite default (4173) to avoid colliding with other repos' previews. The
  // public copy of this demo is served from GitHub Pages, not here.
  preview: {
    host: '127.0.0.1',
    port: 5185,
    strictPort: true
  }
})
