#!/usr/bin/env python3
"""
sync-models.py — Intelligent multi-provider model discovery for LiteLLM Gateway.

Scans .env for provider credentials, queries active model endpoints,
configures llm-gateway/config.yaml, and reloads the gateway seamlessly.
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
    """Post JSON with clean timeout and error handling."""
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
    except urllib.error.HTTPError as e:
        return None
    except Exception:
        return None


def probe_model_inference(base_url_or_endpoint: str, model_id: str, headers: dict, is_gemini: bool = False, timeout: int = 10) -> bool:
    """Send a tiny request to verify the model is accessible and working."""
    if is_gemini:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        if "x-goog-api-key" in headers:
            url += f"?key={headers['x-goog-api-key']}"
        payload = {
            "contents": [{"parts": [{"text": "hi"}]}],
            "generationConfig": {"maxOutputTokens": 1}
        }
        return post_json(url, payload, headers=headers, timeout=timeout) is not None
        
    # Determine URL
    if base_url_or_endpoint.endswith("/models"):
        url = base_url_or_endpoint.replace("/models", "/chat/completions")
    else:
        clean = base_url_or_endpoint.rstrip("/")
        url = f"{clean}/chat/completions"
            
    payload = {"model": model_id, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
        
    return post_json(url, payload, headers=headers, timeout=timeout) is not None


# ══════════════════════════════════════════════════════════════════════════════
# Provider Specifications & Catalogues
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
        "api_base": "https://api.kilo.ai/api/gateway",
        "prefix": "kilo",
        "curated": ["kilo-auto/free", "poolside/laguna-s-2.1:free", "stepfun/step-3.7-flash:free"],
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "env_key": "OPENROUTER_API_KEY",
        "endpoint": "https://openrouter.ai/api/v1/models",
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
        "prefix": "mistral",
        "curated": ["codestral-latest", "mistral-large-latest", "ministral-8b-latest"],
    },
    {
        "id": "groq",
        "name": "Groq",
        "env_key": "GROQ_API_KEY",
        "endpoint": "https://api.groq.com/openai/v1/models",
        "prefix": "groq",
        "curated": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "deepseek-r1-distill-llama-70b"],
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "env_key": "DEEPSEEK_API_KEY",
        "endpoint": "https://api.deepseek.com/models",
        "prefix": "deepseek",
        "curated": ["deepseek-chat", "deepseek-reasoner"],
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "endpoint": "https://api.openai.com/v1/models",
        "prefix": "openai",
        "curated": ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini"],
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "env_key": "ANTHROPIC_API_KEY",
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


def discover_provider_models(prov: dict, env: dict, include_all: bool) -> Tuple[bool, List[str]]:
    """Discover models for a given provider specification."""
    p_id = prov["id"]

    # 1. Primary local/remote OpenAI-compatible provider
    if prov.get("type") == "openai_compatible":
        base_url = env.get(prov["env_url"]) or env.get("PRIMARY_LLM_BASE_URL") or env.get("LLM_BASE_URL") or prov["default_url"]
        api_key = env.get(prov["env_key"]) or "not-needed"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key not in ("not-needed", "none", "") else {}

        clean_url = base_url.rstrip("/")
        models_url = f"{clean_url}/models" if clean_url.endswith("/v1") else f"{clean_url}/v1/models"
        data = fetch_json(models_url, headers=headers)
        if not data and not clean_url.endswith("/v1"):
            data = fetch_json(f"{clean_url}/models", headers=headers)

        if data:
            raw = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            ids = [m.get("id") if isinstance(m, dict) else str(m) for m in raw if m]
            ids = [i for i in ids if i]
            if ids:
                log_info(f"Probing {len(ids)} {prov['name']} models for liveness...")
                valid_ids = []
                for m_id in ids:
                    if probe_model_inference(models_url, m_id, headers, timeout=15):
                        valid_ids.append(m_id)
                    else:
                        print(f"    {C_DIM}○ {m_id} (probe failed){C_RESET}")
                return True, valid_ids
            return True, []
        return False, []

    # 3. Cloud / Third-Party providers
    api_key = env.get(prov["env_key"], "").strip()
    is_configured = bool(api_key) and (api_key != "not-needed")

    if not is_configured and not include_all:
        return False, []

    endpoint = prov.get("endpoint")
    curated = prov.get("curated", [])

    if endpoint and is_configured:
        headers = {"Authorization": f"Bearer {api_key}"}
        if p_id == "gemini":
            headers = {"x-goog-api-key": api_key}
            
        data = fetch_json(endpoint, headers=headers, timeout=6)
        if data:
            found_ids = []
            if p_id == "gemini" and "models" in data and isinstance(data["models"], list):
                for m in data["models"]:
                    if isinstance(m, dict) and m.get("name"):
                        methods = m.get("supportedGenerationMethods", [])
                        if "generateContent" in methods:
                            found_ids.append(m["name"].replace("models/", ""))
            elif "data" in data and isinstance(data["data"], list):
                found_ids = [m.get("id") for m in data["data"] if isinstance(m, dict) and m.get("id")]
            
            if p_id == "kilo":
                found_ids = [m for m in found_ids if m.startswith("kilo-auto/") or ":free" in m]
            elif p_id == "openrouter":
                curated_set = set(curated)
                found_ids = [m for m in found_ids if m in curated_set or m.endswith(":free")][:10]
            
            if found_ids:
                log_info(f"Probing {len(found_ids)} {prov['name']} models for liveness...")
                valid_ids = []
                for m_id in found_ids:
                    if probe_model_inference(endpoint, m_id, headers, is_gemini=(p_id=="gemini"), timeout=10):
                        valid_ids.append(m_id)
                    else:
                        print(f"    {C_DIM}○ {m_id} (probe failed){C_RESET}")
                return True, valid_ids

    return is_configured or include_all, list(curated)


def generate_litellm_config(
    discovered: Dict[str, List[str]],
    env: dict,
    explicit_default: Optional[str] = None,
) -> Tuple[str, str, List[str]]:
    """Generate LiteLLM config.yaml string, returning (yaml, selected_default, fallbacks)."""
    primary_models = discovered.get("primary", [])
    primary_chat = primary_models

    # Determine default model
    if explicit_default and explicit_default != "default":
        selected_default = explicit_default
    elif primary_chat:
        selected_default = primary_chat[0]
    else:
        selected_default = "default"

    # Determine working fallbacks
    fallbacks = []
    # 1. Any secondary local chat model from primary provider
    for sec_m in primary_chat[1:]:
        clean_sec = sec_m.rstrip("/")
        short = clean_sec.split("/")[-1] if "/" in clean_sec else clean_sec
        if short and short not in fallbacks and sec_m not in fallbacks:
            fallbacks.append(short)

    # 2. Configured cloud fallbacks
    if "kilo" in discovered and discovered["kilo"]:
        fallbacks.append("kilo/kilo-auto/free")
    if "openrouter" in discovered and discovered["openrouter"]:
        fallbacks.append("openrouter/openai/gpt-4o-mini")
    if "mistral" in discovered and discovered["mistral"]:
        fallbacks.append("mistral/codestral-latest")
    if "groq" in discovered and discovered["groq"]:
        fallbacks.append(f"groq/{discovered['groq'][0]}")
    if "deepseek" in discovered and discovered["deepseek"]:
        fallbacks.append("deepseek/deepseek-chat")

    # Build YAML
    lines = [
        "# LiteLLM Proxy Configuration for pai-stack",
        "# Centralized LLM gateway managing all model routing, fallbacks, and provider credentials.",
        "",
        "model_list:",
        "  # ── Primary Default Routing ───────────────────────────────────────────",
        "  - model_name: default",
        "    litellm_params:",
        f"      model: openai/{selected_default}",
        "      api_base: os.environ/OPENAI_COMPATIBLE_BASE_URL",
        "      api_key: os.environ/OPENAI_COMPATIBLE_API_KEY",
        "      timeout: 1800",
        "      drop_params: true",
        "",
    ]

    seen = {"default"}

    # 1. Primary language models (clean short canonical names, no duplicates)
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
                f"      model: openai/{m_id}",
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
                lines.extend([
                    f"  - model_name: {alias}",
                    "    litellm_params:",
                    f"      model: openai/{clean}",
                    "      api_base: https://api.kilo.ai/api/gateway",
                    f"      api_key: os.environ/{env_key}",
                    "      timeout: 1800",
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
    """Seamlessly restart the llm-gateway container if Docker is available."""
    try:
        # Check if container is running first
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
        description="Auto-discover models from local & cloud providers and configure llm-gateway."
    )
    parser.add_argument("--all", "-a", action="store_true", help="Include templates for all cloud providers.")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Preview generated config without saving.")
    parser.add_argument("--no-restart", action="store_true", help="Do not restart llm-gateway after updating config.")
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
        active, models = discover_provider_models(prov, env, include_all=args.all)
        p_name = prov["name"]
        if active and models:
            discovered[prov["id"]] = models
            log_ok(f"{p_name:<26} → {len(models)} models: {', '.join(models[:4])}{'...' if len(models) > 4 else ''}")
        elif active:
            log_warn(f"{p_name:<26} → configured but unreachable / 0 models returned")
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

    # Auto-restart gateway
    if not args.no_restart:
        restart_gateway(repo_root)
    print()


if __name__ == "__main__":
    main()
