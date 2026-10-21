#!/usr/bin/env python3
"""
notebook_ops.py — Research Brain wiki tool (Hermes plugin).

Storage is a per-workspace Markdown wiki at
`<session workspace>/.project/research/`:

    SCHEMA.md        conventions, tag taxonomy, domain      (agent-authored)
    index.md         sectioned catalog, one-line summaries  (tool-maintained)
    log.md           append-only action log                 (tool-maintained)
    raw/<category>/  Layer 1: immutable ingested sources
    entities/        Layer 2: people, orgs, products, models
    concepts/        Layer 2: topics, techniques
    comparisons/     Layer 2: side-by-side analyses
    queries/         Layer 2: filed answers worth keeping
    _archive/        superseded pages, delinked from index

The workspace is resolved per call from the session's attached workspace (see
session_workspace.py) — never at import time, so one process serves every
session and a workspace switch takes effect immediately.

Actions:
  - init_wiki, list_pages, get_page, write_page
  - ingest_url, ingest_file, get_source
  - search, ask
"""

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from plugins.pai_tools.session_workspace import (
    WorkspaceUnresolved,
    session_workspace,
)

LLM_GATEWAY_URL = os.environ.get(
    "LLM_GATEWAY_URL",
    os.environ.get("LLM_GATEWAY_BASE_URL", "http://llm-gateway:4000/v1"),
)
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "not-needed")

# Layer 2 page types, keyed by the directory they live in.
PAGE_SECTIONS = ("entities", "concepts", "comparisons", "queries")
# Layer 1 source categories, grouped under raw/.
SOURCE_CATEGORIES = ("articles", "papers", "docs", "notes", "other")
# Directories a page reference may point at. _archive is reachable by
# get_page/write_page but excluded from search so superseded knowledge
# never resurfaces as current.
ADDRESSABLE_DIRS = PAGE_SECTIONS + ("raw", "_archive")

INDEX_HEADER = "# Research Index"
INDEX_TOTAL_PREFIX = "Total pages:"

SCHEMA = {
    "name": "pai_notebook_ops",
    "description": (
        "Research Brain wiki for the workspace attached to this session. "
        "Maintains an interlinked Markdown wiki at <workspace>/.project/research/ "
        "with an immutable raw/ source layer and agent-owned entity/concept/"
        "comparison/query pages. Use for external knowledge: RFCs, papers, API "
        "docs, web articles, and evidence notes. Layer 2 pages must carry YAML "
        "frontmatter and at least two [[wikilinks]]."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "init_wiki",
                    "list_pages",
                    "get_page",
                    "write_page",
                    "ingest_url",
                    "ingest_file",
                    "get_source",
                    "search",
                    "ask",
                ],
                "description": (
                    "Operation to perform. init_wiki: create SCHEMA.md/index.md/log.md "
                    "for a new vault. list_pages: inventory the wiki. get_page: read one "
                    "page by ref. write_page: create/update a Layer 2 page (entities, "
                    "concepts, comparisons, queries) and register it in index.md + log.md. "
                    "ingest_url: fetch a URL into raw/ as an immutable source. "
                    "ingest_file: capture a local file into raw/. get_source: full text of "
                    "an ingested source. search: score pages against a query. ask: "
                    "grounded synthesis over search hits via the gateway."
                ),
            },
            "page_ref": {
                "type": "string",
                "description": "Page reference relative to the vault, e.g. 'concepts/attention.md' or 'entities/acme'. Bare slugs are matched across sections (get_page, write_page).",
            },
            "section": {
                "type": "string",
                "enum": list(PAGE_SECTIONS),
                "description": "Layer 2 section for write_page (default: concepts).",
            },
            "title": {
                "type": "string",
                "description": "Page title. Required for write_page and ingest_url.",
            },
            "content": {
                "type": "string",
                "description": "Markdown body for write_page.",
            },
            "summary": {
                "type": "string",
                "description": "One-line summary used in index.md. Defaults to the page's first paragraph.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags for write_page. Must come from the taxonomy declared in SCHEMA.md.",
            },
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Provenance refs for write_page, e.g. ['raw/articles/foo.md'].",
            },
            "url": {
                "type": "string",
                "description": "URL to ingest (ingest_url).",
            },
            "category": {
                "type": "string",
                "enum": list(SOURCE_CATEGORIES),
                "description": "raw/<category>/ bucket for ingest_url / ingest_file (default: articles).",
            },
            "file_path": {
                "type": "string",
                "description": "Absolute path of a local file to capture (ingest_file).",
            },
            "source_id": {
                "type": "string",
                "description": "Source id from an ingest result, e.g. 'source:9f2a1c...' (get_source).",
            },
            "query": {
                "type": "string",
                "description": "Search query, or the question for ask.",
            },
            "answer_model": {
                "type": "string",
                "description": "Model override for the ask synthesis.",
            },
        },
        "required": ["action"],
    },
}


