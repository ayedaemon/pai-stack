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
import concurrent.futures
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("sync-models")

# ── Chat-capability gate ────────────────────────────────────────────────────
# The liveness probe asks `/chat/completions` and accepts any 200 carrying text
# (see response_has_reply_text). That is too weak to tell a chat model from a
# non-chat one: FIM endpoints answer a chat-shaped POST with a `text` field,
# and guardrail classifiers answer with a label string. Both cleared the probe
# and reached the model_list — and because they have no reasoning phase, FIM
# was always the fastest probe, so it won the `default` pin outright. Every
# pattern here is matched against the model id with `:` in the delimiter set,
# since free-tier ids carry a `:free` suffix (…-safety:free).
NON_CHAT_PATTERNS = (
    r"(^|[-_/:])fim([-_/:]|$)",                       # fill-in-the-middle
    r"embed",                                          # embedding / bi-encoder
    r"rerank",
    r"(^|[-_/:])(guard|guardrail|moderation|safety)([-_/:]|$)",
    r"whisper|transcribe|(^|[-_/:])tts([-_/:]|$)|speech|(^|[-_/:])audio([-_/:]|$)",
    r"(^|[-_/:])(ocr|detection|segmentation|upscal|inpaint)([-_/:]|$)",
)
_NON_CHAT_RE = re.compile("|".join(NON_CHAT_PATTERNS), re.IGNORECASE)

# Provider meta-routers: "pick me any cheap model" aliases, not models.
# The liveness probe talks to the provider's API directly, where they answer
# fine. Production traffic instead goes through LiteLLM's provider handler,
# which cannot resolve them — `openrouter/free` returns
# 404 "No endpoints available for openrouter/free". The probe validates a
# different path than the one requests actually take, so this class has to be
# named explicitly. `kilo/openrouter/free` is NOT here: it resolves through
# the Kilo gateway and works on both paths.
META_ROUTER_IDS = frozenset({"openrouter/free"})

# ── Route timeouts ──────────────────────────────────────────────────────────
# An overloaded free-tier endpoint frequently *holds* the socket rather than
# refusing it. With a 30m ceiling a 503 that should fail fast instead stalls,
# and with several such routes in the chain the request never returns. Free
# routes get a short ceiling; paid routes keep the long one for deep reasoning.
LONG_ROUTE_TIMEOUT = 1800
FREE_ROUTE_TIMEOUT = 120

# ── Explicit `default` pin ──────────────────────────────────────────────────
# The pin is what both Hermes and DSH actually call. It is latency rank 1 —
# the fastest model that answered a multi-turn probe — and the fallback chain
# is rank 2..n from the SAME ordering, so the two can never disagree.
#
# This was explicitly pinned via a preference list before, because fastest-
# probe once selected a fill-in-the-middle endpoint. That failure mode is
# gone: the chat-capability gate filters non-chat models pre-probe and the
# error-envelope check rejects 200-with-error bodies, so latency now measures
# models that can actually serve an agent turn. Per-deployment override is
# still available via PAI_DEFAULT_MODEL in .env.
#
# Trade-off to keep in mind: the pin now re-rolls on `make sync` whenever the
# fastest responder changes, so expect that one line to diff.


def is_chat_candidate(model_id: str) -> bool:
    """False for models that cannot serve a chat/tool-calling agent turn."""
    if model_id in META_ROUTER_IDS:
        return False
    return not _NON_CHAT_RE.search(model_id)


def route_timeout(*ids: str) -> int:
    """Short ceiling for :free routes, long ceiling for everything else."""
    return FREE_ROUTE_TIMEOUT if any(i.endswith(":free") for i in ids) else LONG_ROUTE_TIMEOUT


def setup_logging(debug: bool = False) -> None:
    """Configure stdlib logging: INFO by default, DEBUG with --debug."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False


# Terminal colors (banner headers only — log lines go through logging)
C_BOLD = "\033[1m"
C_RESET = "\033[0m"


def log_ok(msg: str):
    logger.info("✓ %s", msg)


def log_info(msg: str):
    logger.info("%s", msg)


def log_skip(msg: str):
    # Skipped providers (no key) are noise by default — debug only.
    logger.debug("○ %s", msg)


def log_warn(msg: str):
    logger.warning("%s", msg)


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
    """Post JSON; return the parsed body, including on HTTP error.

    An HTTPError body is returned rather than discarded. A 400 is the whole
    signal for the reasoning-echo family (their error body says exactly
    which parameter is missing), and swallowing it here would make those
    models vanish from the pool with no explanation. `response_has_reply_text`
    rejects any body carrying an `error` key, so this does not let failures
    through as successes — it just makes the drop legible.
    """
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
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"error": f"HTTP {e.code}"}
    except Exception:
        return None


def agent_turn_messages() -> list:
    """A two-turn conversation shaped like a real agent request.

    The second message is a PRIOR ASSISTANT TURN with no `reasoning_content`.
    That is exactly what Hermes and DSH send on every turn after the first:
    they replay their own assistant messages (and tool results) back to the
    model, and neither preserves reasoning traces.

    A single-turn probe cannot see this class of failure. Some model families
    require the reasoning of every earlier assistant message to be echoed
    back verbatim and 400 otherwise::

        Missing required parameter: 'messages[7].reasoning_content'. This
        model needs the reasoning of every earlier assistant message: send
        back the 'reasoning_content' returned with that message.

    Those models pass a one-turn liveness probe perfectly, then hard-fail on
    the second turn of every real conversation — burning fallback depth each
    time. Probing multi-turn makes the filter reflect the actual workload
    instead of the shape of the probe.
    """
    return [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "again"},
    ]


def probe_openai_chat(chat_base: str, model_id: str, api_key: str, timeout: int = 10) -> Optional[dict]:
    """Tiny MULTI-TURN chat completion against any OpenAI-compatible endpoint.

    Deliberately multi-turn — see agent_turn_messages for why a one-turn probe
    lets reasoning-echo models through.
    """
    url = f"{chat_base.rstrip('/')}/chat/completions"
    payload = {"model": model_id, "messages": agent_turn_messages()}
    if "o1" in model_id or "o3" in model_id:
        payload["max_completion_tokens"] = 40
    else:
        payload["max_tokens"] = 40
    headers = {"Authorization": f"Bearer {api_key}"}
    return post_json(url, payload, headers=headers, timeout=timeout)


def probe_gemini(model_id: str, api_key: str, timeout: int = 10) -> Optional[dict]:
    """Tiny MULTI-TURN generateContent call (Gemini has no OpenAI-compatible chat shape here)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": "hi"}]},
            {"role": "model", "parts": [{"text": "hello"}]},
            {"role": "user", "parts": [{"text": "again"}]},
        ],
        "generationConfig": {"maxOutputTokens": 40},
    }
    return post_json(url, payload, headers={"x-goog-api-key": api_key}, timeout=timeout)


