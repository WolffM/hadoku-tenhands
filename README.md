# TenHands

**Guide:** [overview](docs/guide/index.md) · [features](docs/guide/features.md) · [contributing](docs/guide/contributing.md) · [history](docs/guide/history.md) · [trivia](docs/guide/trivia.md)

An orchestration layer for dispatching coding agents at real work — and for
earning the right to ship what they produce. Two pipelines, **crimson-kitty**
and **taskauto**, share one evidence-gated engine; see the guide for what each
does, how to run the project, and the failures that shaped it.

## Configuration

Production fetches secrets from a vault broker at start-up — there are no
`.env` files in production. `cp .env.example .env` applies to external or
offline development only; the example file documents every setting:

| Variable | Description | Default |
|---|---|---|
| `AGGREGATOR_API_URL` | Base URL for the aggregator scoring API. Leave empty for offline/fallback mode. | (none) |
| `FLASK_ENV` | Set to `development` for debug mode and extended cache TTL. | `production` |
| `PORT` | Port the Flask backend listens on. | `5024` |
| `URL_PREFIX` | URL prefix for all API routes. Set to `""` for local dev without prefix. | `/tenhands` |
| `DISCORD_WEBHOOK_URL` | Webhook URL for pipeline event notifications. Leave empty to disable. | (none) |
| `BACKEND_PORT` | Backend port for Vite dev proxy. Must match `PORT`. | `5024` |

There is no `ADMIN_KEY`: see [Access control](docs/guide/contributing.md#access-control)
in the guide for how tier resolution works instead.

## License

MIT License -- see [LICENSE](LICENSE) for details.