# ── Vault helpers ────────────────────────────────────────────────────────────


def _vault() -> Path:
    """`<session workspace>/.project/research`, not created."""
    return session_workspace() / ".project" / "research"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00:00")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", str(text)).strip().lower()
    text = re.sub(r"[-\s]+", "-", text)
    return text[:60] or "untitled"


def extract_anchors(text: str) -> List[str]:
    if not text:
        return []
    raw = re.findall(r"@symbol:[^\s\)\`\"\']+", text)
    return sorted({r.rstrip(".,;:)!?'\"") for r in raw})


def extract_wikilinks(text: str) -> List[str]:
    if not text:
        return []
    return sorted({m.strip() for m in re.findall(r"\[\[([^\]]+)\]\]", text)})


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    metadata: Dict[str, Any] = {}
    current_list_key: Optional[str] = None

    for line in parts[1].splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("  - ") and current_list_key:
            metadata.setdefault(current_list_key, []).append(
                line[4:].strip().strip('"').strip("'")
            )
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if not val:
                current_list_key = key
                metadata[key] = []
            else:
                current_list_key = None
                metadata[key] = val

    return metadata, parts[2].strip()


def _canonical_dir(directory: Path) -> Optional[Path]:
    """Return the on-disk directory whose name matches, case exactly.

    `iterdir()` yields paths joined to the directory object it was called on,
    so resolving `Concepts/attention.md` against a constructed wrong-case path
    returns a wrong-case path even after a case-insensitive match. Walking up
    from a real parent entry is the only way to get the true on-disk name.
    """
    parent, name = directory.parent, directory.name
    if not parent.is_dir():
        return None
    target = name.lower()
    for entry in parent.iterdir():
        if entry.name.lower() == target and entry.is_dir():
            return entry
    return None


def _section_dir(section: str) -> Optional[Path]:
    """Canonical path of a vault section directory, or None if absent."""
    return _canonical_dir(_vault() / section)


def _exact_entry(directory: Optional[Path], name: str) -> Optional[Path]:
    """Resolve `directory/name` to a real on-disk file, matching case exactly."""
    if directory is None or not directory.is_dir():
        return None
    target = name.lower()
    for entry in directory.iterdir():
        if entry.name.lower() == target and entry.is_file():
            return entry
    return None


def resolve_page_ref(ref: str) -> Optional[Path]:
    """Resolve a page reference to a file inside the vault.

    Accepts `section/slug.md`, a bare slug, or a wikilink target. A bare slug
    resolves by scanning sections in priority order, so a wikilink written
    without its section still lands somewhere deterministic.
    """
    if not ref or not _vault().exists():
        return None

    norm = ref.strip().strip("[]").removesuffix(".md").strip("/")
    if not norm:
        return None

    root = _vault()

    if "/" in norm:
        head, _, tail = norm.partition("/")
        section_dir = _section_dir(head)
        exact = _exact_entry(section_dir, f"{tail}.md")
        if exact:
            return exact
        # A section name written in the wrong case (`Concepts/foo.md`).
        for section in ADDRESSABLE_DIRS:
            if section.lower() == head.lower():
                exact = _exact_entry(_section_dir(section), f"{tail}.md")
                if exact:
                    return exact
        return None

    for section in ADDRESSABLE_DIRS:
        exact = _exact_entry(_section_dir(section), f"{norm}.md")
        if exact:
            return exact

    # Last resort: a title match on frontmatter.
    needle = norm.lower()
    for section in ADDRESSABLE_DIRS:
        section_dir = _section_dir(section)
        if section_dir is None:
            continue
        for path in section_dir.rglob("*.md"):
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            if str(meta.get("title", "")).strip().lower() == needle:
                return path

    return None