def probe_anthropic(model_id: str, api_key: str, timeout: int = 10) -> Optional[dict]:
    """Tiny MULTI-TURN Messages call (Anthropic has no /chat/completions shape)."""
    url = "https://api.anthropic.com/v1/messages"
    payload = {
        "model": model_id,
        "max_tokens": 40,
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "again"},
        ],
    }
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    return post_json(url, payload, headers=headers, timeout=timeout)


def model_replies(prov: dict, model_id: str, api_key: str) -> Optional[dict]:
    """Route the liveness probe to the right API shape for this provider."""
    p_id = prov["id"]
    if p_id == "gemini":
        return probe_gemini(model_id, api_key)
    if p_id == "anthropic":
        return probe_anthropic(model_id, api_key)
    return probe_openai_chat(prov["chat_base"], model_id, api_key)


def provider_error_detail(data: Optional[dict]) -> Optional[str]:
    """Return a human-readable reason if `data` is an error envelope, else None.

    Providers disagree on the envelope, and every disagreement is a way for a
    dead model to look alive:

    - Kilo / OpenAI / Anthropic / Gemini: ``{"error": {...}}``
    - Mistral native: ``{"object": "error", "message": ..., "code": ...,
      "raw_status_code": 403}`` — no top-level ``error`` key at all, so a check
      for ``data["error"]`` alone lets it through
    - some gateways: ``{"success": false, ...}``

    Missing any one of these routes the body to the benefit-of-the-doubt branch
    at the end of response_has_reply_text, which is how retired models and
    Labs models this account cannot enable survive the probe and land in the
    pool. Match the shapes, not one of them.
    """
    if not isinstance(data, dict):
        return None
    err = data.get("error")
    if err:
        if isinstance(err, dict):
            return str(err.get("message") or err)
        return str(err)
    if str(data.get("object", "")).lower() == "error":
        return str(data.get("message") or "provider error envelope")
    status = data.get("raw_status_code")
    if isinstance(status, int) and status >= 400:
        return str(data.get("message") or f"HTTP {status}")
    if data.get("success") is False:
        return str(data.get("message") or "provider reported failure")
    return None


def response_has_reply_text(data: Optional[dict]) -> bool:
    """True only if the probe response carries an actual reply.

    A bare HTTP 200 is not enough: some Gemini variants (transcribe, TTS,
    robotics, heavy-thinking) return 200 with empty content and no text
    parts. Those count as no-reply and are dropped.

    An HTTP 200 carrying an error envelope is also not a reply. The Kilo
    gateway returns 200 with the failure in the body when the upstream
    provider is down::

        {"id": "gen-…",
         "error": {"message": "Upstream error from Nvidia: Service temporarily
                             overloaded", "code": 503,
                   "metadata": {"error_type": "provider_overloaded"}}}

    That body has no `choices` / `content` / `candidates` key, so it used to
    fall through to the benefit-of-the-doubt branch at the end of this
    function and score the model as ALIVE. Worse, it scored as the FASTEST
    model in the pool: a provider that refuses instantly answers in ~0.5s,
    which beats every model that actually generated tokens. So permanently-
    failing routes were being promoted to the top of the fallback chain on
    every `make sync` — the sync script was manufacturing the exact 503s it
    was supposed to be filtering out. See provider_error_detail for the
    envelope shapes.
    """
    if not data:
        return False
    # `error: null` is a common success shape — only a truthy value is a failure.
    if provider_error_detail(data):
        return False
    try:
        if "choices" in data:  # OpenAI-compatible
            choice = data["choices"][0]
            msg = choice.get("message", {})
            if msg.get("content") or choice.get("text"):
                return True
            # Structured-only reply (e.g. tool calls) still counts as alive.
            if msg.get("tool_calls") or msg.get("function_call"):
                return True
            # Reasoning-only reply still counts as alive. Reasoning models
            # (DeepSeek-R1/Qwen3/Spark via LM Studio etc.) return 200 with
            # content="" + reasoning_content when max_tokens is consumed by
            # thinking (finish_reason=length). The server + model work;
            # the probe budget was just too small for content.
            if msg.get("reasoning_content") or msg.get("reasoning") or msg.get("thought"):
                return True
            return False
        if "content" in data:  # Anthropic
            parts = data["content"]
            if isinstance(parts, list):
                return any(isinstance(p, dict) and p.get("text") for p in parts)
            return False
        if "candidates" in data:  # Gemini
            for cand in data["candidates"]:
                parts = cand.get("content", {}).get("parts", [])
                if any(isinstance(p, dict) and p.get("text") for p in parts):
                    return True
            return False
    except Exception:
        return False
    # Unknown shape but valid 200 JSON — give it the benefit of the doubt.
    # Only after provider_error_detail has cleared the body: that check is the
    # ONLY thing standing between an unrecognised error envelope and a dead
    # model being recorded as live (and fast). Unrecognised-but-not-an-error
    # stays allowed so genuinely novel success shapes are not over-filtered.
    return provider_error_detail(data) is None


