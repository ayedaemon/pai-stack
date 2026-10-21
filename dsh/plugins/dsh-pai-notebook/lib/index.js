/**
 * dsh-pai-notebook — DSH plugin for the Research Brain wiki.
 *
 * Provides: pai_notebook_ops tool with actions:
 * - init_wiki, list_pages, get_page, write_page
 * - ingest_url, ingest_file, get_source
 * - search, ask
 *
 * Storage is a Markdown wiki at `<session workspace>/.project/research/`:
 *
 *   SCHEMA.md        conventions, tag taxonomy, domain     (agent-authored)
 *   index.md         sectioned catalog, one-line summaries (tool-maintained)
 *   log.md           append-only action log                (tool-maintained)
 *   raw/<category>/  Layer 1: immutable ingested sources
 *   entities/        Layer 2: people, orgs, products, models
 *   concepts/        Layer 2: topics, techniques
 *   comparisons/     Layer 2: side-by-side analyses
 *   queries/         Layer 2: filed answers worth keeping
 *   _archive/        superseded pages, delinked from index
 *
 * The workspace is the one attached to the calling session
 * (`exec.agent.session.header.cwd`), resolved per call — see
 * ./session-workspace.js. Mirrors hermes/plugins/pai_tools/notebook_ops.py;
 * keep the two layouts and action names in step.
 */

import z from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { basename, join, relative } from "node:path";
import {
  WorkspaceUnresolved,
  researchDir,
} from "./session-workspace.js";

export const name = "pai-notebook";
export const inject = ["tools"];

export const Config = z.object({
  enabled: z.boolean().default(true),
});

const PAGE_SECTIONS = ["entities", "concepts", "comparisons", "queries"];
const SOURCE_CATEGORIES = ["articles", "papers", "docs", "notes", "other"];
// _archive is addressable but excluded from search so superseded knowledge
// never resurfaces as current.
const ADDRESSABLE_DIRS = [...PAGE_SECTIONS, "raw", "_archive"];
const INDEX_TOTAL_PREFIX = "Total pages:";
const MAX_LOG_ENTRIES = 500;

// ── Vault helpers ───────────────────────────────────────────────────────────

function slugify(text) {
  return (
    String(text ?? "")
      .toLowerCase()
      .replace(/[^\w\s-]/g, "")
      .trim()
      .replace(/[-\s]+/g, "-")
      .slice(0, 60) || "untitled"
  );
}