def page_ref_of(path: Path) -> str:
    """Vault-relative reference for a page, e.g. `concepts/attention`."""
    return str(path.relative_to(_vault()).with_suffix("")).strip("/")


def iter_pages(include_archive: bool = False) -> List[Path]:
    """Every knowledge page in the vault, raw sources included."""
    root = _vault()
    if not root.is_dir():
        return []
    sections = ADDRESSABLE_DIRS if include_archive else ADDRESSABLE_DIRS[:-1]
    pages: List[Path] = []
    for section in sections:
        section_dir = root / section
        if section_dir.is_dir():
            pages.extend(sorted(section_dir.rglob("*.md")))
    return pages


def summarize(body: str, limit: int = 120) -> str:
    """First meaningful paragraph, collapsed to one line.

    Wikilink markup is unwrapped so the index stays a catalog rather than a
    second, competing set of link targets.
    """
    for block in re.split(r"\n\s*\n", body):
        text = " ".join(
            line.strip()
            for line in block.splitlines()
            if line.strip() and not line.startswith(("#", "---", ">"))
        )
        text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
        if len(text) >= 12:
            return (text[: limit - 1] + "…") if len(text) > limit else text
    return ""


# ── index.md / log.md bookkeeping ────────────────────────────────────────────


def _read_index() -> List[str]:
    path = _vault() / "index.md"
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def register_in_index(ref: str, summary: str) -> None:
    """Upsert `ref` into its section of index.md, keeping sections sorted."""
    root = _vault()
    path = root / "index.md"
    lines = _read_index()

    section = ref.split("/", 1)[0].title() if "/" in ref else "Queries"
    entry = f"- [[{ref}]]" + (f" — {summary}" if summary else "")

    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == f"## {section}")
    except StopIteration:
        lines += ["", f"## {section}", "", entry, ""]
    else:
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
            len(lines),
        )
        block = [
            l
            for l in lines[start + 1 : end]
            if l.strip().startswith("- [[") and l.strip() != f"- [[{ref}]]"
        ]
        block.append(entry)
        block.sort(key=lambda l: l.strip().lower())
        # Blank line after the header and between entries keeps the file
        # readable as Markdown; index.md is agent-facing, not just a machine map.
        rebuilt: List[str] = []
        for i, line in enumerate(block):
            if i:
                rebuilt.append("")
            rebuilt.append(line)
        # Trailing blank keeps the next `## Section` header off this block.
        lines[start + 1 : end] = [""] + rebuilt + [""]

    total = sum(1 for l in lines if l.strip().startswith("- [["))
    lines = [f"{INDEX_TOTAL_PREFIX} {total}" if l.startswith(INDEX_TOTAL_PREFIX) else l for l in lines]
    lines = [f"_Updated {_today()}_" if l.startswith("_Updated ") else l for l in lines]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def append_log(action: str, detail: str) -> None:
    path = _vault() / "log.md"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"- {stamp} | {action} | {detail}"
    if not path.is_file():
        path.write_text(f"# Research Log\n\n{entry}\n", encoding="utf-8")
    else:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{entry}\n")
    rotate_log()


def rotate_log() -> Optional[str]:
    """Roll log.md to log-YYYY.md once it passes 500 entries."""
    path = _vault() / "log.md"
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    entries = [l for l in lines if l.startswith("- ")]
    if len(entries) <= 500:
        return None
    year = _today()[:4]
    rotated = _vault() / f"log-{year}.md"
    with rotated.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(entries) + "\n")
    path.write_text(
        "\n".join([l for l in lines if not l.startswith("- ")]) + f"\n- {len(entries)} entries rotated to log-{year}.md\n",
        encoding="utf-8",
    )
    return rotated.name


# ── Action handlers ──────────────────────────────────────────────────────────