def extract_response_text(data: Optional[dict]) -> str:
    """Extract the full human-readable reply text from a provider response."""
    if not data:
        return ""
    try:
        if "choices" in data:
            msg = data["choices"][0].get("message", {})
            content = msg.get("content", "")
            if content:
                return content
            # Reasoning-only reply — surface thinking text for the log line.
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or msg.get("thought") or ""
            if isinstance(reasoning, dict):
                reasoning = reasoning.get("content") or reasoning.get("text") or str(reasoning)
            return str(reasoning) if reasoning else str(data)
        if "content" in data:
            parts = data["content"]
            if isinstance(parts, list) and parts:
                return str(parts[0].get("text", ""))
        if "candidates" in data:
            parts = data["candidates"][0].get("content", {}).get("parts", [])
            if parts:
                return str(parts[0].get("text", ""))
    except Exception:
        pass
    return str(data)


# ══════════════════════════════════════════════════════════════════════════════
# Providers: key in .env → list ALL models → probe each → keep repliers.
# No curated allowlists — if a model is exhausted, it simply won't be listed
# the next time the script runs.
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
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "env_key": "OPENROUTER_API_KEY",
        "endpoint": "https://openrouter.ai/api/v1/models",
        "chat_base": "https://openrouter.ai/api/v1",
        "prefix": "openrouter",
    },
    {
        "id": "mistral",
        "name": "Mistral AI",
        "env_key": "MISTRAL_API_KEY",
        "endpoint": "https://api.mistral.ai/v1/models",
        "chat_base": "https://api.mistral.ai/v1",
        "prefix": "mistral",
    },
    {
        "id": "groq",
        "name": "Groq",
        "env_key": "GROQ_API_KEY",
        "endpoint": "https://api.groq.com/openai/v1/models",
        "chat_base": "https://api.groq.com/openai/v1",
        "prefix": "groq",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "env_key": "DEEPSEEK_API_KEY",
        "endpoint": "https://api.deepseek.com/models",
        "chat_base": "https://api.deepseek.com/v1",
        "prefix": "deepseek",
    },
    {
        "id": "nvidia",
        "name": "NVIDIA NIM",
        "env_key": "NVIDIA_API_KEY",
        "endpoint": "https://integrate.api.nvidia.com/v1/models",
        "chat_base": "https://integrate.api.nvidia.com/v1",
        "prefix": "nvidia",
        # OpenAI-compatible; explicit api_base (LiteLLM's built-in nvidia/ routing
        # 404s on this endpoint — verified via probe).
        "api_base": "https://integrate.api.nvidia.com/v1",
        # Model ids already carry vendor prefixes (nvidia/, meta/, google/...) —
        # strip the provider's own prefix for clean aliases.
        "strip_prefix": "nvidia/",
    },
    {
        # Ollama Cloud is OpenAI-compatible at ollama.com/v1 (no cloud.ollama.com).
        # api_base → emitted as openai/ mapping with explicit base in the config.
        "id": "ollama_cloud",
        "name": "Ollama Cloud",
        "env_key": "OLLAMA_CLOUD_API_KEY",
        "endpoint": "https://ollama.com/v1/models",
        "chat_base": "https://ollama.com/v1",
        "prefix": "ollama",
        "api_base": "https://ollama.com/v1",
    },
    {
        # Aion Labs (api.aionlabs.ai) — OpenAI-compatible; model ids carry the
        # aion-labs/ vendor prefix, so openai/ mapping keeps them intact.
        "id": "aion",
        "name": "Aion Labs",
        "env_key": "AION_LABS_API_KEY",
        "endpoint": "https://api.aionlabs.ai/v1/models",
        "chat_base": "https://api.aionlabs.ai/v1",
        "prefix": "aion",
        "api_base": "https://api.aionlabs.ai/v1",
        # Model ids carry the aion-labs/ vendor prefix — strip it for aliases.
        "strip_prefix": "aion-labs/",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "endpoint": "https://api.openai.com/v1/models",
        "chat_base": "https://api.openai.com/v1",
        "prefix": "openai",
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "endpoint": "https://api.anthropic.com/v1/models",
        "prefix": "anthropic",
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "env_key": "GEMINI_API_KEY",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models",
        "prefix": "gemini",
    },
    {
        "id": "zen",
        "name": "OpenCode Zen",
        "env_key": "",
        "endpoint": "https://opencode.ai/zen/v1/models",
        "chat_base": "https://opencode.ai/zen/v1",
        "prefix": "zen",
    },
]


def parse_listing(p_id: str, data: dict) -> List[str]:
    """Extract all model ids from a /models response."""
    found_ids: List[str] = []
    if p_id == "gemini" and isinstance(data.get("models"), list):
        for m in data["models"]:
            if isinstance(m, dict) and m.get("name") and "generateContent" in m.get("supportedGenerationMethods", []):
                found_ids.append(m["name"].replace("models/", ""))
    elif isinstance(data.get("data"), list):
        found_ids = [m.get("id") for m in data["data"] if isinstance(m, dict) and m.get("id")]
    return found_ids


