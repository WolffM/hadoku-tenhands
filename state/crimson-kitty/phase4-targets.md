# Phase 4 targets — crimson-kitty first external-upstream batch

Selected 2026-04-18 from aggregator's all-scored-issues. Constraints:
- Not in jade-hare-era fork parents (34 repos excluded)
- Not WolffM/* personal repos
- Labeled as `bug` (not feature request / perf / lint-class)
- Distinct upstream per pick (20 unique repos)
- Title free of vibeCheck/markdownlint/bandit/jscpd/osv-scanner/yamllint markers

Rankings based on 2026-04-12 aggregator snapshot. Per-repo refresh to run
immediately before dispatch so briefs are current.

| # | Upstream | Issue | Difficulty | 👍 | 💬 | Title |
|---|---|---|---|---|---|---|
|  1 | jestjs/jest              | #2070   | beginner     | 220 | 82 | [bug] duplicate manual mock found in separate directories |
|  2 | shadcn-ui/ui             | #6843   | intermediate | 121 | 47 | Cursor pointer not working when hovering on button in Tailwind |
|  3 | cli/cli                  | #9569   | intermediate |  95 | 24 | Can't install / update `gh` due to expired GPG key? |
|  4 | nextauthjs/next-auth     | #9504   | advanced     |  46 | 69 | useSession only getting the session after manually reloading |
|  5 | microsoft/TypeScript     | #283    | beginner     |  62 | 25 | cloneNode should return sub type, not Node |
|  6 | drizzle-team/drizzle-orm | #3493   | intermediate |  52 | 22 | db.$count inside relational query generates bad SQL |
|  7 | microsoft/vscode         | #155242 | advanced     |  22 | 54 | The background of main interface became grey |
|  8 | huggingface/transformers | #36683  | beginner     |  29 | 39 | AttributeError: 'Gemma3Config' object has no attribute 'vocab_size' |
|  9 | oven-sh/bun              | #14522  | beginner     |  34 | 19 | Bun cannot proxy websocket requests |
| 10 | vercel/next.js           | #63121  | advanced     |  34 | 17 | "Rendered more hooks than during previous render" when using App Router |
| 11 | eslint/eslint            | #19118  | beginner     |  10 | 58 | Bug: File ignored because outside of base path |
| 12 | withastro/astro          | #11919  | intermediate |  22 | 26 | Navigation Links in Chrome iOS replaced upon back |
| 13 | sharkdp/bat              | #3029   | intermediate |  28 | 11 | bat fails to run due to dependency on older libgit2 on macOS |
| 14 | pnpm/pnpm                | #7068   | intermediate |  29 |  9 | prepare script runs even when --ignore-scripts |
| 15 | supabase/supabase        | #37312  | beginner     |  17 | 30 | Cookie "__cf_bm" rejected for invalid domain |
| 16 | ollama/ollama            | #14575  | advanced     |  18 | 25 | qwen 3.5 models from HuggingFace don't work |
| 17 | expressjs/express        | #2281   | intermediate |  14 | 32 | '/' route breaks strict routing |
| 18 | TanStack/query           | #2712   | beginner     |   5 | 42 | Errored queries caught by ErrorBoundary not retried on mount |
| 19 | vitejs/vite              | #21944  | intermediate |   3 | 44 | Bundle size is 19kB (31%) bigger with svelte project |
| 20 | denoland/deno            | #7590   | intermediate |  11 | 21 | Deno.exit terminates entire process when using run --watch |

Difficulty mix: 6 beginner / 8 intermediate / 6 advanced.

## Pre-dispatch TODO
- [ ] Per-repo `POST /refresh` on each of the 20 slugs right before dispatch
- [ ] Verify each issue is still OPEN on GitHub
- [ ] Aggregator audit: confirm each dossier / brief / health / contributing payload has everything vibedispatch needs

## Exclusion list (jade-hare parent repos)
OpenHands/software-agent-sdk, cloudflare/workers-sdk, containers/podman,
coollabsio/coolify, electron/electron, evanw/esbuild, expo/expo,
facebook/react, fastify/fastify, getsentry/sentry, grafana/grafana,
hoppscotch/hoppscotch, keras-team/keras, louislam/uptime-kuma,
mastra-ai/mastra, mermaid-js/mermaid, microsoft/PowerToys,
microsoft/autogen, microsoft/data-formulator, microsoft/fluentui,
microsoft/markitdown, microsoft/playwright, microsoft/pyright,
microsoft/terminal, microsoft/vcpkg, nuxt/nuxt, opentofu/opentofu,
payloadcms/payload, puppeteer/puppeteer, solidjs/solid,
storybookjs/storybook, strapi/strapi, valkey-io/valkey,
vercel/turborepo