def action_init_wiki(inp: Dict[str, Any]) -> str:
    root = _vault()
    root.mkdir(parents=True, exist_ok=True)
    domain = inp.get("content") or inp.get("summary") or ""
    created: List[str] = []

    if not (root / "SCHEMA.md").is_file():
        (root / "SCHEMA.md").write_text(
            f"""---
title: Research Schema
created: "{_now()}"
---

# SCHEMA

{f'**Domain**: {domain.strip()}' if domain.strip() else '**Domain**: _undeclared — set this before the first ingest._'}

## Filenames
lowercase, hyphens (`transformer-architecture.md`).

## Page frontmatter (required on every Layer 2 page)
`title, created, updated, type: entity|concept|comparison|query|summary, tags, sources`

## Rules
- Every Layer 2 page carries >= 2 `[[wikilinks]]`, cross-referenced both directions.
- Bump `updated` on every edit; add the page to `index.md`; append to `log.md`.
- Tags come only from the taxonomy below — extend it here first.
- Create a page when an entity appears in 2+ sources or is central to one.
- Split a page past ~200 lines.
- `raw/` is immutable. Superseded pages move to `_archive/` and leave `index.md`.
- Contradictions stay side by side with dates, marked `contested: true`.
- Set `confidence: high|medium|low` for opinion-heavy or fast-moving claims.

## Tag taxonomy
<!-- add tags here as the domain demands; nothing outside this list is valid -->
- general
""",
            encoding="utf-8",
        )
        created.append("SCHEMA.md")

    if not (root / "index.md").is_file():
        (root / "index.md").write_text(
            f"{INDEX_HEADER}\n\n## Entities\n\n## Concepts\n\n## Comparisons\n\n## Queries\n\n"
            f"{INDEX_TOTAL_PREFIX} 0\n\n_Updated {_today()}_\n",
            encoding="utf-8",
        )
        created.append("index.md")

    if not (root / "log.md").is_file():
        (root / "log.md").write_text("# Research Log\n", encoding="utf-8")
        created.append("log.md")

    if created:
        append_log("init_wiki", f"initialized {', '.join(created)}")

    return json.dumps(
        {
            "vault": str(root),
            "created": created,
            "already_initialized": not created,
        }
    )


def action_list_pages(inp: Dict[str, Any]) -> str:
    root = _vault()
    if not root.is_dir():
        return json.dumps({"error": "Wiki not initialized. Run action=init_wiki first."})

    sections: Dict[str, List[Dict[str, Any]]] = {}
    raw_count = 0
    layer2_count = 0
    for section in ADDRESSABLE_DIRS:
        entries = []
        for path in iter_pages(include_archive=True):
            if page_ref_of(path).split("/", 1)[0] != section:
                continue
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            entries.append(
                {
                    "ref": page_ref_of(path),
                    "title": meta.get("title", path.stem),
                    "updated": meta.get("updated", ""),
                    "tags": meta.get("tags", []),
                }
            )
        if not entries:
            continue
        sections[section] = entries
        if section == "raw":
            raw_count = len(entries)
        else:
            layer2_count += len(entries)

    return json.dumps(
        {
            "vault": str(root),
            "layer2_pages": layer2_count,
            "raw_sources": raw_count,
            "sections": sections,
            "has_schema": (root / "SCHEMA.md").is_file(),
        }
    )


def action_get_page(inp: Dict[str, Any]) -> str:
    ref = inp.get("page_ref") or ""
    if not ref:
        return json.dumps({"error": "page_ref is required"})

    path = resolve_page_ref(ref)
    if not path:
        return json.dumps({"error": f"Page not found: {ref}"})

    raw = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw)
    return json.dumps(
        {
            "ref": page_ref_of(path),
            "file_path": str(path),
            "metadata": meta,
            "anchors": extract_anchors(body),
            "wikilinks": extract_wikilinks(body),
            "content": body,
        }
    )