def auth_headers(prov: dict, api_key: str) -> dict:
    if prov["id"] == "gemini":
        return {"x-goog-api-key": api_key}
    if prov["id"] == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    if prov["id"] == "zen":
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def probe_candidates(prov: dict, candidates: List[str], api_key: str) -> Dict[str, float]:
    """Probe candidates; return {model_id: probe latency in seconds} for repliers.

    Non-chat models are dropped *before* probing. They must never reach a
    latency measurement: the `default` pin and the fallback order are both
    derived from probe latency, and a non-chat endpoint that answers the probe
    shape is by construction the fastest thing in the pool (no reasoning
    phase, no tool-call parsing), so letting one through corrupts the ranking
    that everything else depends on.

    Per-model chatter (reply text, upstream errors, silent drops) is DEBUG-only.
    The default run reports what responded and why a model was chosen, not a
    transcript of every probe — a 400-model provider would otherwise bury that
    under hundreds of lines nobody reads.
    """
    chat_candidates = [m for m in candidates if is_chat_candidate(m)]
    dropped = [m for m in candidates if not is_chat_candidate(m)]
    if dropped:
        logger.debug("⊘ %s → %d non-chat model(s) filtered pre-probe: %s",
                     prov["name"], len(dropped), ", ".join(sorted(dropped)))
    if not chat_candidates:
        return {}

    logger.debug("Probing %d %s models for liveness...", len(chat_candidates), prov["name"])
    live: Dict[str, float] = {}

    def check_model(m_id):
        start = time.monotonic()
        response = model_replies(prov, m_id, api_key)
        return m_id, response, time.monotonic() - start

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_model, m_id): m_id for m_id in chat_candidates}
        for future in concurrent.futures.as_completed(futures):
            m_id, response, elapsed = future.result()
            if response and response_has_reply_text(response):
                live[m_id] = elapsed
                reply = extract_response_text(response)
                logger.debug("✓ %s → %s (%.2fs)", m_id, reply, elapsed)
            elif response and provider_error_detail(response):
                # 200 + error envelope: the gateway is up, the upstream is not.
                # Worth DEBUG — this is the signal that a provider is degraded,
                # not that a model id is wrong.
                logger.debug("⚠ %s → upstream error: %s", m_id, provider_error_detail(response))
            else:
                # No reply text (or HTTP error) — debug-only, use --debug to list.
                logger.debug("○ %s (no reply text, dropped)", m_id)
    return live


def discover_primary(prov: dict, env: dict) -> Tuple[bool, Dict[str, float], Optional[str]]:
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
        # Distinguish "we could not reach a box that IS configured" from "no
        # key, nothing to do". Returning False here used to land in the
        # no-key branch, so a remote OpenAI-compatible box that was offline or
        # asleep silently vanished from the run — reported as "(no key in
        # .env, skipped)" when the key and URL were both set. The provider just
        # disappeared from the config with no explanation.
        return False, {}, (
            f"configured but unreachable — GET {models_url} failed "
            f"(DNS ok, connection refused/timed out?)"
        )

    raw = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    ids = [m.get("id") if isinstance(m, dict) else str(m) for m in raw if m]
    ids = [i for i in ids if i]
    if not ids:
        return True, {}, None
    return True, probe_candidates(prov | {"chat_base": clean_url}, ids, api_key), None


def discover_provider_models(prov: dict, env: dict) -> Tuple[bool, Dict[str, float], Optional[str]]:
    """List + probe one provider.

    Returns (active, live, note) where `note` explains an inactive provider.
    The note exists so "not configured" and "configured but broken" stay
    distinguishable in the run summary — a provider that vanished because its
    host was down looks identical to one you never asked for, and that hides
    the fact that the gateway config just quietly lost a whole upstream.
    """
    if prov.get("type") == "openai_compatible":
        return discover_primary(prov, env)

    api_key = env.get(prov["env_key"], "").strip() if prov.get("env_key") else ""
    if prov.get("env_key") and (not api_key or api_key == "not-needed"):
        return False, {}, "no key in .env"

    data = fetch_json(prov["endpoint"], headers=auth_headers(prov, api_key), timeout=6)
    if not data:
        return False, {}, f"GET {prov['endpoint']} failed (unreachable or rejected)"
    candidates = parse_listing(prov["id"], data)
    if not candidates:
        return True, {}, None
    return True, probe_candidates(prov, candidates, api_key), None


def latency_rank(
    alias_params: Dict[str, List[str]],
    alias_latency: Dict[str, float],
) -> List[str]:
    """Order every live model fastest-probe-first; ties broken alphabetically.

    This drives BOTH the `default` pin (rank 1) and the fallback chain (rank
    2..n), so the two can never disagree about what "first" means.

    An earlier version interleaved providers by fractional key instead, on the
    theory that fastest-first stampedes: when rank 1 is overloaded the whole
    fleet moves to rank 2 together and overloads it. Latency rank is used
    deliberately now, for two reasons:

      - It subsumes most of that protection. The providers that actually
        overload are the slow ones — the free-tier Nvidia NIMs answer in
        2-4s and the Nemotron Nemotron-class models sit at the tail, so the
        chain only reaches them after everything usable has already failed.
      - The stampede mechanism is separately bounded now. Cooldown
        (`allowed_fails_policy` + `cooldown_time`) benches a deployment that
        is actually returning 503, so a sick upstream stops absorbing traffic
        instead of being re-tried by the whole fleet every request.

    The chat-capability gate and the error-envelope check are what make the
    ranking trustworthy at all: before them, the fastest probe was reliably a
    fill-in-the-middle endpoint or an outright 503, both of which this order
    would have promoted to rank 1.
    """
    return sorted(
        alias_params,
        key=lambda a: (alias_latency.get(a, float("inf")), a.casefold(), a),
    )


