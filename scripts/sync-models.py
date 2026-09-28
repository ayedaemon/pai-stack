#!/usr/bin/env python3
"""
sync-models.py — Keep llm-gateway serving only models that actually reply.

Pipeline (one goal, nothing else):
  1. Read provider API keys from .env.
  2. Ask each keyed provider for its model list.
  3. Probe every candidate with a tiny inference call; drop silent ones.
  4. Write llm-gateway/config.yaml with survivors only, reload the gateway.

Providers without a key are skipped. Nothing unprobed ever reaches the config,
so Hermes never routes to a listed-but-dead model.
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Terminal colors
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_DIM = "\033[2m"
C_BOLD = "\033[1m"
C_RESET = "\033[0m"


def log_ok(msg: str):
    print(f"  {C_GREEN}✓{C_RESET} {msg}")


def log_info(msg: str):
    print(f"  {C_CYAN}ℹ{C_RESET} {msg}")


def log_skip(msg: str):
    print(f"  {C_DIM}○ {msg}{C_RESET}")


def log_warn(msg: str):
    print(f"  {C_YELLOW}⚠{C_RESET} {msg}")


def parse_env_file(path: Path) -> dict:
    """Parse key=value pairs from .env file."""
    env = {}
    if not path.exists():
        return env
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.replace("export ", "").strip()
            v = v.strip().strip("'\"")
            env[k] = v
    return env


def resolve_probe_url(url: str) -> str:
    """Map host.docker.internal to 127.0.0.1 if running directly on host without DNS mapping."""
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname and "host.docker.internal" in parsed.hostname:
        try:
            socket.gethostbyname(parsed.hostname)
        except socket.gaierror:
            return urllib.parse.urlunparse(parsed._replace(netloc=parsed.netloc.replace(parsed.hostname, "127.0.0.1")))
    return url


def fetch_json(url: str, headers: Optional[dict] = None, timeout: int = 5) -> Optional[dict]:
    """Fetch JSON with clean timeout and error handling."""
    probe_url = resolve_probe_url(url)
    req = urllib.request.Request(
        probe_url,
        headers={"User-Agent": "pai-stack-sync/2.0", "Accept": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def post_json(url: str, payload: dict, headers: Optional[dict] = None, timeout: int = 5) -> Optional[dict]:
    """Post JSON with clean timeout and error handling (HTTP errors count as no-reply)."""
    probe_url = resolve_probe_url(url)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        probe_url,
        data=data,
        headers={"User-Agent": "pai-stack-sync/2.0", "Accept": "application/json", "Content-Type": "application/json", **(headers or {})},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return None
    except Exception:
        return None


def probe_openai_chat(chat_base: str, model_id: str, api_key: str, timeout: int = 10) -> bool:
    """Tiny chat completion against any OpenAI-compatible endpoint."""
    url = f"{chat_base.rstrip('/')}/chat/completions"
    payload = {"model": model_id, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
    headers = {"Authorization": f"Bearer {api_key}"}
    return post_json(url, payload, headers=headers, timeout=timeout) is not None


def probe_gemini(model_id: str, api_key: str, timeout: int = 10) -> bool:
    """Tiny generateContent call (Gemini has no OpenAI-compatible chat shape here)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": "hi"}]}], "generationConfig": {"maxOutputTokens": 1}}
    return post_json(url, payload, headers={"x-goog-api-key": api_key}, timeout=timeout) is not None