def action_write_page(inp: Dict[str, Any]) -> str:
    title = inp.get("title") or ""
    content = inp.get("content") or ""
    if not title.strip():
        return json.dumps({"error": "title is required"})
    if not content.strip():
        return json.dumps({"error": "content is required"})

    section = inp.get("section") or "concepts"
    if section not in PAGE_SECTIONS:
        return json.dumps({"error": f"section must be one of {', '.join(PAGE_SECTIONS)}"})

    root = _vault()
    root.mkdir(parents=True, exist_ok=True)
    (root / section).mkdir(parents=True, exist_ok=True)

    ref = f"{section}/{slugify(title)}"
    path = root / f"{ref}.md"

    existing_meta: Dict[str, Any] = {}
    if path.is_file():
        existing_meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))

    # Carry created/anchors forward so an update is not a rewrite.
    merged_sources = list(inp.get("sources") or existing_meta.get("sources") or [])
    if isinstance(merged_sources, str):
        merged_sources = [merged_sources]
    for ref_link in extract_wikilinks(content):
        if ref_link not in merged_sources:
            merged_sources.append(ref_link)

    anchors = extract_anchors(content)
    tags = inp.get("tags") or existing_meta.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    summary = (inp.get("summary") or "").strip() or summarize(content)

    frontmatter = [
        "---",
        f"title: {json.dumps(title.strip())}",
        f'type: "{section.rstrip("s") if section != "queries" else "query"}"',
        f'created: "{existing_meta.get("created") or _now()}"',
        f'updated: "{_now()}"',
    ]
    if tags:
        frontmatter.append("tags:")
        frontmatter.extend(f'  - "{t}"' for t in tags)
    if merged_sources:
        frontmatter.append("sources:")
        frontmatter.extend(f'  - "{s}"' for s in merged_sources)
    if anchors:
        frontmatter.append("anchors:")
        frontmatter.extend(f'  - "{a}"' for a in anchors)
    frontmatter.append("confidence: medium")
    frontmatter.append("---\n")

    path.write_text(
        "\n".join(frontmatter) + f"\n# {title.strip()}\n\n{content.strip()}\n",
        encoding="utf-8",
    )

    created = not existing_meta
    register_in_index(ref, summary)
    append_log("write_page", f"{'created' if created else 'updated'} {ref}")

    warnings = []
    links = extract_wikilinks(content)
    if len(links) < 2:
        warnings.append(
            f"Only {len(links)} [[wikilink]] found — pages need >= 2 to stay reachable."
        )
    broken = [l for l in links if not resolve_page_ref(l)]
    if broken:
        warnings.append(
            "These [[wikilinks]] point at pages that do not exist yet: "
            + ", ".join(broken)
        )
    if not merged_sources:
        warnings.append("No [[wikilinks]] or sources recorded — page is an orphan.")

    return json.dumps(
        {
            "ref": ref,
            "file_path": str(path),
            "created": created,
            "summary": summary,
            "anchors": anchors,
            "wikilinks": links,
            "broken_links": broken,
            "warnings": warnings,
        }
    )


def _write_raw(
    *,
    title: str,
    body: str,
    category: str,
    source_url: str = "",
    origin_path: str = "",
) -> Tuple[Path, str, bool]:
    """Capture an immutable Layer 1 source. Returns (path, sha256, drift)."""
    root = _vault()
    (root / "raw" / category).mkdir(parents=True, exist_ok=True)

    ref = f"raw/{category}/{slugify(title)}"
    path = root / f"{ref}.md"
    digest = hashlib.sha256(body.strip().encode("utf-8")).hexdigest()

    if path.is_file():
        # Compare against the recorded digest of the source body, not the
        # assembled document (which carries title + provenance of its own).
        prior_meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        if prior_meta.get("sha256") == digest:
            return path, digest, False

    source_id = f"source:{digest[:16]}"
    provenance = f"**Source URL**: [{source_url}]({source_url})" if source_url else f"**Source File**: `{origin_path}`"
    frontmatter = [
        "---",
        f"title: {json.dumps(title)}",
        f"type: raw",
        f"id: \"{source_id}\"",
    ]
    if source_url:
        frontmatter.append(f"source_url: \"{source_url}\"")
    if origin_path:
        frontmatter.append(f"file_path: \"{origin_path}\"")
    frontmatter.extend(
        [
            f'ingested: "{_now()}"',
            f"sha256: {digest}",
            "---\n",
        ]
    )

    path.write_text(
        "\n".join(frontmatter) + f"\n# {title}\n\n{provenance}\n\n{body.strip()}\n",
        encoding="utf-8",
    )
    return path, digest, True


def _category(inp: Dict[str, Any]) -> str:
    category = inp.get("category") or "articles"
    return category if category in SOURCE_CATEGORIES else "other"


