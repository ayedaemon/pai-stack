# LLM Gateway

High-performance Go-based AI Gateway (Bifrost) on `:4000` (profile: `gateway`).
The unified model gateway for Hermes, DSH, and all agents in pai-stack.

## Overview

- **Engine**: [Bifrost](https://github.com/maximhq/bifrost) — ultra-low latency Go proxy (~10–15µs proxy overhead vs ~8–15ms in Python).
- **Network & Bindings**: Bound to `0.0.0.0:4000` by default (configurable via `LLM_GATEWAY_BIND_IP` in `.env`). Accessible across LAN and container networks via `http://llm-gateway:4000/v1` (aliases: `litellm`, `bifrost`).
- **Web UI & Monitoring**: Built-in web dashboard at `http://localhost:4000/` for monitoring requests, latency, token usage, and traces.
- **Structured Logging**: Emits JSON logs to container stdout (`docker logs -f llm-gateway`) and records persistent request metrics in SQLite (`/app/data/logs.db` in `llm_gateway_data` volume).

## Routing & Fallbacks

- Agents request model aliases from `http://llm-gateway:4000/v1/chat/completions`:
  - `"default"`: General text, code, and deep reasoning (latency rank 1 + full fallback chain).
  - `"vision"`: Image understanding, screenshots, diagrams (latency rank 1 vision model + vision-only fallback chain).
  - `"audio"`: Voice, speech comprehension, audio recordings (latency rank 1 audio model + audio-only fallback chain).
- All provider configurations, keys, and dynamic CEL routing rules live in `llm-gateway/config.json`, generated declaratively by `scripts/sync-models.py`.
- **Dynamic Fallbacks**: Each modality route (`default`, `vision`, `audio`) routes to the fastest vetted model (latency rank 1) with an ordered fallback chain restricted to surviving models capable of that modality.
- **Explicit Overrides**: Override rank 1 per deployment in `.env` via `PAI_DEFAULT_MODEL`, `PAI_VISION_MODEL`, or `PAI_AUDIO_MODEL`.
- **Provider Passthrough**: Downstream callers can also specify explicit provider models (e.g. `mistral/codestral-latest`, `openrouter/nvidia/nemotron-3.5-lightning:free`).
- Point it at any upstream OpenAI-compatible provider via `.env`: local (LM Studio, Ollama, llama.cpp, vLLM) or cloud providers (`MISTRAL_API_KEY`, `OPENROUTER_API_KEY`, etc.).

## Sync & Operations

```bash
make sync             # Discover live models across keyed providers, run liveness probes, write config.json, and reload gateway
make gateway-up       # Start llm-gateway container
make gateway-down     # Stop llm-gateway container
make gateway-logs     # Tail real-time structured logs
make gateway-clean    # Stop gateway and remove persistent volume
```

## Configuration & Persistence

- Config file: `llm-gateway/config.json` (mounted read-only to `/app/data/config.json:ro`).
- Volume: `llm_gateway_data` mounted at `/app/data` to persist `/app/data/config.db` and `/app/data/logs.db`.
- `"source_of_truth": "config.json"` ensures repository configuration is authoritative upon container startup.
- Virtual key enforcement on inference is disabled (`"enforce_auth_on_inference": false`) so agents connect without proprietary auth headers.
