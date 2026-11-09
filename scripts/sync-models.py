#!/usr/bin/env python3
"""
sync-models.py — Keep llm-gateway serving only models that actually reply.

Pipeline (one goal, nothing else):
  1. Read provider API keys from .env.
  2. Ask each keyed provider for its model list.
  3. Probe every candidate with a tiny inference call; drop silent ones.
  4. Write llm-gateway/config.json with survivors only, reload the gateway.

Providers without a key are skipped. Nothing unprobed ever reaches the config,
so Hermes never routes to a listed-but-dead model.
"""

import argparse
import concurrent.futures
import email.utils
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
from typing import Dict, Iterable, List, Optional, Set, Tuple

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
    r"whisper|transcribe|(^|[-_/:])tts([-_/:]|$)|(^|[-_/:])stt([-_/:]|$)",
    r"(^|[-_/:])(ocr|detection|segmentation|upscal|inpaint)([-_/:]|$)",
)
_NON_CHAT_RE = re.compile("|".join(NON_CHAT_PATTERNS), re.IGNORECASE)

# ── Modality patterns ────────────────────────────────────────────────────────
# Classify surviving chat models into specialized modality pools:
# - default: general text, code, and reasoning (all live chat models)
# - vision: models accepting visual/image input
# - audio: models accepting audio/speech input
VISION_PATTERNS = (
    r"(-|_|/)vl(-|_|:|$)",              # nemotron-3.5-super-vl, qwen2.5-vl, internvl, etc.
    r"vision",                          # llama-3.2-11b-vision, gpt-4-vision
    r"(^|[-_/:])pixtral([-_/:]|$)",     # pixtral-12b, pixtral-large
    r"(^|[-_/:])gpt-4o([-_/:]|$)",      # gpt-4o, gpt-4o-mini
    r"(^|[-_/:])claude-3",              # claude-3-haiku, claude-3-5-sonnet, etc.
    r"(^|[-_/:])gemini-(1\.5|2\.)",     # gemini-1.5-flash, gemini-2.0-flash, etc.
    r"(^|[-_/:])omni([-_/:]|$)",        # nemotron-3-nano-omni
    r"(^|[-_/:])minicpm-v",
    r"(^|[-_/:])internvl",
    r"(^|[-_/:])molmo",
    r"(^|[-_/:])cogvlm",
)
_VISION_RE = re.compile("|".join(VISION_PATTERNS), re.IGNORECASE)

AUDIO_PATTERNS = (
    r"(^|[-_/:])voxtral([-_/:]|$)",     # voxtral-small-latest, voxtral-small-2507
    r"(^|[-_/:])audio([-_/:]|$)",       # qwen-2-audio, gpt-4o-audio-preview
    r"(^|[-_/:])omni([-_/:]|$)",        # nemotron-3-nano-omni
    r"(^|[-_/:])gemini-(1\.5|2\.)",     # gemini-1.5, gemini-2.0 native audio input
    r"qwen.*audio",
)
_AUDIO_RE = re.compile("|".join(AUDIO_PATTERNS), re.IGNORECASE)

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


def determine_modalities(
    alias: str,
    prov_id: str,
    model_id: str,
    meta: Optional[dict] = None,
) -> Set[str]:
    """Classify a chat model into modalities: text (always), vision, audio."""
    modalities = {"text"}
    meta = meta or {}

    # Check provider metadata (e.g. OpenRouter input_modalities or modality)
    arch = meta.get("architecture") if isinstance(meta.get("architecture"), dict) else {}
    input_mods = [str(x).lower() for x in arch.get("input_modalities", [])]
    mod_str = str(arch.get("modality", "")).lower()

    if "image" in input_mods or "image" in mod_str:
        modalities.add("vision")
    if "audio" in input_mods or "audio" in mod_str:
        modalities.add("audio")

    # Gemini native generateContent models support vision; 1.5 and 2.0 also support audio
    if prov_id == "gemini":
        m_lower = model_id.lower()
        if "gemini" in m_lower:
            modalities.add("vision")
        if "gemini-1.5" in m_lower or "gemini-2" in m_lower:
            modalities.add("audio")

    # Anthropic Claude 3+ supports vision
    if prov_id == "anthropic" and "claude-3" in model_id.lower():
        modalities.add("vision")

    # Regex heuristic check on alias and model_id
    combined = f"{alias} {model_id}"
    if _VISION_RE.search(combined):
        modalities.add("vision")
    if _AUDIO_RE.search(combined):
        modalities.add("audio")

    return modalities


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