def action_ingest_url(inp: Dict[str, Any]) -> str:
    url = inp.get("url") or ""
    if not url:
        return json.dumps({"error": "url is required"})

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return json.dumps({"error": f"Failed to fetch URL: {exc}"})

    title = inp.get("title") or ""
    text = ""
    try:
        import trafilatura

        text = trafilatura.extract(raw_html, include_links=True) or ""
        metadata = trafilatura.extract_metadata(raw_html)
        if not title and metadata and metadata.title:
            title = metadata.title
    except ImportError:
        pass

    fallback_title, fallback_text = clean_html(raw_html)
    title = title or fallback_title
    text = text or fallback_text
    path, digest, changed = _write_raw(
        title=title, body=text, category=_category(inp), source_url=url
    )
    if changed:
        append_log("ingest_url", f"{url} → {page_ref_of(path)}")

    return json.dumps(
        {
            "source_id": f"source:{digest[:16]}",
            "title": title,
            "url": url,
            "ref": page_ref_of(path),
            "file_path": str(path),
            "sha256": digest,
            "status": "ingested" if changed else "unchanged",
        }
    )


def action_ingest_file(inp: Dict[str, Any]) -> str:
    fpath = inp.get("file_path") or ""
    if not fpath:
        return json.dumps({"error": "file_path is required"})

    source = Path(fpath)
    if not source.is_file():
        return json.dumps({"error": f"File not found: {fpath}"})

    try:
        body = source.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return json.dumps({"error": f"Failed to read file: {exc}"})

    title = inp.get("title") or source.stem
    path, digest, changed = _write_raw(
        title=title, body=body, category=_category(inp), origin_path=str(source)
    )
    if changed:
        append_log("ingest_file", f"{fpath} → {page_ref_of(path)}")

    return json.dumps(
        {
            "source_id": f"source:{digest[:16]}",
            "title": title,
            "ref": page_ref_of(path),
            "file_path": str(path),
            "sha256": digest,
            "status": "ingested" if changed else "unchanged",
        }
    )


def action_get_source(inp: Dict[str, Any]) -> str:
    source_id = inp.get("source_id") or inp.get("page_ref") or ""
    if not source_id:
        return json.dumps({"error": "source_id is required"})

    needle = str(source_id).removeprefix("source:")
    for path in iter_pages():
        if path.stem == needle or path.name == needle:
            meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            return json.dumps(
                {
                    "id": meta.get("id", f"source:{needle}"),
                    "title": meta.get("title", path.stem),
                    "url": meta.get("source_url", ""),
                    "ref": page_ref_of(path),
                    "file_path": str(path),
                    "sha256": meta.get("sha256", ""),
                    "content": body,
                }
            )

    for path in iter_pages():
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        if str(meta.get("id", "")).removeprefix("source:").startswith(needle):
            return json.dumps(
                {
                    "id": meta.get("id"),
                    "title": meta.get("title", path.stem),
                    "url": meta.get("source_url", ""),
                    "ref": page_ref_of(path),
                    "file_path": str(path),
                    "sha256": meta.get("sha256", ""),
                    "content": body,
                }
            )

    return json.dumps({"error": f"Source not found: {source_id}"})


def _search(query: str, limit: int = 15) -> List[Dict[str, Any]]:
    terms = [re.escape(t.lower()) for t in query.split() if len(t) > 1]
    if not terms:
        terms = [re.escape(query.lower())]

    results: List[Dict[str, Any]] = []
    for path in iter_pages():
        try:
            meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        title = str(meta.get("title", path.stem))
        anchors = " ".join(meta.get("anchors", []) or [])
        tags = " ".join(meta.get("tags", []) or [])
        haystack = f"{title}\n{anchors}\n{tags}\n{body}".lower()

        score = 0
        snippet = ""
        for term in terms:
            if term in title.lower():
                score += 15
            if term in anchors.lower():
                score += 10
            matches = list(re.finditer(term, haystack))
            score += len(matches) * 2
            if matches and not snippet:
                idx = matches[0].start()
                snippet = haystack[max(0, idx - 80) : idx + 140].replace("\n", " ").strip()

        if score > 0:
            results.append(
                {
                    "ref": page_ref_of(path),
                    "title": title,
                    "type": meta.get("type", ""),
                    "tags": meta.get("tags", []),
                    "score": score,
                    "snippet": f"...{snippet}..." if snippet else body[:180],
                    "file_path": str(path),
                }
            )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def action_search(inp: Dict[str, Any]) -> str:
    query = inp.get("query") or ""
    if not query.strip():
        return json.dumps({"error": "query is required"})
    if not _vault().is_dir():
        return json.dumps({"error": "Wiki not initialized. Run action=init_wiki first."})
    return json.dumps(_search(query))


