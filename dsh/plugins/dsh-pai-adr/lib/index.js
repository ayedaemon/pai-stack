/**
 * dsh-pai-adr — DSH plugin for Architecture Decision Records (ADRs).
 *
 * Provides: pai_adr_ops tool with actions:
 * - list_adrs: list ADRs in .project/planning/research/
 * - create_adr: create new ADR markdown file
 * - check_drift: detect code symbol drift against ADRs
 *
 * ADRs live in `<session workspace>/.project/planning/research/` — the same
 * path Hermes' pai_adr_ops uses, so both agents read one ADR set. Resolved per
 * call from the attached workspace; see ./session-workspace.js.
 */
import z from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";
import { existsSync, mkdirSync, readFileSync, writeFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";

import {
  WorkspaceUnresolved,
  projectDir,
  sessionWorkspace,
} from "./session-workspace.js";

export const name = "pai-adr";
export const inject = ["tools"];

export const Config = z.object({
  enabled: z.boolean().default(true),
});

function computeFileHash(filePath) {
  try {
    if (!existsSync(filePath)) return null;
    const content = readFileSync(filePath);
    return createHash("sha256").update(content).digest("hex").slice(0, 16);
  } catch {
    return null;
  }
}

/** `<workspace>/.project/planning/research` for the calling session. */
function adrDir(exec, workspaceOverride, { create = false } = {}) {
  const root = workspaceOverride
    ? join(workspaceOverride, ".project")
    : projectDir(exec);
  const research = join(root, "planning", "research");
  if (create) mkdirSync(research, { recursive: true });
  return research;
}

export function apply(ctx, config) {
  const cfg = { enabled: true, ...(config ?? {}) };
  if (!cfg.enabled) return;

  const adrTool = defineTool({
    name: "pai_adr_ops",
    description: "Living ADR creation & code symbol drift detection, scoped to the workspace attached to this session.",
    parameters: {
      action: {
        type: "string",
        required: true,
        enum: ["list_adrs", "create_adr", "check_drift"],
        description: "ADR operation to perform"
      },
      workspace: { type: "string", description: "Optional workspace override. Defaults to this session's attached workspace." },
      // create_adr
      adr_number: { type: "string", description: "ADR number (create_adr)", default: "001" },
      title: { type: "string", description: "ADR title (create_adr)" },
      context: { type: "string", description: "Context section content (create_adr)" },
      decision: { type: "string", description: "Decision section content (create_adr)" },
      symbols: {
        type: "array",
        items: { type: "string" },
        description: "Symbols to track (create_adr), each formatted @symbol:<file>:<symbol>, file relative to the workspace"
      },
    },
    output: {
      schema: { type: "json" },
      render: (_args, value) => [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value, null, 2) }]
    },
    execute(args, exec) {
      const action = args.action;
      try {
        const workspace = sessionWorkspace(exec);

        if (action === "list_adrs") {
          const researchDir = adrDir(exec, args.workspace);
          if (!existsSync(researchDir)) return { adrs: [] };
          return { adrs: readdirSync(researchDir).filter((f) => f.endsWith(".md")) };
        }

        if (action === "create_adr") {
          const adrNumber = args.adr_number || "001";
          const title = args.title || "Untitled ADR";
          const context = args.context || "";
          const decision = args.decision || "";
          const symbols = args.symbols || [];
          const researchDir = adrDir(exec, args.workspace, { create: true });

          const symbolEntries = symbols.map((sym) => {
            const match = sym.match(/@symbol:(.+):(.+)/);
            if (!match) return null;
            const [, filePath, symbolName] = match;
            return { symbol: sym, file: filePath, name: symbolName, hash: computeFileHash(join(workspace, filePath)) };
          }).filter(Boolean);

          const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
          const filepath = join(researchDir, `ADR-${adrNumber}-${slug}.md`);
          const content = `# ${title}\n\n## Context\n${context}\n\n## Decision\n${decision}\n\n## Symbols\n${symbolEntries.map((s) => `- \`${s.symbol}\` — ${s.file}:${s.name} (${s.hash || "NOT FOUND"})`).join("\n")}\n`;

          writeFileSync(filepath, content);
          return { success: true, adr_path: filepath, adr_number: adrNumber };
        }

        if (action === "check_drift") {
          const researchDir = adrDir(exec, args.workspace);
          if (!existsSync(researchDir)) return { drift: [] };
          const drift = [];
          for (const f of readdirSync(researchDir).filter((x) => x.endsWith(".md"))) {
            const content = readFileSync(join(researchDir, f), "utf8");
            for (const sym of content.match(/@symbol:[^:\s]+:[^\s]+/g) || []) {
              const match = sym.match(/@symbol:(.+):(.+)/);
              if (!match) continue;
              const [, filePath] = match;
              const currentHash = computeFileHash(join(workspace, filePath));
              const escapedSym = sym.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
              const storedMatch = content.match(new RegExp("`" + escapedSym + "`.*?\\(([^)]+)\\)"));
              const storedHash = storedMatch ? storedMatch[1] : null;
              if (currentHash && storedHash && currentHash !== storedHash) {
                drift.push({ adr: f, symbol: sym, stored: storedHash, current: currentHash });
              }
            }
          }
          return { drift };
        }

        return { error: `Unsupported action: ${action}` };
      } catch (err) {
        if (err instanceof WorkspaceUnresolved) return { error: err.message, action };
        return { error: err.message };
      }
    },
  });

  ctx.tools.register(adrTool);
}

export default { Config, apply, inject, name };