def format_duration(seconds: float) -> str:
    secs = int(round(seconds))
    if secs <= 0:
        return "0s"
    hours, remainder = divmod(secs, 3600)
    minutes, s = divmod(remainder, 60)
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if s > 0 or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)


def parse_reset_time(raw: str) -> str:
    if not raw:
        return ""
    raw = str(raw).strip()
    try:
        val = float(raw)
        if val > 1_000_000_000:
            diff = max(0, val - time.time())
            return f"{format_duration(diff)} (at {time.strftime('%H:%M:%S', time.localtime(val))})"
        else:
            target = time.time() + val
            return f"{format_duration(val)} (at {time.strftime('%H:%M:%S', time.localtime(target))})"
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        diff = max(0, dt.timestamp() - time.time())
        return f"{format_duration(diff)} (at {time.strftime('%H:%M:%S', time.localtime(dt.timestamp()))})"
    except Exception:
        pass
    m = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*(s|sec|second|m|min|minute|h|hr|hour)s?', raw, re.I)
    if m:
        num = float(m.group(1))
        unit = m.group(2).lower()
        mul = 3600 if unit.startswith('h') else (60 if unit.startswith('m') else 1)
        secs = num * mul
        target = time.time() + secs
        return f"{format_duration(secs)} (at {time.strftime('%H:%M:%S', time.localtime(target))})"
    return raw


def is_rate_limit(data: Optional[dict]) -> bool:
    if not isinstance(data, dict):
        return False
    status = data.get("raw_status_code")
    if status == 429:
        return True
    err = data.get("error")
    err_type = ""
    err_msg = ""
    if isinstance(err, dict):
        err_type = str(err.get("type", "")).lower()
        err_msg = str(err.get("message", "")).lower()
    else:
        err_msg = str(err or "").lower()
    if any(k in err_type for k in ("rate", "quota", "usage", "limit")):
        return True
    if any(k in err_msg for k in ("rate limit", "usage limit", "free usage limit", "quota exceeded", "too many requests", "429")):
        return True
    return False


def extract_rate_limit_reset(data: Optional[dict]) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    raw = data.get("retry_after") or data.get("ratelimit_reset")
    if not raw and isinstance(data.get("error"), dict):
        err = data["error"]
        raw = err.get("retry_after") or err.get("reset_time") or err.get("resets_at")
    if not raw:
        msg = ""
        if isinstance(data.get("error"), dict):
            msg = str(data["error"].get("message", ""))
        elif "error" in data:
            msg = str(data.get("error", ""))
        m = re.search(r'(?:retry|try again|resets?)(?:\s+in|\s+after)?\s+([0-9]+(?:\.[0-9]+)?\s*(?:s|sec|second|m|min|minute|h|hr|hour)s?)', msg, re.I)
        if m:
            raw = m.group(1)
    if raw:
        return parse_reset_time(str(raw))
    return None


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
    except urllib.error.HTTPError as e:
        body = {}
        try:
            parsed = json.loads(e.read().decode("utf-8"))
            if isinstance(parsed, dict):
                body = parsed
            else:
                body = {"data": parsed}
        except Exception:
            body = {"error": f"HTTP {e.code}"}
        body.setdefault("raw_status_code", e.code)
        retry_after = e.headers.get("Retry-After") or e.headers.get("retry-after")
        if retry_after:
            body["retry_after"] = retry_after
        rl_reset = (
            e.headers.get("x-ratelimit-reset")
            or e.headers.get("x-ratelimit-reset-requests")
            or e.headers.get("x-ratelimit-reset-tokens")
        )
        if rl_reset:
            body["ratelimit_reset"] = rl_reset
        return body
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
            body = json.loads(resp.read().decode("utf-8"))
            if isinstance(body, dict):
                body.setdefault("raw_status_code", resp.getcode())
            return body
    except urllib.error.HTTPError as e:
        body = {}
        try:
            parsed = json.loads(e.read().decode("utf-8"))
            if isinstance(parsed, dict):
                body = parsed
            else:
                body = {"data": parsed}
        except Exception:
            body = {"error": f"HTTP {e.code}"}
        body.setdefault("raw_status_code", e.code)
        retry_after = e.headers.get("Retry-After") or e.headers.get("retry-after")
        if retry_after:
            body["retry_after"] = retry_after
        rl_reset = (
            e.headers.get("x-ratelimit-reset")
            or e.headers.get("x-ratelimit-reset-requests")
            or e.headers.get("x-ratelimit-reset-tokens")
        )
        if rl_reset:
            body["ratelimit_reset"] = rl_reset
        return body
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