def action_ask(inp: Dict[str, Any]) -> str:
    question = inp.get("query") or ""
    if not question.strip():
        return json.dumps({"error": "query is required"})

    hits = _search(question, limit=5)
    if not hits:
        context_block = "No matching pages in this workspace's research wiki."
        sources_used: List[str] = []
    else:
        parts = []
        sources_used = []
        for hit in hits:
            try:
                _, body = parse_frontmatter(Path(hit["file_path"]).read_text(encoding="utf-8"))
            except Exception:
                continue
            parts.append(f"### {hit['title']} ({hit['ref']})\n{body[:2500]}")
            sources_used.append(hit["ref"])
        context_block = "\n\n---\n\n".join(parts)

    payload = {
        "model": inp.get("answer_model") or "default",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an empirical research synthesis assistant. Answer using "
                    "only the provided research context. Cite page refs and preserve "
                    "@symbol: anchors when discussing code. Say plainly when the context "
                    "does not answer the question."
                ),
            },
            {"role": "user", "content": f"RESEARCH CONTEXT:\n{context_block}\n\nQUESTION: {question}"},
        ],
        "temperature": 0.2,
    }

    try:
        req = urllib.request.Request(
            f"{LLM_GATEWAY_URL}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LITELLM_MASTER_KEY}",
            },
            data=json.dumps(payload).encode("utf-8"),
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            answer = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]
    except Exception as exc:
        answer = (
            f"(Gateway synthesis failed: {exc})\n\nTop context:\n{context_block[:1000]}"
        )

    return json.dumps({"answer": answer, "sources": sources_used})


def clean_html(html_content: str) -> Tuple[str, str]:
    """Extract page title and readable text from raw HTML without dependencies."""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
    title = re.sub(r"\s+", " ", unescape(title_match.group(1))).strip() if title_match else "Extracted Source"

    text = re.sub(r"<script[^>]*>.*?</script>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<h1[^>]*>(.*?)</h1>", r"\n# \1\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\n\1\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", text, flags=re.DOTALL | re.IGNORECASE)
    text = unescape(re.sub(r"<[^>]+>", " ", text))

    lines = [line.strip() for line in text.splitlines()]
    cleaned: List[str] = []
    blanks = 0
    for line in lines:
        if line:
            blanks = 0
            cleaned.append(line)
        else:
            blanks += 1
            if blanks <= 1:
                cleaned.append("")
    return title, "\n".join(cleaned).strip()


def handle(args, **kwargs) -> str:
    """Hermes tool handler — resolve the session workspace, then dispatch."""
    if not isinstance(args, dict):
        return json.dumps({"error": "Invalid arguments"})

    dispatch = {
        "init_wiki": action_init_wiki,
        "list_pages": action_list_pages,
        "get_page": action_get_page,
        "write_page": action_write_page,
        "ingest_url": action_ingest_url,
        "ingest_file": action_ingest_file,
        "get_source": action_get_source,
        "search": action_search,
        "ask": action_ask,
    }
    handler = dispatch.get(args.get("action"))
    if not handler:
        return json.dumps(
            {"error": f"Unknown action: {args.get('action')}", "allowed": list(dispatch)}
        )

    try:
        session_workspace()
    except WorkspaceUnresolved as exc:
        return json.dumps({"error": str(exc), "action": args.get("action")})

    try:
        return handler(args)
    except WorkspaceUnresolved as exc:
        return json.dumps({"error": str(exc), "action": args.get("action")})
    except Exception as exc:
        return json.dumps({"error": f"Execution error in {args.get('action')}: {exc}"})