def choose_default_pin(
    alias_params: Dict[str, List[str]],
    fallback_order: List[str],
    env: dict,
) -> Tuple[Optional[str], str]:
    """Pick the model both agents actually call (`model: default`).

    Returns (alias, reason) so the run can report *why* this model won — the
    selection is the one decision in this script that is not self-evident from
    the generated config.

    Resolution order:
      1. PAI_DEFAULT_MODEL from .env, if it is in the live pool. An explicit
         per-deployment choice always beats the ranking.
      2. Rank 1 of `fallback_order`, i.e. the fastest model that actually
         answered a multi-turn probe.

    The pin and the chain are now one ordering (latency_rank), so `default`
    is always chain rank 1 and the two can never disagree. An intermediate
    version pinned explicitly via DEFAULT_PIN_PREFERENCE instead, to stop the
    pin re-rolling on every sync; the chat-capability gate and the
    error-envelope check removed the failure that motivated it (a
    fill-in-the-middle endpoint winning rank 1), so speed is safe to trust
    again. Consequence to be aware of: the pin now changes whenever the
    fastest responder changes, which is a real diff on `make sync`.
    """
    live = set(alias_params)
    if not live:
        return None, "no live models"

    override = (env.get("PAI_DEFAULT_MODEL") or "").strip()
    if override:
        if override in live:
            rank = fallback_order.index(override) + 1 if override in fallback_order else None
            return override, (
                "PAI_DEFAULT_MODEL from .env (explicit override)"
                + (f"; chain rank {rank}" if rank else "")
            )
        logger.warning(
            "PAI_DEFAULT_MODEL=%r is not in the live pool — falling back to "
            "latency rank. Model names in .env use the gateway alias "
            "(e.g. 'mistral/codestral-2508').", override,
        )

    if fallback_order:
        chosen = fallback_order[0]
        runner_up = fallback_order[1] if len(fallback_order) > 1 else None
        why = "latency rank 1 — fastest model that answered the multi-turn probe"
        if runner_up:
            why += f" (ahead of {runner_up})"
        return chosen, why
    return None, "no live models"