def parse_listing(p_id: str, data: dict, api_key: str = "") -> Tuple[List[str], Dict[str, dict]]:
    """Extract all model ids and metadata dictionaries from a /models response."""
    found_ids: List[str] = []
    meta_by_id: Dict[str, dict] = {}
    if not isinstance(data, dict):
        return found_ids, meta_by_id
    if p_id == "gemini" and isinstance(data.get("models"), list):
        for m in data["models"]:
            if isinstance(m, dict) and m.get("name") and "generateContent" in m.get("supportedGenerationMethods", []):
                mid = m["name"].replace("models/", "")
                found_ids.append(mid)
                meta_by_id[mid] = m
    elif isinstance(data.get("data"), list):
        for m in data["data"]:
            if isinstance(m, dict) and m.get("id"):
                mid = m["id"]
                if p_id == "zen" and not api_key:
                    # Without an API key, OpenCode Zen only serves its free/keyless models.
                    # Filtering avoids spamming 75+ paid models with unauthenticated requests.
                    if not (mid.endswith("-free") or mid == "big-pickle"):
                        continue
                found_ids.append(mid)
                meta_by_id[mid] = m
    return found_ids, meta_by_id


def auth_headers(prov: dict, api_key: str) -> dict:
    if prov["id"] == "gemini":
        return {"x-goog-api-key": api_key}
    if prov["id"] == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    if prov["id"] == "zen":
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def probe_candidates(prov: dict, candidates: List[str], api_key: str) -> Tuple[Dict[str, float], Optional[str]]:
    """Probe candidates; return ({model_id: probe latency in seconds}, rate_limit_summary).

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
        return {}, None

    logger.debug("Probing %d %s models for liveness...", len(chat_candidates), prov["name"])
    live: Dict[str, float] = {}
    rate_limits: Dict[str, Tuple[str, str]] = {}

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
            elif response and is_rate_limit(response):
                reset_str = extract_rate_limit_reset(response) or ""
                detail = provider_error_detail(response) or "rate limit exceeded"
                rate_limits[m_id] = (detail, reset_str)
                if reset_str:
                    logger.info("  ⚠ %s (%s) → rate limited: %s (resets in %s)", prov["name"], m_id, detail, reset_str)
                else:
                    logger.info("  ⚠ %s (%s) → rate limited: %s", prov["name"], m_id, detail)
            elif response and provider_error_detail(response):
                # 200 + error envelope: the gateway is up, the upstream is not.
                # Worth DEBUG — this is the signal that a provider is degraded,
                # not that a model id is wrong.
                logger.debug("⚠ %s → upstream error: %s", m_id, provider_error_detail(response))
            else:
                # No reply text (or HTTP error) — debug-only, use --debug to list.
                logger.debug("○ %s (no reply text, dropped)", m_id)

    rl_summary = None
    if rate_limits:
        resets = [r for _, r in rate_limits.values() if r]
        reset_text = f"; resets in {resets[0]}" if resets else ""
        rl_summary = f"rate limited ({len(rate_limits)} model(s){reset_text})"

    return live, rl_summary


def discover_primary(prov: dict, env: dict) -> Tuple[bool, Dict[str, float], Optional[str], Dict[str, dict]]:
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
        ), {}

    raw = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    ids = [m.get("id") if isinstance(m, dict) else str(m) for m in raw if m]
    ids = [i for i in ids if i]
    meta_by_id = {m.get("id"): m for m in raw if isinstance(m, dict) and m.get("id")}
    if not ids:
        return True, {}, None, {}
    live, rl_summary = probe_candidates(prov | {"chat_base": clean_url}, ids, api_key)
    if not live:
        return True, {}, rl_summary, meta_by_id
    return True, live, rl_summary, meta_by_id


def discover_provider_models(prov: dict, env: dict) -> Tuple[bool, Dict[str, float], Optional[str], Dict[str, dict]]:
    """List + probe one provider.

    Returns (active, live, note, meta_by_id) where `note` explains an inactive provider.
    """
    if prov.get("type") == "openai_compatible":
        return discover_primary(prov, env)

    api_key = env.get(prov["env_key"], "").strip() if prov.get("env_key") else ""
    if prov.get("env_key") and (not api_key or api_key == "not-needed"):
        return False, {}, "no key in .env", {}

    data = fetch_json(prov["endpoint"], headers=auth_headers(prov, api_key), timeout=6)
    if not data or (isinstance(data, dict) and data.get("raw_status_code", 200) >= 400):
        if is_rate_limit(data):
            reset_str = extract_rate_limit_reset(data)
            reset_part = f" (resets in {reset_str})" if reset_str else ""
            return False, {}, f"GET {prov['endpoint']} rate limited{reset_part}", {}
        return False, {}, f"GET {prov['endpoint']} failed (unreachable or rejected)", {}
    candidates, meta_by_id = parse_listing(prov["id"], data, api_key=api_key)
    if not candidates:
        return True, {}, None, {}
    live, rl_summary = probe_candidates(prov, candidates, api_key)
    if not live:
        return True, {}, rl_summary, meta_by_id
    return True, live, rl_summary, meta_by_id


def latency_rank(
    aliases: Iterable[str],
    alias_latency: Dict[str, float],
) -> List[str]:
    """Order every live model fastest-probe-first; ties broken alphabetically.

    This drives BOTH the modality pins (rank 1) and their fallback chains (rank
    2..n), so the two can never disagree about what "first" means.
    """
    return sorted(
        aliases,
        key=lambda a: (alias_latency.get(a, float("inf")), a.casefold(), a),
    )


def choose_category_pin(
    category: str,
    alias_params: Dict[str, List[str]],
    fallback_order: List[str],
    env: dict,
) -> Tuple[Optional[str], str]:
    """Pick the model for a category (default, vision, audio).

    Returns (alias, reason) so the run can report *why* this model won.

    Resolution order:
      1. PAI_<CATEGORY>_MODEL from .env (e.g. PAI_DEFAULT_MODEL, PAI_VISION_MODEL,
         PAI_AUDIO_MODEL), if it is in the live pool.
      2. Rank 1 of fallback_order (fastest probed model in this category).
    """
    live = set(alias_params)
    if not live or not fallback_order:
        return None, f"no live {category} models"

    env_key = f"PAI_{category.upper()}_MODEL" if category != "default" else "PAI_DEFAULT_MODEL"
    override = (env.get(env_key) or "").strip()
    if override:
        if override in live and override in fallback_order:
            rank = fallback_order.index(override) + 1
            return override, (
                f"{env_key} from .env (explicit override)"
                + f"; chain rank {rank}"
            )
        elif override in live:
            return override, f"{env_key} from .env (explicit override; not in {category} chain)"
        logger.warning(
            "%s=%r is not in the live pool — falling back to latency rank.",
            env_key, override,
        )

    chosen = fallback_order[0]
    runner_up = fallback_order[1] if len(fallback_order) > 1 else None
    cat_label = "chat" if category == "default" else category
    why = f"latency rank 1 — fastest {cat_label} model that answered the multi-turn probe"
    if runner_up:
        why += f" (ahead of {runner_up})"
    return chosen, why


def generate_litellm_config(
    discovered: Dict[str, Dict[str, float]],
    env: dict,
    discovered_meta: Optional[Dict[str, Dict[str, dict]]] = None,
) -> Tuple[str, List[str], Dict[str, List[str]], Dict[str, str], Dict[str, str], Dict[str, Set[str]]]:
    """Generate LiteLLM config.yaml string with all discovered models as independent entries.

    `discovered` maps provider id → {model_id: probe latency in seconds}.

    Returns (config_text, ordered_aliases, category_fallbacks, category_pins, category_reasons, alias_modalities):
    - ordered_aliases is alphabetically sorted (case-insensitive) and drives
      the `model_list` emission order and the DSH seed model list.
    - category_fallbacks maps category ('default', 'vision', 'audio') to latency-ranked model chains.
    - category_pins maps category to rank 1 (or overridden) pinned model.
    """
    lines = [
        "# LiteLLM Proxy Configuration for pai-stack",
        "# Centralized LLM gateway managing all model routing and provider credentials.",
        "# NOTE: routes use mistral/ provider mapping (not openai/) so reasoning params",
        "# are stripped pre-flight — see note at primary-models section below.",
        "# NOTE: model entries are alphabetically sorted (case-insensitive) — do not",
        "# hand-reorder; re-running scripts/sync-models.py regenerates this order.",
        "# NOTE: latency-ranked. `default`, `vision`, and `audio` routes have dedicated",
        "# fallback chains from their respective modality pools.",
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
    alias_raw_id: Dict[str, str] = {}

    PRIMARY_SECTION = "  # ── Upstream Language Models (Clean Canonical Names) ──────────────────"

    # 1. Primary language models (clean short canonical names, no duplicates)
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
        alias_raw_id.setdefault(short_name, m_id)

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
        strip_prefix = prov.get("strip_prefix")

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
                block = [
                    f"      model: openai/{m}",
                    f"      api_base: {prov['api_base']}",
                    f"      api_key: os.environ/{env_key}",
                    f"      timeout: {route_timeout(alias)}",
                    "      drop_params: true",
                ]
            else:
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
            alias_raw_id.setdefault(alias, m)

    # 3. Classify modalities for each live alias
    alias_modalities: Dict[str, Set[str]] = {}
    for alias in alias_params:
        pid = alias_provider[alias]
        raw_id = alias_raw_id.get(alias, alias)
        meta = (discovered_meta or {}).get(pid, {}).get(raw_id, {})
        alias_modalities[alias] = determine_modalities(alias, pid, raw_id, meta)

    ordered_aliases: List[str] = sorted(alias_params.keys(), key=lambda a: (a.casefold(), a))

    category_aliases = {
        "default": list(alias_params.keys()),
        "vision": [a for a in alias_params if "vision" in alias_modalities[a]],
        "audio": [a for a in alias_params if "audio" in alias_modalities[a]],
    }

    category_fallbacks: Dict[str, List[str]] = {}
    category_pins: Dict[str, str] = {}
    category_reasons: Dict[str, str] = {}

    for cat in ("default", "vision", "audio"):
        order = latency_rank(category_aliases[cat], alias_latency)
        pinned, why = choose_category_pin(cat, alias_params, order, env)
        if pinned:
            if order and order[0] != pinned:
                order = [pinned] + [a for a in order if a != pinned]
            category_pins[cat] = pinned
            category_reasons[cat] = why
            category_fallbacks[cat] = order

    # Emit model_list in alphabetically sorted order
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

    # 4. Modality pins (default, vision, audio)
    logger.info("")
    for cat in ("default", "vision", "audio"):
        pinned = category_pins.get(cat)
        if pinned:
            order = category_fallbacks[cat]
            rest_count = len(order) - 1
            counts: Dict[str, int] = {}
            for alias in order:
                pid = alias_provider.get(alias, "?")
                counts[pid] = counts.get(pid, 0) + 1
            lines.append(f"  # ── {cat.capitalize()} (latency rank 1; rest via {cat} fallback chain) ──")
            lines.extend([
                f"  - model_name: {cat}",
                "    litellm_params:",
                *alias_params[pinned],
                "",
            ])
            log_ok(f"{cat:<7} → {pinned}")
            log_info(f"  why    {category_reasons[cat]}")
            log_info(
                f"  chain  {len(order)} {cat} model(s), latency-ranked across "
                f"{len(counts)} provider(s) ({rest_count} fallback(s)) — "
                + ", ".join(f"{k}×{v}" for k, v in sorted(counts.items()))
            )
        else:
            log_skip(f"{cat:<7} → no live {cat} models found (route omitted)")
    logger.info("")

    # Router Settings
    lines.extend([
        "# ── Router Settings ─────────────────────────────────────────────────────",
        "router_settings:",
        "  timeout: 1800              # 30m request timeout for large models & deep reasoning",
        "  stream_timeout: 1800       # 30m chunk timeout for slow reasoning token streams",
        "  num_retries: 2             # retries within a deployment before failing over",
        "  max_fallbacks: 60          # >= chain length, so every link is reachable",
        "  cooldown_time: 60          # bench length — a failing model rests 60s",
        "  retry_after: 5             # honour upstream Retry-After, else wait 5s",
        "  allowed_fails_policy:",
        "    ServiceUnavailableErrorAllowedFails: 3   # 503 (overloaded upstream)",
        "    InternalServerErrorAllowedFails: 3",
        "    BadGatewayErrorAllowedFails: 3           # 502 (upstream refused)",
        "    TimeoutErrorAllowedFails: 5",
        "    RateLimitErrorAllowedFails: 5            # 429",
    ])

    fallbacks_entries = []
    for cat in ("default", "*", "vision", "audio"):
        lookup_cat = "default" if cat == "*" else cat
        order = category_fallbacks.get(lookup_cat, [])
        rest = order[1:] if len(order) > 1 else []
        if rest:
            quoted = ", ".join(f'"{a}"' for a in rest)
            fallbacks_entries.append(f'    - {{"{cat}": [{quoted}]}}')

    if fallbacks_entries:
        lines.extend([
            "  # ── Failover, every mechanism this LiteLLM build supports ──────────",
            "  fallbacks:",
            *fallbacks_entries,
            "  context_window_fallbacks:",
            *fallbacks_entries,
            "  content_policy_fallbacks:",
            *fallbacks_entries,
        ])

    lines.extend([
        "",
        "# ── General Settings ─────────────────────────────────────────────────────",
        "general_settings:",
        "  drop_params: true",
        "  request_timeout: 1800      # 30m global HTTP timeout",
        "",
    ])

    return (
        "\n".join(lines),
        ordered_aliases,
        category_fallbacks,
        category_pins,
        category_reasons,
        alias_modalities,
    )


def generate_bifrost_config(
    discovered: Dict[str, Dict[str, float]],
    env: dict,
    category_fallbacks: Dict[str, List[str]],
    category_pins: Dict[str, str],
) -> str:
    """Generate Bifrost config.json string with surviving models, latency-ranked routes, and fallbacks."""
    providers_config = {}
    prov_map = {p["id"]: p for p in PROVIDERS}

    for p_id, models in discovered.items():
        if not models:
            continue
        prov = prov_map.get(p_id, {})
        env_key = prov.get("env_key", "")
        prefix = prov.get("prefix", p_id)
        api_base = prov.get("api_base") or prov.get("chat_base")
        is_openai_comp = (
            prov.get("type") == "openai_compatible"
            or bool(prov.get("api_base"))
            or p_id in ("kilo", "zen", "nvidia", "aion", "ollama_cloud")
        )

        model_names = []
        for m in sorted(models.keys()):
            clean = m
            if prov.get("strip_prefix"):
                clean = m.replace(prov["strip_prefix"], "")
            elif prefix and m.startswith(f"{prefix}/"):
                clean = m[len(prefix) + 1:]
            model_names.append(clean)

        key_value = f"env.{env_key}" if env_key else "not-needed"
        if p_id == "primary":
            key_value = "env.OPENAI_COMPATIBLE_API_KEY"

        key_entry = {
            "name": f"{p_id}-key",
            "value": key_value,
            "models": model_names if model_names else ["*"],
            "weight": 1.0,
            "enabled": True,
        }

        entry = {
            "keys": [key_entry],
            "network_config": {
                "default_request_timeout_in_seconds": 120 if any(m.endswith(":free") for m in models) else 1800,
                "max_retries": 2,
            },
        }

        if is_openai_comp:
            entry["custom_provider_config"] = {
                "base_provider_type": "openai",
                "is_key_less": (p_id == "zen"),
                "allowed_requests": {
                    "list_models": True,
                    "chat_completion": True,
                    "chat_completion_stream": True,
                },
            }
            if p_id == "primary":
                entry["network_config"]["base_url"] = "env.OPENAI_COMPATIBLE_BASE_URL"
            elif api_base:
                entry["network_config"]["base_url"] = api_base

        providers_config[p_id] = entry

    aliases_config = {}
    routing_rules = []
    priority = 1

    for cat in ("default", "vision", "audio"):
        pinned = category_pins.get(cat)
        if not pinned:
            continue
        if "/" in pinned:
            prov_prefix, p_model = pinned.split("/", 1)
        else:
            prov_prefix, p_model = "primary", pinned

        pin_prov = prov_prefix
        for pid, pdata in prov_map.items():
            if pdata.get("prefix") == prov_prefix:
                pin_prov = pid
                break

        aliases_config[cat] = {
            "type": "static",
            "target": {
                "provider": pin_prov,
                "model": p_model,
            },
        }

        order = category_fallbacks.get(cat, [])
        fallbacks = [fb for fb in order if fb != pinned]

        rule = {
            "id": f"{cat}-model-rule",
            "name": f"{cat}-model-rule",
            "description": f"Route model={cat} to latency rank 1 {cat} model with dedicated fallback chain",
            "cel_expression": f"model == '{cat}'",
            "scope": "global",
            "priority": priority,
            "targets": [
                {
                    "provider": pin_prov,
                    "model": p_model,
                    "weight": 1,
                }
            ],
            "fallbacks": fallbacks,
        }
        routing_rules.append(rule)
        priority += 1

    bifrost_doc = {
        "$schema": "https://www.getbifrost.ai/schema",
        "source_of_truth": "config.json",
        "encryption_key": "env.BIFROST_ENCRYPTION_KEY",
        "client": {
            "drop_excess_requests": False,
            "enable_logging": True,
            "enforce_auth_on_inference": False,
        },
        "aliases": aliases_config,
        "config_store": {
            "enabled": True,
            "type": "sqlite",
            "config": {
                "path": "/app/data/config.db",
            },
        },
        "providers": providers_config,
        "governance": {
            "virtual_keys": [
                {
                    "name": "default-key",
                    "value": "sk-bf-default",
                    "description": "Default virtual key for pai-stack",
                    "is_active": True,
                }
            ],
            "routing_rules": routing_rules,
        },
    }

    return json.dumps(bifrost_doc, indent=2) + "\n"


DSH_ENTRY_ID = "llm-pi-ai"
DSH_PROVIDER_ID = "pai-gateway"


def generate_dsh_seed(
    ordered_aliases: List[str],
    category_pins: Optional[Dict[str, str]] = None,
) -> str:
    """Generate the dsh/settings.yaml seed snippet from the live gateway alias list."""
    category_pins = category_pins or {}
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
    if "vision" in category_pins:
        lines.append("          - id: vision    # vision fallback chain — dedicated multimodal image failover")
    if "audio" in category_pins:
        lines.append("          - id: audio     # audio fallback chain — dedicated multimodal audio failover")
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
        description="Write llm-gateway (Bifrost) config with only models that reply (keyed providers only)."
    )
    parser.add_argument("--dry-run", "-n", action="store_true", help="Preview generated config without saving.")
    parser.add_argument("--debug", "-d", "--verbose", "-v", action="store_true",
                        help="Show dropped / skipped (not-connected) models. Hidden by default.")
    parser.add_argument("--env", type=Path, default=Path(".env"), help="Path to .env (default: .env).")
    parser.add_argument("--output", type=Path, default=Path("llm-gateway/config.json"), help="LLM Gateway config destination.")
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
    discovered_meta: Dict[str, Dict[str, dict]] = {}
    skipped: List[str] = []
    broken: List[Tuple[str, str]] = []

    log_info("── What responded " + "─" * 55)
    for prov in PROVIDERS:
        active, live, note, prov_meta = discover_provider_models(prov, env)
        p_name = prov["name"]
        if active and live:
            discovered[prov["id"]] = live
            discovered_meta[prov["id"]] = prov_meta
            log_ok(f"{p_name}")
            # Every responder, fastest first — the input to both the pins and the
            # chains. Truncating this list hid the tail, which is exactly where a
            # chat-capable-but-slow model would otherwise look like a dropout.
            ranked = sorted(live.items(), key=lambda kv: (kv[1], kv[0].casefold(), kv[0]))
            width = max((len(m) for m in live), default=0)
            for m, secs in ranked:
                meta = prov_meta.get(m, {})
                mods = sorted(determine_modalities(m, prov["id"], m, meta))
                mods_badge = f"[{', '.join(mods)}]"
                log_info(f"    {m:<{width}}  {secs:6.2f}s  {mods_badge}")
            if note:
                log_warn(f"    ⚠ {note}")
        elif active:
            if note:
                log_warn(f"{p_name:<26} → {note}")
            else:
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

    (
        _,
        ordered_aliases,
        category_fallbacks,
        category_pins,
        category_reasons,
        alias_modalities,
    ) = generate_litellm_config(discovered, env, discovered_meta)
    bifrost_content = generate_bifrost_config(
        discovered, env, category_fallbacks, category_pins
    )
    dsh_seed = generate_dsh_seed(ordered_aliases, category_pins)

    if args.dry_run:
        print(f"\n{C_BOLD}── Preview (Dry Run) ──{C_RESET}\n{bifrost_content}", flush=True)
        routes = [f"{cat} ({len(category_fallbacks[cat])} models)" for cat in ("default", "vision", "audio") if cat in category_pins]
        routes_summary = ", ".join(routes) if routes else "no live routes"
        log_info(f"DSH seed preview: {len(ordered_aliases)} live models + routes: {routes_summary} (not saved).")
        log_info(f"Bifrost config preview: {len(ordered_aliases)} live models across {len(discovered)} provider(s) (not saved).")
        return

    # Backup & Write Gateway Config (Bifrost)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if output_file.exists():
        shutil.copy2(output_file, output_file.with_suffix(".json.bak"))

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(bifrost_content)

    print(flush=True)
    log_ok(f"Saved LLM Gateway configuration to {output_file.relative_to(repo_root)}")

    # Backup & Write DSH Seed
    dsh_output_file.parent.mkdir(parents=True, exist_ok=True)
    if dsh_output_file.exists():
        shutil.copy2(dsh_output_file, dsh_output_file.with_suffix(".yaml.bak"))

    with open(dsh_output_file, "w", encoding="utf-8") as f:
        f.write(dsh_seed)

    routes = [f"{cat} → {category_pins[cat]}" for cat in ("default", "vision", "audio") if cat in category_pins]
    routes_str = f" + routes: {', '.join(routes)}" if routes else ""
    log_ok(f"Saved DSH seed ({len(ordered_aliases)} models{routes_str}) to {dsh_output_file.relative_to(repo_root)}")
    log_info("Push it live with: make dsh-refresh (DSH must be up)")

    restart_gateway(repo_root)
    print(flush=True)


if __name__ == "__main__":
    main()