function now() {
  return new Date().toISOString().replace("T", " ").replace(/\.\d+Z$/, "+00:00");
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

function extractAnchors(text) {
  if (!text) return [];
  const raw = text.match(/@symbol:[^\s\)`"']+/g) || [];
  return [...new Set(raw.map((r) => r.replace(/[.,;:)!?'"]+$/, "")))].sort();
}

function extractWikilinks(text) {
  if (!text) return [];
  return [...new Set([...text.matchAll(/\[\[([^\]]+)\]\]/g)].map((m) => m[1].trim()))].sort();
}

function parseFrontmatter(content) {
  if (!content.startsWith("---")) return { meta: {}, body: content };
  const parts = content.split("---", 3);
  if (parts.length < 3) return { meta: {}, body: content };

  const meta = {};
  let listKey = null;
  for (const line of parts[1].split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    if (trimmed.startsWith("- ") && listKey) {
      meta[listKey] = [...(meta[listKey] || []), trimmed.slice(2).replace(/^["']|["']$/g, "")];
      continue;
    }
    const idx = trimmed.indexOf(":");
    if (idx > 0) {
      const key = trimmed.slice(0, idx).trim();
      const val = trimmed.slice(idx + 1).trim().replace(/^["']|["']$/g, "");
      if (!val) {
        listKey = key;
        meta[key] = [];
      } else {
        listKey = null;
        meta[key] = val;
      }
    }
  }
  return { meta, body: parts[2].trim() };
}

/** Resolve a directory to its real on-disk name, matching case exactly. */
function canonicalDir(dir) {
  try {
    if (!existsSync(dir) || !statSync(dir).isDirectory()) return null;
    const parent = dirnameOf(dir);
    if (!parent) return null;
    const target = basename(dir).toLowerCase();
    for (const entry of readdirSync(parent, { withFileTypes: true })) {
      if (entry.isDirectory() && entry.name.toLowerCase() === target) {
        return join(parent, entry.name);
      }
    }
  } catch {}
  return null;
}

function dirnameOf(dir) {
  const idx = dir.lastIndexOf("/");
  return idx <= 0 ? dir : dir.slice(0, idx);
}

/** Resolve `dir/name` to a real on-disk file, matching case exactly. */
function exactEntry(dir, name) {
  if (!dir) return null;
  try {
    const target = name.toLowerCase();
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isFile() && entry.name.toLowerCase() === target) return join(dir, entry.name);
    }
  } catch {}
  return null;
}

function sectionDir(vault, section) {
  return canonicalDir(join(vault, section));
}

/**
 * Resolve a page ref (`section/slug.md`, bare slug, or wikilink target) to a
 * real file. Case-exact throughout: vaults are written from macOS and read
 * from this Linux container, where a wrong-case path simply does not exist.
 */
function resolvePageRef(vault, ref) {
  if (!ref || !existsSync(vault)) return null;
  const norm = String(ref).trim().replace(/^\[\[|\]\]$/g, "").replace(/\.md$/, "").replace(/^\/+|\/+$/g, "");
  if (!norm) return null;

  if (norm.includes("/")) {
    const [head, ...rest] = norm.split("/");
    const tail = rest.join("/");
    let hit = exactEntry(sectionDir(vault, head), `${tail}.md`);
    if (hit) return hit;
    for (const section of ADDRESSABLE_DIRS) {
      if (section.toLowerCase() === head.toLowerCase()) {
        hit = exactEntry(sectionDir(vault, section), `${tail}.md`);
        if (hit) return hit;
      }
    }
    return null;
  }

  for (const section of ADDRESSABLE_DIRS) {
    const hit = exactEntry(sectionDir(vault, section), `${norm}.md`);
    if (hit) return hit;
  }

  const needle = norm.toLowerCase();
  for (const section of ADDRESSABLE_DIRS) {
    const dir = sectionDir(vault, section);
    if (!dir) continue;
    for (const path of walk(dir)) {
      const { meta } = parseFrontmatter(readFileSync(path, "utf8"));
      if (String(meta.title ?? "").trim().toLowerCase() === needle) return path;
    }
  }
  return null;
}

function* walk(dir) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(full);
    else if (entry.isFile() && entry.name.endsWith(".md")) yield full;
  }
}

function pageRef(vault, path) {
  return relative(vault, path).replace(/\.md$/, "").replace(/^\/+|\/+$/g, "");
}

function iterPages(vault, includeArchive = false) {
  const sections = includeArchive ? ADDRESSABLE_DIRS : ADDRESSABLE_DIRS.slice(0, -1);
  const pages = [];
  for (const section of sections) {
    const dir = sectionDir(vault, section);
    if (dir) pages.push(...walk(dir));
  }
  return pages.sort();
}

function summarize(body, limit = 120) {
  for (const block of body.split(/\n\s*\n/)) {
    const text = block
      .split("\n")
      .filter((l) => l.trim() && !l.startsWith("#") && !l.startsWith("---") && !l.startsWith(">"))
      .map((l) => l.trim())
      .join(" ")
      .replace(/\[\[([^\]]+)\]\]/g, "$1");
    if (text.length >= 12) return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
  }
  return "";
}

// ── index.md / log.md bookkeeping ───────────────────────────────────────────

function registerInIndex(vault, ref, summary) {
  const path = join(vault, "index.md");
  const section = ref.includes("/") ? ref.split("/")[0][0].toUpperCase() + ref.split("/")[0].slice(1) : "Queries";
  const entry = `- [[${ref}]]${summary ? ` — ${summary}` : ""}`;

  let lines = existsSync(path) ? readFileSync(path, "utf8").split("\n") : ["# Research Index", ""];
  const start = lines.findIndex((l) => l.trim() === `## ${section}`);

  if (start === -1) {
    lines = [...lines, "", `## ${section}`, "", entry, ""];
  } else {
    let end = lines.findIndex((l, i) => i > start && l.startsWith("## "));
    if (end === -1) end = lines.length;
    const block = lines
      .slice(start + 1, end)
      .filter((l) => l.trim().startsWith("- [[") && l.trim() !== `- [[${ref}]]`)
      .concat(entry)
      .sort((a, b) => a.trim().toLowerCase().localeCompare(b.trim().toLowerCase()));
    // Blank line between entries, and one after the block, keeps index.md
    // readable Markdown rather than a dense machine map.
    const rebuilt = block.flatMap((line, i) => (i ? ["", line] : [line]));
    lines = [...lines.slice(0, start + 1), "", ...rebuilt, "", ...lines.slice(end)];
  }

  const total = lines.filter((l) => l.trim().startsWith("- [[")).length;
  lines = lines.map((l) =>
    l.startsWith(INDEX_TOTAL_PREFIX) ? `${INDEX_TOTAL_PREFIX} ${total}` : l,
  );
  lines = lines.map((l) => (l.startsWith("_Updated ") ? `_Updated ${today()}_` : l));
  writeFileSync(path, `${lines.join("\n").replace(/\n+$/, "")}\n`, "utf8");
}

function appendLog(vault, action, detail) {
  const path = join(vault, "log.md");
  const entry = `- ${new Date().toISOString().replace(/\.\d+Z$/, "Z")} | ${action} | ${detail}`;
  if (!existsSync(path)) {
    writeFileSync(path, `# Research Log\n\n${entry}\n`, "utf8");
  } else {
    writeFileSync(path, `${readFileSync(path, "utf8").replace(/\n*$/, "\n")}${entry}\n`, "utf8");
  }
  rotateLog(vault);
}

function rotateLog(vault) {
  const path = join(vault, "log.md");
  if (!existsSync(path)) return;
  const lines = readFileSync(path, "utf8").split("\n");
  const entries = lines.filter((l) => l.startsWith("- "));
  if (entries.length <= MAX_LOG_ENTRIES) return;
  const year = today().slice(0, 4);
  writeFileSync(join(vault, `log-${year}.md`), `${entries.join("\n")}\n`, "utf8");
  writeFileSync(
    path,
    `${[...lines.filter((l) => !l.startsWith("- ")), `- ${entries.length} entries rotated to log-${year}.md`].join("\n")}\n`,
    "utf8",
  );
}

// ── Ingest ──────────────────────────────────────────────────────────────────

function writeRaw(vault, { title, body, category, sourceUrl = "", originPath = "" }) {
  mkdirSync(join(vault, "raw", category), { recursive: true });
  const ref = `raw/${category}/${slugify(title)}`;
  const path = join(vault, `${ref}.md`);
  const digest = createHash("sha256").update(body.trim()).digest("hex");

  if (existsSync(path)) {
    // Compare the recorded digest of the source body, not the assembled
    // document (which carries its own title + provenance block).
    const { meta } = parseFrontmatter(readFileSync(path, "utf8"));
    if (meta.sha256 === digest) return { path, ref, digest, changed: false };
  }

  const sourceId = `source:${digest.slice(0, 16)}`;
  const provenance = sourceUrl
    ? `**Source URL**: [${sourceUrl}](${sourceUrl})`
    : `**Source File**: \`${originPath}\``;
  const frontmatter = [
    "---",
    `title: ${JSON.stringify(title)}`,
    "type: raw",
    `id: "${sourceId}"`,
    ...(sourceUrl ? [`source_url: "${sourceUrl}"`] : []),
    ...(originPath ? [`file_path: "${originPath}"`] : []),
    `ingested: "${now()}"`,
    `sha256: ${digest}`,
    "---\n",
  ];
  writeFileSync(path, `${frontmatter.join("\n")}\n# ${title}\n\n${provenance}\n\n${body.trim()}\n`, "utf8");
  return { path, ref, digest, changed: true };
}

function categoryOf(args) {
  return SOURCE_CATEGORIES.includes(args.category) ? args.category : "articles";
}

// ── Search / ask ────────────────────────────────────────────────────────────

function searchPages(vault, query, limit = 15) {
  let terms = query.split(/\s+/).filter((t) => t.length > 1).map((t) => t.toLowerCase());
  if (terms.length === 0) terms = [query.toLowerCase()];

  const results = [];
  for (const path of iterPages(vault)) {
    let meta;
    let body;
    try {
      ({ meta, body } = parseFrontmatter(readFileSync(path, "utf8")));
    } catch {
      continue;
    }
    const title = String(meta.title ?? basename(path, ".md"));
    const anchors = (meta.anchors ?? []).join(" ");
    const tags = (meta.tags ?? []).join(" ");
    const haystack = `${title}\n${anchors}\n${tags}\n${body}`.toLowerCase();

    let score = 0;
    let snippet = "";
    for (const term of terms) {
      if (title.toLowerCase().includes(term)) score += 15;
      if (anchors.toLowerCase().includes(term)) score += 10;
      const matches = haystack.match(new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g")) || [];
      score += matches.length * 2;
      if (matches.length && !snippet) {
        const idx = haystack.indexOf(term);
        snippet = haystack.slice(Math.max(0, idx - 80), idx + 140).replace(/\n/g, " ").trim();
      }
    }
    if (score > 0) {
      results.push({
        ref: pageRef(vault, path),
        title,
        type: meta.type ?? "",
        tags: meta.tags ?? [],
        score,
        snippet: snippet ? `...${snippet}...` : body.slice(0, 180),
        file_path: path,
      });
    }
  }
  results.sort((a, b) => b.score - a.score);
  return results.slice(0, limit);
}

function stripHtml(html) {
  let text = html
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<nav[\s\S]*?<\/nav>/gi, "")
    .replace(/<footer[\s\S]*?<\/footer>/gi, "")
    .replace(/<h1[^>]*>([\s\S]*?)<\/h1>/gi, "\n# $1\n")
    .replace(/<h2[^>]*>([\s\S]*?)<\/h2>/gi, "\n## $1\n")
    .replace(/<h3[^>]*>([\s\S]*?)<\/h3>/gi, "\n### $1\n")
    .replace(/<p[^>]*>([\s\S]*?)<\/p>/gi, "\n$1\n")
    .replace(/<li[^>]*>([\s\S]*?)<\/li>/gi, "\n- $1")
    .replace(/<[^>]+>/g, " ");
  text = text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ");

  const out = [];
  let blanks = 0;
  for (const line of text.split("\n").map((l) => l.replace(/\s+/g, " ").trim())) {
    if (line) {
      blanks = 0;
      out.push(line);
    } else if (++blanks <= 1) {
      out.push("");
    }
  }
  return out.join("\n").trim();
}

// ── Plugin ──────────────────────────────────────────────────────────────────

export function apply(ctx, config) {
  const cfg = { enabled: true, ...(config ?? {}) };
  if (!cfg.enabled) return;

  const LLM_GATEWAY_URL =
    process.env.LLM_GATEWAY_URL ||
    process.env.LLM_GATEWAY_BASE_URL ||
    "http://llm-gateway:4000/v1";
  const LITELLM_MASTER_KEY = process.env.LITELLM_MASTER_KEY || "not-needed";

  const notebookTool = defineTool({
    name: "pai_notebook_ops",
    description:
      "Research Brain wiki for the workspace attached to this session, at " +
      "<workspace>/.project/research/. Immutable raw/ source layer plus agent-owned " +
      "entity/concept/comparison/query pages with YAML frontmatter and [[wikilinks]]. " +
      "Use for external knowledge: RFCs, papers, API docs, web articles, evidence notes.",
    parameters: {
      action: {
        type: "string",
        required: true,
        enum: [
          "init_wiki", "list_pages", "get_page", "write_page",
          "ingest_url", "ingest_file", "get_source",
          "search", "ask",
        ],
        description:
          "init_wiki: create SCHEMA.md/index.md/log.md for a new vault. " +
          "list_pages: inventory the wiki. get_page: read one page by ref. " +
          "write_page: create/update a Layer 2 page and register it in index.md + log.md. " +
          "ingest_url: fetch a URL into raw/ as an immutable source. " +
          "ingest_file: capture a local file into raw/. " +
          "get_source: full text of an ingested source. " +
          "search: score pages against a query. ask: grounded synthesis via the gateway.",
      },
      page_ref: {
        type: "string",
        description:
          "Page ref relative to the vault, e.g. 'concepts/attention.md' or 'entities/acme'. " +
          "Bare slugs match across sections.",
      },
      section: {
        type: "string",
        enum: PAGE_SECTIONS,
        description: "Layer 2 section for write_page (default: concepts).",
      },
      title: { type: "string", description: "Page title. Required for write_page and ingest_url." },
      content: { type: "string", description: "Markdown body for write_page." },
      summary: { type: "string", description: "One-line summary for index.md. Defaults to the first paragraph." },
      tags: { type: "array", items: { type: "string" }, description: "Tags for write_page, from the SCHEMA.md taxonomy." },
      sources: { type: "array", items: { type: "string" }, description: "Provenance refs, e.g. ['raw/articles/foo']." },
      url: { type: "string", description: "URL to ingest (ingest_url)." },
      category: { type: "string", enum: SOURCE_CATEGORIES, description: "raw/<category>/ bucket for ingest (default: articles)." },
      file_path: { type: "string", description: "Path to a local file to capture (ingest_file)." },
      source_id: { type: "string", description: "Source id from an ingest result (get_source)." },
      query: { type: "string", description: "Search query, or the question for ask." },
      answer_model: { type: "string", description: "Model override for the ask synthesis." },
    },
    output: {
      schema: { type: "json" },
      render: (_args, value) => [
        { type: "text", text: typeof value === "string" ? value : JSON.stringify(value, null, 2) },
      ],
    },

    async execute(args, exec) {
      const action = args.action;
      let vault;
      try {
        vault = researchDir(exec);
      } catch (err) {
        if (err instanceof WorkspaceUnresolved) {
          return { error: err.message, action };
        }
        throw err;
      }

      try {
        switch (action) {
          case "init_wiki": {
            mkdirSync(vault, { recursive: true });
            const domain = (args.content || args.summary || "").trim();
            const created = [];

            if (!existsSync(join(vault, "SCHEMA.md"))) {
              writeFileSync(
                join(vault, "SCHEMA.md"),
                `---
title: Research Schema
created: "${now()}"
---

# SCHEMA

${domain ? `**Domain**: ${domain}` : "**Domain**: _undeclared — set this before the first ingest._"}

## Filenames
lowercase, hyphens (\`transformer-architecture.md\`).

## Page frontmatter (required on every Layer 2 page)
\`title, created, updated, type: entity|concept|comparison|query|summary, tags, sources\`

## Rules
- Every Layer 2 page carries >= 2 \`[[wikilinks]]\`, cross-referenced both directions.
- Bump \`updated\` on every edit; add the page to \`index.md\`; append to \`log.md\`.
- Tags come only from the taxonomy below — extend it here first.
- Create a page when an entity appears in 2+ sources or is central to one.
- Split a page past ~200 lines.
- \`raw/\` is immutable. Superseded pages move to \`_archive/\` and leave \`index.md\`.
- Contradictions stay side by side with dates, marked \`contested: true\`.
- Set \`confidence: high|medium|low\` for opinion-heavy or fast-moving claims.

## Tag taxonomy
<!-- add tags here as the domain demands; nothing outside this list is valid -->
- general
`,
                "utf8",
              );
              created.push("SCHEMA.md");
            }

            if (!existsSync(join(vault, "index.md"))) {
              writeFileSync(
                join(vault, "index.md"),
                `# Research Index\n\n## Entities\n\n## Concepts\n\n## Comparisons\n\n## Queries\n\n${INDEX_TOTAL_PREFIX} 0\n\n_Updated ${today()}_\n`,
                "utf8",
              );
              created.push("index.md");
            }

            if (!existsSync(join(vault, "log.md"))) {
              writeFileSync(join(vault, "log.md"), "# Research Log\n", "utf8");
              created.push("log.md");
            }

            if (created.length) appendLog(vault, "init_wiki", `initialized ${created.join(", ")}`);
            return { vault, created, already_initialized: created.length === 0 };
          }

          case "list_pages": {
            if (!existsSync(vault)) {
              return { error: "Wiki not initialized. Run action=init_wiki first." };
            }
            const sections = {};
            let rawCount = 0;
            let layer2Count = 0;
            for (const section of ADDRESSABLE_DIRS) {
              const entries = [];
              for (const path of iterPages(vault, true)) {
                if (pageRef(vault, path).split("/")[0] !== section) continue;
                const { meta } = parseFrontmatter(readFileSync(path, "utf8"));
                entries.push({
                  ref: pageRef(vault, path),
                  title: meta.title ?? basename(path, ".md"),
                  updated: meta.updated ?? "",
                  tags: meta.tags ?? [],
                });
              }
              if (!entries.length) continue;
              sections[section] = entries;
              if (section === "raw") rawCount = entries.length;
              else layer2Count += entries.length;
            }
            return {
              vault,
              layer2_pages: layer2Count,
              raw_sources: rawCount,
              sections,
              has_schema: existsSync(join(vault, "SCHEMA.md")),
            };
          }

          case "get_page": {
            if (!args.page_ref) return { error: "page_ref is required" };
            const path = resolvePageRef(vault, args.page_ref);
            if (!path) return { error: `Page not found: ${args.page_ref}` };
            const { meta, body } = parseFrontmatter(readFileSync(path, "utf8"));
            return {
              ref: pageRef(vault, path),
              file_path: path,
              metadata: meta,
              anchors: extractAnchors(body),
              wikilinks: extractWikilinks(body),
              content: body,
            };
          }

          case "write_page": {
            const title = (args.title || "").trim();
            const content = args.content || "";
            if (!title) return { error: "title is required" };
            if (!content.trim()) return { error: "content is required" };

            const section = args.section || "concepts";
            if (!PAGE_SECTIONS.includes(section)) {
              return { error: `section must be one of ${PAGE_SECTIONS.join(", ")}` };
            }

            mkdirSync(join(vault, section), { recursive: true });
            const ref = `${section}/${slugify(title)}`;
            const path = join(vault, `${ref}.md`);

            const existed = existsSync(path);
            const priorMeta = existed ? parseFrontmatter(readFileSync(path, "utf8")).meta : {};

            // Carry created/anchors forward so an update is not a rewrite.
            const mergedSources = [...(args.sources || toArray(priorMeta.sources))];
            for (const link of extractWikilinks(content)) {
              if (!mergedSources.includes(link)) mergedSources.push(link);
            }

            const anchors = extractAnchors(content);
            const tags = args.tags || toArray(priorMeta.tags);
            const summary = (args.summary || "").trim() || summarize(content);

            const frontmatter = [
              "---",
              `title: ${JSON.stringify(title)}`,
              `type: "${section === "queries" ? "query" : section.replace(/s$/, "")}"`,
              `created: "${priorMeta.created || now()}"`,
              `updated: "${now()}"`,
            ];
            if (tags.length) frontmatter.push("tags:", ...tags.map((t) => `  - "${t}"`));
            if (mergedSources.length) {
              frontmatter.push("sources:", ...mergedSources.map((s) => `  - "${s}"`));
            }
            if (anchors.length) frontmatter.push("anchors:", ...anchors.map((a) => `  - "${a}"`));
            frontmatter.push("confidence: medium", "---\n");

            writeFileSync(path, `${frontmatter.join("\n")}\n# ${title}\n\n${content.trim()}\n`, "utf8");

            registerInIndex(vault, ref, summary);
            appendLog(vault, "write_page", `${existed ? "updated" : "created"} ${ref}`);

            const links = extractWikilinks(content);
            const broken = links.filter((l) => !resolvePageRef(vault, l));
            const warnings = [];
            if (links.length < 2) {
              warnings.push(`Only ${links.length} [[wikilink]] found — pages need >= 2 to stay reachable.`);
            }
            if (broken.length) {
              warnings.push(
                `These [[wikilinks]] point at pages that do not exist yet: ${broken.join(", ")}`,
              );
            }
            if (!mergedSources.length) {
              warnings.push("No [[wikilinks]] or sources recorded — page is an orphan.");
            }

            return { ref, file_path: path, created: !existed, summary, anchors, wikilinks: links, broken_links: broken, warnings };
          }

          case "ingest_url": {
            if (!args.url) return { error: "url is required" };
            let html;
            try {
              const res = await fetch(args.url, {
                headers: {
                  "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                  Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                signal: AbortSignal.timeout(20000),
              });
              html = await res.text();
            } catch (e) {
              return { error: `Failed to fetch URL: ${e.message}` };
            }

            const titleMatch = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
            const title = (args.title || (titleMatch ? titleMatch[1].replace(/\s+/g, " ").trim() : "")) || "Web Source";
            const result = writeRaw(vault, { title, body: stripHtml(html), category: categoryOf(args), sourceUrl: args.url });
            if (result.changed) appendLog(vault, "ingest_url", `${args.url} → ${result.ref}`);
            return {
              source_id: `source:${result.digest.slice(0, 16)}`,
              title,
              url: args.url,
              ref: result.ref,
              file_path: result.path,
              sha256: result.digest,
              status: result.changed ? "ingested" : "unchanged",
            };
          }

          case "ingest_file": {
            if (!args.file_path) return { error: "file_path is required" };
            let body;
            try {
              body = readFileSync(args.file_path, "utf8");
            } catch (e) {
              return { error: `Failed to read file: ${e.message}` };
            }
            const title = args.title || basename(args.file_path).replace(/\.[^.]+$/, "");
            const result = writeRaw(vault, { title, body, category: categoryOf(args), originPath: args.file_path });
            if (result.changed) appendLog(vault, "ingest_file", `${args.file_path} → ${result.ref}`);
            return {
              source_id: `source:${result.digest.slice(0, 16)}`,
              title,
              ref: result.ref,
              file_path: result.path,
              sha256: result.digest,
              status: result.changed ? "ingested" : "unchanged",
            };
          }

          case "get_source": {
            const sourceId = args.source_id || args.page_ref || "";
            if (!sourceId) return { error: "source_id is required" };
            const needle = sourceId.replace(/^source:/, "");
            for (const path of iterPages(vault)) {
              const { meta, body } = parseFrontmatter(readFileSync(path, "utf8"));
              const id = String(meta.id ?? "").replace(/^source:/, "");
              if (path.endsWith(`${needle}.md`) || id.startsWith(needle)) {
                return {
                  id: meta.id ?? `source:${needle}`,
                  title: meta.title ?? basename(path, ".md"),
                  url: meta.source_url ?? "",
                  ref: pageRef(vault, path),
                  file_path: path,
                  sha256: meta.sha256 ?? "",
                  content: body,
                };
              }
            }
            return { error: `Source not found: ${sourceId}` };
          }

          case "search": {
            if (!args.query || !args.query.trim()) return { error: "query is required" };
            if (!existsSync(vault)) return { error: "Wiki not initialized. Run action=init_wiki first." };
            return { results: searchPages(vault, args.query) };
          }

          case "ask": {
            const question = args.query || "";
            if (!question.trim()) return { error: "query is required" };

            const hits = existsSync(vault) ? searchPages(vault, question, 5) : [];
            let contextBlock = "No matching pages in this workspace's research wiki.";
            const sourcesUsed = [];
            if (hits.length) {
              const parts = [];
              for (const hit of hits) {
                try {
                  const { body } = parseFrontmatter(readFileSync(hit.file_path, "utf8"));
                  parts.push(`### ${hit.title} (${hit.ref})\n${body.slice(0, 2500)}`);
                  sourcesUsed.push(hit.ref);
                } catch {}
              }
              contextBlock = parts.join("\n\n---\n\n");
            }

            let answer;
            try {
              const response = await fetch(`${LLM_GATEWAY_URL}/chat/completions`, {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                  Authorization: `Bearer ${LITELLM_MASTER_KEY}`,
                },
                body: JSON.stringify({
                  model: args.answer_model || "default",
                  messages: [
                    {
                      role: "system",
                      content:
                        "You are an empirical research synthesis assistant. Answer using only " +
                        "the provided research context. Cite page refs and preserve @symbol: " +
                        "anchors when discussing code. Say plainly when the context does not " +
                        "answer the question.",
                    },
                    { role: "user", content: `RESEARCH CONTEXT:\n${contextBlock}\n\nQUESTION: ${question}` },
                  ],
                  temperature: 0.2,
                }),
                signal: AbortSignal.timeout(60000),
              });
              const data = await response.json();
              answer = data.choices?.[0]?.message?.content || "(No response from LLM gateway)";
            } catch (e) {
              answer = `(Gateway synthesis failed: ${e.message})\n\nTop context:\n${contextBlock.slice(0, 1000)}`;
            }
            return { answer, sources: sourcesUsed };
          }

          default:
            return { error: `Unsupported action: ${action}` };
        }
      } catch (err) {
        return { error: `${action}: ${err.message}` };
      }
    },
  });

  ctx.tools.register(notebookTool);
}

function toArray(value) {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
}

export default { Config, apply, inject, name };