def probe_anthropic(model_id: str, api_key: str, timeout: int = 10) -> bool:
    """Tiny Messages call (Anthropic has no /chat/completions shape)."""
    url = "https://api.anthropic.com/v1/messages"
    payload = {"model": model_id, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    return post_json(url, payload, headers=headers, timeout=timeout) is not None


def model_replies(prov: dict, model_id: str, api_key: str) -> bool:
    """Route the liveness probe to the right API shape for this provider."""
    p_id = prov["id"]
    if p_id == "gemini":
        return probe_gemini(model_id, api_key)
    if p_id == "anthropic":
        return probe_anthropic(model_id, api_key)
    return probe_openai_chat(prov["chat_base"], model_id, api_key)


# ══════════════════════════════════════════════════════════════════════════════
# Providers: key in .env → list models → probe each → keep repliers.
# `curated` doubles as the candidate set when a /models listing fails, and as
# the allowlist filter for firehose endpoints (OpenRouter lists hundreds).
# ══════════════════════════════════════════════════════════════════════════════

PROVIDERS = [
    {
        "id": "primary",
        "name": "Primary OpenAI-Compatible",
        "env_key": "OPENAI_COMPATIBLE_API_KEY",
        "env_url": "OPENAI_COMPATIBLE_BASE_URL",
        "default_url": "http://host.docker.internal:8080/v1",
        "type": "openai_compatible",
    },
    {
        "id": "kilo",
        "name": "Kilo Gateway",
        "env_key": "KILO_GATEWAY_API_KEY",
        "endpoint": "https://api.kilo.ai/api/gateway/models",
        "chat_base": "https://api.kilo.ai/api/gateway",
        "prefix": "kilo",
        "curated": ["kilo-auto/free", "poolside/laguna-s-2.1:free", "stepfun/step-3.7-flash:free"],
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "env_key": "OPENROUTER_API_KEY",
        "endpoint": "https://openrouter.ai/api/v1/models",
        "chat_base": "https://openrouter.ai/api/v1",
        "prefix": "openrouter",
        "curated": [
            "openai/gpt-4o-mini",
            "anthropic/claude-3.5-sonnet",
            "deepseek/deepseek-chat",
            "deepseek/deepseek-r1",
            "meta-llama/llama-3.3-70b-instruct",
            "qwen/qwen-2.5-coder-32b-instruct",
        ],
    },
    {
        "id": "mistral",
        "name": "Mistral AI",
        "env_key": "MISTRAL_API_KEY",
        "endpoint": "https://api.mistral.ai/v1/models",
        "chat_base": "https://api.mistral.ai/v1",
        "prefix": "mistral",
        "curated": ["codestral-latest", "mistral-large-latest", "ministral-8b-latest"],
    },
    {
        "id": "groq",
        "name": "Groq",
        "env_key": "GROQ_API_KEY",
        "endpoint": "https://api.groq.com/openai/v1/models",
        "chat_base": "https://api.groq.com/openai/v1",
        "prefix": "groq",
        "curated": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "deepseek-r1-distill-llama-70b"],
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "env_key": "DEEPSEEK_API_KEY",
        "endpoint": "https://api.deepseek.com/models",
        "chat_base": "https://api.deepseek.com/v1",
        "prefix": "deepseek",
        "curated": ["deepseek-chat", "deepseek-reasoner"],
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "endpoint": "https://api.openai.com/v1/models",
        "chat_base": "https://api.openai.com/v1",
        "prefix": "openai",
        "curated": ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini"],
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "endpoint": "https://api.anthropic.com/v1/models",
        "prefix": "anthropic",
        "curated": ["claude-3-7-sonnet-20250219", "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "env_key": "GEMINI_API_KEY",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models",
        "prefix": "gemini",
        "curated": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    },
]


def parse_listing(p_id: str, data: dict, curated: List[str]) -> List[str]:
    """Extract candidate model ids from a /models response, applying volume filters."""
    found_ids: List[str] = []
    if p_id == "gemini" and isinstance(data.get("models"), list):
        for m in data["models"]:
            if isinstance(m, dict) and m.get("name") and "generateContent" in m.get("supportedGenerationMethods", []):
                found_ids.append(m["name"].replace("models/", ""))
    elif isinstance(data.get("data"), list):
        found_ids = [m.get("id") for m in data["data"] if isinstance(m, dict) and m.get("id")]

    if p_id == "kilo":
        found_ids = [m for m in found_ids if m.startswith("kilo-auto/") or ":free" in m]
    elif p_id == "openrouter":
        curated_set = set(curated)
        found_ids = [m for m in found_ids if m in curated_set or m.endswith(":free")][:10]
    return found_ids


def auth_headers(prov: dict, api_key: str) -> dict:
    if prov["id"] == "gemini":
        return {"x-goog-api-key": api_key}
    if prov["id"] == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {api_key}"}


def probe_candidates(prov: dict, candidates: List[str], api_key: str) -> List[str]:
    """Keep only models that answer a tiny inference call."""
    log_info(f"Probing {len(candidates)} {prov['name']} models for liveness...")
    live = []
    for m_id in candidates:
        if model_replies(prov, m_id, api_key):
            live.append(m_id)
        else:
            print(f"    {C_DIM}○ {m_id} (no reply, dropped){C_RESET}")
    return live


def discover_primary(prov: dict, env: dict) -> Tuple[bool, List[str]]:
    """List + probe the local/remote OpenAI-compatible box."""
    base_url = (
        env.get(prov["env_url"])
        or env.get("PRIMARY_LLM_BASE_URL")
        or env.get("LLM_BASE_URL")
        or prov["default_url"]
    )
    api_key = env.get(prov["env_key"]) or "not-needed"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key not in ("not-needed", "none", "") else {}

    clean_url = base_url.rstrip("/")
    models_url = f"{clean_url}/models" if clean_url.endswith("/v1") else f"{clean_url}/v1/models"
    data = fetch_json(models_url, headers=headers)
    if not data and not clean_url.endswith("/v1"):
        data = fetch_json(f"{clean_url}/models", headers=headers)
    if not data:
        return False, []

    raw = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    ids = [m.get("id") if isinstance(m, dict) else str(m) for m in raw if m]
    ids = [i for i in ids if i]
    if not ids:
        return True, []
    return True, probe_candidates(prov | {"chat_base": clean_url}, ids, api_key)


def discover_provider_models(prov: dict, env: dict) -> Tuple[bool, List[str]]:
    """List + probe one cloud provider. No key → skipped. No reply → dropped."""
    if prov.get("type") == "openai_compatible":
        return discover_primary(prov, env)

    api_key = env.get(prov["env_key"], "").strip()
    if not api_key or api_key == "not-needed":
        return False, []

    curated = prov.get("curated", [])
    data = fetch_json(prov["endpoint"], headers=auth_headers(prov, api_key), timeout=6) or {}
    candidates = parse_listing(prov["id"], data, curated) or list(curated)
    if not candidates:
        return True, []
    return True, probe_candidates(prov, candidates, api_key)


def generate_litellm_config(
    discovered: Dict[str, List[str]],
    env: dict,
    explicit_default: Optional[str] = None,
) -> Tuple[str, str, List[str]]:
    """Generate LiteLLM config.yaml string, returning (yaml, selected_default, fallbacks)."""
    primary_models = discovered.get("primary", [])
    primary_chat = primary_models

    # Determine default model. office2-first when reachable; live-cloud (kilo free)
    # when primary discovery is empty. Rationale (2026-09-25): a dead default hangs
    # every request for minutes before failover, so `default` must always resolve to
    # something alive. NOTE: primary discovery skips unauthenticated ("not-needed")
    # endpoints, so office2 never appears here — office2 routes are hand-maintained
    # in llm-gateway/config.yaml (OFFLINE-LAST-RESORT section); hand-restore
    # office2 entries after the box wakes.
    if explicit_default and explicit_default != "default":
        selected_default = explicit_default
        default_via_office2 = True
    elif primary_chat:
        selected_default = primary_chat[0]
        default_via_office2 = True
    else:
        selected_default = "kilo/kilo-auto/free"
        default_via_office2 = False

    # Determine working fallbacks: live cloud FIRST, office2-local LAST by policy
    # (2026-09-25: box offline; last-resort only, after all other providers exhaust).
    fallbacks = []
    # 1. Configured cloud fallbacks (independent live upstreams first)
    if "kilo" in discovered and discovered["kilo"]:
        fallbacks.append("kilo/kilo-auto/free")
    if "openrouter" in discovered and discovered["openrouter"]:
        # Reference a live-discovered group: a hardcoded id may not be emitted
        # (dangling fallback), same pattern as groq below.
        fallbacks.append(f"openrouter/{discovered['openrouter'][0]}")
    if "mistral" in discovered and discovered["mistral"]:
        fallbacks.append("mistral/codestral-latest")
    if "groq" in discovered and discovered["groq"]:
        fallbacks.append(f"groq/{discovered['groq'][0]}")
    if "deepseek" in discovered and discovered["deepseek"]:
        fallbacks.append("deepseek/deepseek-chat")
    # 2. Secondary local chat models from primary provider — LAST (offline box
    # must never head the chain; when the box is up these are still tried).
    for sec_m in primary_chat[1:]:
        clean_sec = sec_m.rstrip("/")
        short = clean_sec.split("/")[-1] if "/" in clean_sec else clean_sec
        if short and short not in fallbacks and sec_m not in fallbacks:
            fallbacks.append(short)

    # Build YAML
    lines = [
        "# LiteLLM Proxy Configuration for pai-stack",
        "# Centralized LLM gateway managing all model routing, fallbacks, and provider credentials.",
        "# NOTE: routes use mistral/ provider mapping (not openai/) so reasoning params",
        "# are stripped pre-flight — see note at primary-models section below.",
        "",
        "model_list:",
        "  # ── Primary Default Routing ───────────────────────────────────────────",
    ]
    if default_via_office2:
        lines.extend([
            "  - model_name: default",
            "    litellm_params:",
            f"      model: mistral/{selected_default}",
            "      api_base: os.environ/OPENAI_COMPATIBLE_BASE_URL",
            "      api_key: os.environ/OPENAI_COMPATIBLE_API_KEY",
            "      timeout: 1800",
            "      drop_params: true",
            "",
        ])
    else:
        # Box unreachable at sync time: point default at live kilo free.
        # Next sync with the box up restores the office2 default automatically.
        lines.extend([
            "  # TEMPORARY (auto-managed): primary box unreachable at sync time — `default`",
            "  # points at kilo free. Re-run sync after waking office2 to restore local default.",
            "  - model_name: default",
            "    litellm_params:",
            "      model: mistral/kilo-auto/free",
            "      api_base: https://api.kilo.ai/api/gateway",
            "      api_key: os.environ/KILO_GATEWAY_API_KEY",
            "      timeout: 1800",
            "      drop_params: true",
            "",
        ])

    seen = {"default"}

    # 1. Primary language models (clean short canonical names, no duplicates)
    # NOTE (2026-09-25): primary routes are mistral-mapped (not openai/) + drop_params
    # because our LiteLLM synthesizes a conflicting nested `reasoning` object from ANY
    # `reasoning_effort` value, and strict OpenAI-compatible upstreams 400 on the pair.
    # The mistral provider spec excludes reasoning params so they are stripped pre-flight
    # (verified live: 200 + forced tool-call + SSE streaming).
    primary_chat_unique = []
    for m_id in primary_models:
        clean_id = m_id.rstrip("/")
        short_name = clean_id.split("/")[-1] if "/" in clean_id else clean_id
        if not short_name:
            short_name = m_id.strip("/") or "primary-model"
        if short_name not in seen:
            seen.add(short_name)
            primary_chat_unique.append((short_name, m_id))

    if primary_chat_unique:
        lines.append("  # ── Upstream Language Models (Clean Canonical Names) ──────────────────")
        for short_name, m_id in primary_chat_unique:
            lines.extend([
                f"  - model_name: {short_name}",
                "    litellm_params:",
                f"      model: mistral/{m_id}",
                "      api_base: os.environ/OPENAI_COMPATIBLE_BASE_URL",
                "      api_key: os.environ/OPENAI_COMPATIBLE_API_KEY",
                "      timeout: 1800",
                "      drop_params: true",
                "",
            ])

    # 2. Other providers (clean prefixed names, no aliases)
    for prov in PROVIDERS:
        p_id = prov["id"]
        if p_id == "primary":
            continue
        models = discovered.get(p_id, [])
        if not models:
            continue

        prefix = prov["prefix"]
        env_key = prov["env_key"]
        lines.append(f"  # ── {prov['name']} ───────────────────────────────────────────────────")

        for m in models:
            clean = m.replace(f"{prefix}/", "")
            alias = f"{prefix}/{clean}"
            if alias in seen:
                continue
            seen.add(alias)

            if p_id == "kilo":
                # mistral-mapped + drop_params: strips reasoning params pre-flight
                # (openai-mapped routes 400 on LiteLLM's synthesized nested object).
                lines.extend([
                    f"  - model_name: {alias}",
                    "    litellm_params:",
                    f"      model: mistral/{clean}",
                    "      api_base: https://api.kilo.ai/api/gateway",
                    f"      api_key: os.environ/{env_key}",
                    "      timeout: 1800",
                    "      drop_params: true",
                    "",
                ])
            elif p_id == "openrouter":
                lines.extend([
                    f"  - model_name: {alias}",
                    "    litellm_params:",
                    f"      model: openrouter/{clean}",
                    f"      api_key: os.environ/{env_key}",
                    "      timeout: 1800",
                    "",
                ])
            else:
                lines.extend([
                    f"  - model_name: {alias}",
                    "    litellm_params:",
                    f"      model: {prefix}/{clean}",
                    f"      api_key: os.environ/{env_key}",
                    "      timeout: 1800",
                    "",
                ])

    # Router Settings & Fallbacks
    lines.extend([
        "# ── Router & Fallback Settings ───────────────────────────────────────────",
        "router_settings:",
        "  timeout: 1800              # 30m request timeout for large models & deep reasoning",
        "  stream_timeout: 1800       # 30m chunk timeout for slow reasoning token streams",
    ])
    if fallbacks:
        lines.append("  fallbacks:")
        lines.append("    - default:")
        for fb in fallbacks:
            lines.append(f'        - "{fb}"')
    else:
        lines.append("  fallbacks: []")

    lines.extend([
        "",
        "# ── General Settings ─────────────────────────────────────────────────────",
        "general_settings:",
        "  drop_params: true",
        "  request_timeout: 1800      # 30m global HTTP timeout",
        "",
    ])

    return "\n".join(lines), selected_default, fallbacks


def restart_gateway(repo_root: Path) -> bool:
    """Restart the llm-gateway container if running; no-op otherwise."""
    try:
        res = subprocess.run(
            ["docker", "compose", "ps", "-q", "llm-gateway"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        if res.returncode != 0 or not res.stdout.strip():
            log_info("llm-gateway container is not currently running (skipped reload).")
            return False

        subprocess.run(
            ["docker", "compose", "restart", "llm-gateway"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        log_ok("llm-gateway restarted. Changes are live!")
        return True
    except Exception as e:
        log_warn(f"Could not auto-restart llm-gateway: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Write llm-gateway config with only models that reply (keyed providers only)."
    )
    parser.add_argument("--dry-run", "-n", action="store_true", help="Preview generated config without saving.")
    parser.add_argument("--env", type=Path, default=Path(".env"), help="Path to .env (default: .env).")
    parser.add_argument("--output", type=Path, default=Path("llm-gateway/config.yaml"), help="Config destination.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    env_file = args.env if args.env.is_absolute() else (repo_root / args.env)
    output_file = args.output if args.output.is_absolute() else (repo_root / args.output)

    print(f"\n{C_BOLD}pai-stack — Model Synchronizer{C_RESET}")

    env = parse_env_file(env_file)
    for k, v in os.environ.items():
        if k not in env:
            env[k] = v

    discovered: Dict[str, List[str]] = {}

    for prov in PROVIDERS:
        active, models = discover_provider_models(prov, env)
        p_name = prov["name"]
        if active and models:
            discovered[prov["id"]] = models
            log_ok(f"{p_name:<26} → {len(models)} live models: {', '.join(models[:4])}{'...' if len(models) > 4 else ''}")
        elif active:
            log_warn(f"{p_name:<26} → key present but 0 models replied")
        else:
            log_skip(f"{p_name:<26} (no key in .env, skipped)")

    explicit_default = env.get("OPENAI_COMPATIBLE_MODEL", "").strip()
    yaml_content, selected_default, fallbacks = generate_litellm_config(
        discovered, env, explicit_default=explicit_default
    )

    print(f"\n  {C_BOLD}Active Primary Model:{C_RESET} {C_CYAN}{selected_default}{C_RESET}")
    if fallbacks:
        print(f"  {C_BOLD}Fallback Route:{C_RESET}       {C_DIM}{' → '.join(fallbacks)}{C_RESET}")

    if args.dry_run:
        print(f"\n{C_BOLD}── Preview (Dry Run) ──{C_RESET}\n{yaml_content}")
        return

    # Backup & Write
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if output_file.exists():
        shutil.copy2(output_file, output_file.with_suffix(".yaml.bak"))

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(yaml_content)

    print()
    log_ok(f"Saved configuration to {output_file.relative_to(repo_root)}")

    restart_gateway(repo_root)
    print()


if __name__ == "__main__":
    main()