def generate_litellm_config(
    discovered: Dict[str, Dict[str, float]],
    env: dict,
) -> Tuple[str, List[str], List[str]]:
    """Generate LiteLLM config.yaml string with all discovered models as independent entries.

    `discovered` maps provider id → {model_id: probe latency in seconds}.

    Returns (config_text, ordered_aliases, fallback_order):
    - ordered_aliases is alphabetically sorted (case-insensitive) and drives
      the `model_list` emission order and the DSH seed model list, so those
      stay deterministic across runs.
    - fallback_order is latency-ranked (see latency_rank): fastest
      multi-turn probe first. It drives BOTH the `default` pin (rank 1) and
      the router fallback chain (rank 2..n), so the two cannot disagree.
    """
    lines = [
        "# LiteLLM Proxy Configuration for pai-stack",
        "# Centralized LLM gateway managing all model routing and provider credentials.",
        "# NOTE: routes use mistral/ provider mapping (not openai/) so reasoning params",
        "# are stripped pre-flight — see note at primary-models section below.",
        "# NOTE: model entries are alphabetically sorted (case-insensitive) — do not",
        "# hand-reorder; re-running scripts/sync-models.py regenerates this order.",
        "# NOTE: latency-ranked. `default` is rank 1 and the chain is rank 2..n,",
        "# from one ordering, so they never disagree. Slow/overloaded free-tier",
        "# upstreams sink to the tail on their own; cooldown (below) stops a",
        "# genuinely 5xx-ing deployment being re-tried by every request.",
        "# NOTE: router has a circuit breaker (allowed_fails/cooldown_time) so a model",
        "# that is actually down is benched instead of retried on every request.",
        "",
        "model_list:",
    ]

    seen = set()
    alias_params: Dict[str, List[str]] = {}
    alias_section: Dict[str, str] = {}
    alias_latency: Dict[str, float] = {}
    alias_provider: Dict[str, str] = {}

    PRIMARY_SECTION = "  # ── Upstream Language Models (Clean Canonical Names) ──────────────────"

    # 1. Primary language models (clean short canonical names, no duplicates)
    # NOTE (2026-09-25): primary routes are mistral-mapped (not openai/) + drop_params
    # because our LiteLLM synthesizes a conflicting nested `reasoning` object from ANY
    # `reasoning_effort` value, and strict OpenAI-compatible upstreams 400 on the pair.
    # The mistral provider spec excludes reasoning params so they are stripped pre-flight
    # (verified live: 200 + forced tool-call + SSE streaming).
    primary_models = discovered.get("primary", {})
    primary_chat_unique = []
    for m_id, latency in primary_models.items():
        clean_id = m_id.rstrip("/")
        short_name = clean_id.split("/")[-1] if "/" in clean_id else clean_id
        if not short_name:
            short_name = m_id.strip("/") or "primary-model"
        if short_name not in seen:
            seen.add(short_name)
            primary_chat_unique.append((short_name, m_id, latency))

    for short_name, m_id, latency in primary_chat_unique:
        block = [
            f"      model: mistral/{m_id}",
            "      api_base: os.environ/OPENAI_COMPATIBLE_BASE_URL",
            "      api_key: os.environ/OPENAI_COMPATIBLE_API_KEY",
            f"      timeout: {route_timeout(m_id, short_name)}",
            "      drop_params: true",
        ]
        alias_params.setdefault(short_name, block)
        alias_section.setdefault(short_name, PRIMARY_SECTION)
        alias_latency.setdefault(short_name, latency)
        alias_provider.setdefault(short_name, "primary")

    # 2. Other providers (clean prefixed names, no aliases) — collect only.
    for prov in PROVIDERS:
        p_id = prov["id"]
        if p_id == "primary":
            continue
        models = discovered.get(p_id, {})
        if not models:
            continue

        prefix = prov["prefix"]
        env_key = prov["env_key"]
        section = f"  # ── {prov['name']} ───────────────────────────────────────────────────"

        strip_prefix = prov.get("strip_prefix")  # ids carrying their own vendor prefix (nvidia/, aion-labs/)

        for m, latency in models.items():
            clean = m.replace(strip_prefix, "") if strip_prefix else m.replace(f"{prefix}/", "")
            alias = f"{prefix}/{clean}"
            if alias in seen:
                continue
            seen.add(alias)

            if p_id == "kilo":
                block = [
                    f"      model: mistral/{clean}",
                    "      api_base: https://api.kilo.ai/api/gateway",
                    f"      api_key: os.environ/{env_key}",
                    f"      timeout: {route_timeout(alias)}",
                    "      drop_params: true",
                ]
            elif p_id == "openrouter":
                block = [
                    f"      model: openrouter/{clean}",
                    f"      api_key: os.environ/{env_key}",
                    f"      timeout: {route_timeout(alias)}",
                    "      drop_params: true",
                ]
            elif p_id == "nvidia":
                # NVIDIA NIM provider prefix is nvidia_nim/ (bare nvidia/
                # is not a LiteLLM provider and fails router init with
                # "LLM Provider NOT provided"). Alias keeps the nvidia/
                # gateway name; only the litellm routing model changes.
                block = [
                    f"      model: nvidia_nim/{clean}",
                    f"      api_key: os.environ/{env_key}",
                    f"      timeout: {route_timeout(alias)}",
                    "      drop_params: true",
                ]
            elif p_id == "zen":
                block = [
                    f"      model: openai/{clean}",
                    "      api_base: https://opencode.ai/zen/v1",
                    f"      timeout: {route_timeout(alias)}",
                    "      drop_params: true",
                ]
            elif prov.get("api_base"):
                # OpenAI-compatible providers whose ids carry vendor prefixes
                # (nvidia/nemotron-*, aion-labs/*, ollama cloud) — openai/ mapping
                # with explicit api_base keeps the id intact. Use the full id `m`
                # for routing; `clean` is only used for the alias name above.
                block = [
                    f"      model: openai/{m}",
                    f"      api_base: {prov['api_base']}",
                    f"      api_key: os.environ/{env_key}",
                    f"      timeout: {route_timeout(alias)}",
                    "      drop_params: true",
                ]
            else:
                # Vendor-native SDK routes (mistral, groq, deepseek, openai).
                # drop_params is emitted here too: the Sep-25 fix relies on
                # reasoning params being stripped pre-flight, and leaving this
                # branch without it made the protection conditional on which
                # model happened to win the pin.
                block = [
                    f"      model: {prefix}/{clean}",
                    f"      api_key: os.environ/{env_key}",
                    f"      timeout: {route_timeout(alias)}",
                    "      drop_params: true",
                ]
            alias_params.setdefault(alias, block)
            alias_section.setdefault(alias, section)
            alias_latency.setdefault(alias, latency)
            alias_provider.setdefault(alias, p_id)

    # 3. Two orders from here on:
    # - model_list emission stays alphabetically sorted (case-insensitive) so
    #   the file diff and the DSH seed stay deterministic across runs.
    # - the fallback chain is latency-ranked, fastest multi-turn probe first.
    ordered_aliases: List[str] = sorted(alias_params.keys(), key=lambda a: (a.casefold(), a))
    fallback_order: List[str] = latency_rank(alias_params, alias_latency)

    # Emit model_list in that sorted order; provider comment follows the entry
    # (emitted once per contiguous provider run) for readability only.
    last_section: Optional[str] = None
    for alias in ordered_aliases:
        section = alias_section.get(alias)
        if section and section != last_section:
            lines.append(section)
            last_section = section
        lines.extend([
            f"  - model_name: {alias}",
            "    litellm_params:",
            *alias_params[alias],
            "",
        ])

    # 4. Default alias — Hermes/DSH `model: default` must always resolve.
    # The pin is explicit, not the head of the fallback order: it used to be
    # whichever model probed fastest, which re-rolled on every sync and (before
    # the chat-capability gate) selected a fill-in-the-middle endpoint that
    # answered the probe shape faster than any real chat model because it has no
    # reasoning phase. Pinned last, outside the sorted order.
    pinned, pin_reason = choose_default_pin(alias_params, fallback_order, env)
    if pinned:
        counts: Dict[str, int] = {}
        for alias in fallback_order:
            pid = alias_provider.get(alias, "?")
            counts[pid] = counts.get(pid, 0) + 1
        # Report the one decision this run makes that the generated YAML does
        # not explain on its own: which model `default` resolves to, and why.
        logger.info("")
        log_ok(f"default → {pinned}")
        log_info(f"  why    {pin_reason}")
        log_info(
            f"  scope  called directly by Hermes and DSH; excluded from its own "
            f"chain, which covers the other {len(fallback_order) - 1}"
        )
        log_info(
            f"  chain  {len(fallback_order)} models, latency-ranked, across "
            f"{len(counts)} provider(s) — "
            + ", ".join(f"{k}×{v}" for k, v in sorted(counts.items()))
        )
        log_info(
            f"  fall  default + \"*\" generic chain, plus context-window and "
            f"content-policy variants (same order)"
        )
        logger.info("")
        lines.append("  # ── Default (latency rank 1; rest via the fallback chain) ──")
        lines.extend([
            "  - model_name: default",
            "    litellm_params:",
            *alias_params[pinned],
            "",
        ])
    else:
        log_warn("no live models — gateway config will have no `default` pin")

    # Router Settings — latency-ranked failover, every mechanism available.
    # Without a cooldown policy LiteLLM has no memory: a model that has been
    # 503-ing for hours is retried on every single request.
    #
    # `allowed_fails_policy` (named exception types) — NOT bare `allowed_fails`.
    # `_is_allowed_fails_set_on_router()` only returns True when the value
    # differs from `litellm.allowed_fails`, whose default is 3. Setting
    # `allowed_fails: 3` therefore routes into the error-rate branch instead,
    # and that branch is gated on `not is_single_deployment_model_group`. Every
    # model_name in this file maps to exactly ONE deployment, so the gate can
    # never pass and `allowed_fails: 3` is a silent no-op — verified live, the
    # cooldown list stayed empty across a burst of 503s. A named
    # exception-type policy is the documented override
    # (`_has_explicit_allowed_fails_policy_for_exception`) and skips both gates.
    #
    # The fallbacks maps below cover `default` AND the generic "*" key, so a
    # caller that names a specific alias still gets the chain behind it.
    lines.extend([
        "# ── Router Settings ─────────────────────────────────────────────────────",
        "router_settings:",
        "  timeout: 1800              # 30m request timeout for large models & deep reasoning",
        "  stream_timeout: 1800       # 30m chunk timeout for slow reasoning token streams",
        "  num_retries: 2             # retries within a deployment before failing over",
        "  # LiteLLM defaults max_fallbacks to 5 (ROUTER_MAX_FALLBACKS), which is",
        "  # far shorter than this chain — the walk would be abandoned mid-list.",
        "  max_fallbacks: 60          # >= chain length, so every link is reachable",
        "  cooldown_time: 60          # bench length — a failing model rests 60s",
        "  retry_after: 5             # honour upstream Retry-After, else wait 5s",
        "  # Named-exception cooldown policy — see the note in sync-models.py.",
        "  # Do NOT replace this with a bare `allowed_fails:` scalar: it is a no-op",
        "  # on a one-deployment-per-model config.",
        "  allowed_fails_policy:",
        "    ServiceUnavailableErrorAllowedFails: 3   # 503 (overloaded upstream)",
        "    InternalServerErrorAllowedFails: 3",
        "    BadGatewayErrorAllowedFails: 3           # 502 (upstream refused)",
        "    TimeoutErrorAllowedFails: 5",
        "    RateLimitErrorAllowedFails: 5            # 429",
    ])
    if pinned and fallback_order:
        # `default` and the chain come from ONE ordering, so the pin is always
        # rank 1 and can never disagree with the chain. A PAI_DEFAULT_MODEL
        # override that names a non-rank-1 model re-heads the ordering rather
        # than being demoted — an explicit choice should win, but the emitted
        # chain must still be the ordered remainder.
        if fallback_order[0] != pinned:
            logger.info(
                "  note   PAI_DEFAULT_MODEL re-ordered to rank 1; remaining %d "
                "chain links keep their latency order", len(fallback_order) - 1,
            )
            fallback_order = [pinned] + [a for a in fallback_order if a != pinned]
        rest = fallback_order[1:]
        if rest:
            quoted = ", ".join(f'"{a}"' for a in rest)
            lines.extend([
                "  # ── Failover, every mechanism this LiteLLM build supports ──────────",
                "  # 1. fallbacks — latency-ranked chain, rank 2..n. `default` is listed",
                "  #    explicitly; the \"*\" key is the generic catch-all that applies",
                "  #    to ANY model group a caller asks for by name. That closes the",
                "  #    DSH model-picker trapdoor: a session pinned to one alias used",
                "  #    to get a single attempt with no chain behind it.",
                "  # 2. context_window_fallbacks — long agent transcripts can overflow a",
                "  #    small-context model; retry the chain rather than 400.",
                "  # 3. content_policy_fallbacks — a safety refusal on one vendor",
                "  #    should not end the turn.",
                "  # 4. allowed_fails_policy + cooldown_time — bench a deployment that",
                "  #    is genuinely 5xx-ing, so the chain stops re-trying it.",
                "  # 5. num_retries + max_fallbacks — retries inside a deployment, then",
                "  #    depth for the walk itself.",
                "  fallbacks:",
                f'    - {{"default": [{quoted}]}}',
                f'    - {{"*": [{quoted}]}}',
                "  context_window_fallbacks:",
                f'    - {{"default": [{quoted}]}}',
                f'    - {{"*": [{quoted}]}}',
                "  content_policy_fallbacks:",
                f'    - {{"default": [{quoted}]}}',
                f'    - {{"*": [{quoted}]}}',
            ])
    lines.extend([
        "",
        "# ── General Settings ─────────────────────────────────────────────────────",
        "general_settings:",
        "  drop_params: true",
        "  request_timeout: 1800      # 30m global HTTP timeout",
        "",
    ])

    return "\n".join(lines), ordered_aliases, fallback_order


