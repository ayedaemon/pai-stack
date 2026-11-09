"""pai_web_ops — Web search via SearXNG + fetch (native Hermes tool).

Environment variables:
  SEARXNG_URL — SearXNG base URL (default: http://searxng:8888)
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ALLOWED_ACTIONS = ("search", "fetch")

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8888").rstrip("/")

SCHEMA = {
    "name": "pai_web_ops",
    "description": (
        "Web search (via SearXNG) and fetch. "
        "Use for: search the web for a query, fetch a URL's text content. "
        "search returns titles, urls, snippets. fetch returns page text."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(ALLOWED_ACTIONS),
                "description": "Operation to perform",
            },
            "query": {
                "type": "string",
                "description": "Search query (required for search)",
            },
            "url": {
                "type": "string",
                "description": "URL to fetch (required for fetch)",
            },
            "max_results": {
                "type": "integer",
                "description": "Max results for search (default 10)",
            },
        },
        "required": ["action"],
    },
}


def _search(query, max_results=10):
    url = f"{SEARXNG_URL}/search?q={urllib.request.quote(query)}&format=json"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            raw = resp.read().decode()
            data = json.loads(raw) if raw else {}
    except Exception as e:
        return {"error": str(e)}
    results = []
    for r in (data.get("results") or [])[:max_results]:
        results.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": (r.get("content") or "")[:300],
        })
    return {"query": query, "results": results, "count": len(results)}


def _fetch(url, max_chars=20000):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pai-web/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"error": str(e), "url": url}
    text = raw
    # strip tags roughly
    import re
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    return {"url": url, "content": text[:max_chars], "truncated": len(text) > max_chars}


def handle(args, **kwargs) -> str:
    if not isinstance(args, dict):
        return json.dumps({"error": "Invalid arguments"})
    action = args.get("action", "")
    if action == "search":
        query = args.get("query", "") or ""
        if not query:
            return json.dumps({"error": "query is required for search"})
        max_results = int(args.get("max_results") or 10)
        return json.dumps(_search(query, max_results))
    if action == "fetch":
        url = args.get("url", "") or ""
        if not url:
            return json.dumps({"error": "url is required for fetch"})
        return json.dumps(_fetch(url))
    return json.dumps({"error": f"unknown action: {action}. Allowed: {list(ALLOWED_ACTIONS)}"})
