# ADR-003: OmniRoute as Central LLM Gateway

## Status
Superseded — OmniRoute removed; Hermes now routes directly to providers.

## Context
Hermes needs one OpenAI-compatible endpoint that can route across free pools (OpenCode/NVIDIA/OpenRouter :free) with failover, plus pin paid/pro models on demand. Direct provider SDKs would scatter keys and retry logic.

## Decision
Run `diegosouzapw/omniroute:latest` `docker-compose.yaml:37` as the sole `model.provider: omniroute` `hermes/config.yaml:2` at `http://omniroute:20128/v1` `hermes/config.yaml:4`, with `discover_models: true` `hermes/config.yaml:15`. Seed `personal/free-chat` and `personal/gemini-fallback` combos via `omniroute/seed-combos.sh:43` (dynamic + static), `candidatePool` + `maxRetries` + `routerStrategy: rules`.

## Alternatives Considered
- **LiteLLM proxy** — similar, but OmniRoute already bundles free-pool combos and `auto` strategy tuned for cost-saver.
- **Direct OpenAI/Anthropic SDKs per provider** — requires Hermes to manage keys/failover; no unified catalog.

## Consequences
- Positive: Hermes `model.default: auto/best-coding` `hermes/config.yaml:3` resolves to free failover; any of ~1066 models browseable; `make seed` `Makefile:19` re-creates combos.
- Negative: Extra hop (20128) and seed script must run after OmniRoute healthy (`depends_on: service_healthy` `docker-compose.yaml:29`, wait loop `seed-combos.sh:14`).

## Trade-offs
Unified routing and cost optimization prioritized over direct low-latency provider calls. Paid models still addressable as `provider/model` via `kanban.default_model`.