DSH_ENTRY_ID = "llm-pi-ai"
DSH_PROVIDER_ID = "pai-gateway"


def generate_dsh_seed(ordered_aliases: List[str]) -> str:
    """Generate the dsh/settings.yaml seed snippet from the live gateway alias list.

    Single source of truth: every `make sync` regenerates this, so the DSH
    model picker never drifts from the gateway. `ordered_aliases` arrives
    alphabetically sorted from generate_litellm_config — emitted as-is so DSH
    (and any future consumer) stays sorted without re-sorting. `default`
    (full fallback chain) is always first, so DSH keeps working even if its
    live volume copy is stale — run `make dsh-refresh` to push the full list.
    """
    lines = [
        "# GENERATED by scripts/sync-models.py — do not hand-edit.",
        "# Rebuilt on every `make sync` from the same liveness-probed alias list",
        "# as llm-gateway/config.yaml, then pushed live with `make dsh-refresh`.",
        "#",
        "# FORMAT: a Cordis profile-patch snippet (entry-list dialect), NOT a",
        "# $DSH_HOME/settings.yaml document. The legacy user-layer import consumes that",
        "# path without merging providers (verified: file renamed to .imported, tree",
        "# unchanged, UI still DeepSeek-only), so this snippet is appended to",
        "# profiles/web/cordis.patch.yml instead — see `make dsh-settings`, which does",
        "# it idempotently and restarts (HMR is off, so file edits need a restart;",
        "# per-request re-read applies to credentials, not to the provider list).",
        "# The Models page merges UI edits into the same patch file; provider ID is",
        "# permanent — sessions reference it.",
        f"- id: {DSH_ENTRY_ID}",
        "  config:",
        "    providers:",
        f"      {DSH_PROVIDER_ID}:",
        "        api: openai-completions",
        "        baseURL: http://llm-gateway:4000/v1",
        "        apiKeyEnv: OPENAI_API_KEY",
        "        models:",
        "          - id: default   # full fallback chain — always works, even if stale",
    ]
    for alias in ordered_aliases:
        lines.append(f"          - id: {alias}")
    lines.extend([
        "",
        "# ── Gateway-only overlays (static — same every run) ─────────────────────",
        "# DSH serves ONLY the stack gateway: the native DeepSeek chat provider is",
        "# unmounted and the agent default points at the `default` fallback chain.",
        "# A user-patch row addresses a base row by id with last-write-wins",
        "# (same mechanism as the documented tool-ralph overlay), so `disabled`",
        "# here removes deepseek-official from the picker without touching the image.",
        "- id: llm-deepseek",
        "  disabled: true",
        "",
        "- id: llm-deepseek-account",
        "  disabled: true",
        "",
        "- id: agent-default-model",
        "  config:",
        "    provider: pai-gateway",
        "    model: default",
        "",
    ])
    return "\n".join(lines)


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
    parser.add_argument("--debug", "-d", "--verbose", "-v", action="store_true",
                        help="Show dropped / skipped (not-connected) models. Hidden by default.")
    parser.add_argument("--env", type=Path, default=Path(".env"), help="Path to .env (default: .env).")
    parser.add_argument("--output", type=Path, default=Path("llm-gateway/config.yaml"), help="Config destination.")
    parser.add_argument("--dsh-output", type=Path, default=Path("dsh/settings.yaml"), help="DSH seed snippet destination.")
    args = parser.parse_args()

    setup_logging(debug=args.debug)

    repo_root = Path(__file__).resolve().parent.parent
    env_file = args.env if args.env.is_absolute() else (repo_root / args.env)
    output_file = args.output if args.output.is_absolute() else (repo_root / args.output)
    dsh_output_file = args.dsh_output if args.dsh_output.is_absolute() else (repo_root / args.dsh_output)

    print(f"\n{C_BOLD}pai-stack — Model Synchronizer{C_RESET}", flush=True)

    env = parse_env_file(env_file)
    for k, v in os.environ.items():
        if k not in env:
            env[k] = v

    discovered: Dict[str, Dict[str, float]] = {}
    skipped: List[str] = []
    broken: List[Tuple[str, str]] = []

    log_info("── What responded " + "─" * 55)
    for prov in PROVIDERS:
        active, live, note = discover_provider_models(prov, env)
        p_name = prov["name"]
        if active and live:
            discovered[prov["id"]] = live
            log_ok(f"{p_name}")
            # Every responder, fastest first — the input to both the pin and the
            # chain. Truncating this list hid the tail, which is exactly where a
            # chat-capable-but-slow model would otherwise look like a dropout.
            ranked = sorted(live.items(), key=lambda kv: (kv[1], kv[0].casefold(), kv[0]))
            width = max((len(m) for m in live), default=0)
            for m, secs in ranked:
                log_info(f"    {m:<{width}}  {secs:6.2f}s")
        elif active:
            log_warn(f"{p_name:<26} → reachable, but 0 models replied")
        elif note == "no key in .env":
            skipped.append(p_name)
            log_skip(f"{p_name:<26} (no key in .env, skipped)")
        else:
            # Configured but not answering. This is NOT the same as "no key":
            # the URL and/or key are set, so the gateway is about to be written
            # without this entire upstream and nothing else in the run says so.
            broken.append((p_name, note or "unreachable"))
            log_warn(f"{p_name:<26} → {note}")

    if skipped:
        # Default output stays quiet — one summary line, details need --debug.
        log_info("")
        log_info(f"{len(skipped)} provider(s) skipped (no key). Models that failed to "
                 f"respond are not listed above — rerun with --debug to see them.")

    if broken:
        # Loud on purpose. A configured-but-unreachable provider means the
        # config about to be written is missing a whole upstream, which used to
        # happen silently.
        log_info("")
        log_warn(f"{len(broken)} configured provider(s) UNREACHABLE — "
                 f"excluded from the config that is about to be written:")
        for name, why in broken:
            log_warn(f"    {name}: {why}")

    yaml_content, ordered_aliases, fallback_order = generate_litellm_config(discovered, env)
    dsh_seed = generate_dsh_seed(ordered_aliases)

    if args.dry_run:
        print(f"\n{C_BOLD}── Preview (Dry Run) ──{C_RESET}\n{yaml_content}", flush=True)
        log_info(f"DSH seed preview: {len(ordered_aliases)} live models + default (not saved).")
        return

    # Backup & Write
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if output_file.exists():
        shutil.copy2(output_file, output_file.with_suffix(".yaml.bak"))

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(yaml_content)

    print(flush=True)
    log_ok(f"Saved configuration to {output_file.relative_to(repo_root)}")

    dsh_output_file.parent.mkdir(parents=True, exist_ok=True)
    if dsh_output_file.exists():
        shutil.copy2(dsh_output_file, dsh_output_file.with_suffix(".yaml.bak"))

    with open(dsh_output_file, "w", encoding="utf-8") as f:
        f.write(dsh_seed)

    log_ok(f"Saved DSH seed ({len(ordered_aliases)} models + default) to {dsh_output_file.relative_to(repo_root)}")
    log_info("Push it live with: make dsh-refresh (DSH must be up)")

    restart_gateway(repo_root)
    print(flush=True)


if __name__ == "__main__":
    main()
