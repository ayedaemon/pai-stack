/**
 * dsh-pai-web — DSH plugin for web search and fetch operations.
 *
 * Provides: pai_web_ops tool with actions:
 * - search, fetch, search_and_fetch
 */

import z from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";

export const name = "pai-web";
export const inject = ["tools"];

export const Config = z.object({
  enabled: z.boolean().default(true),
});

export function apply(ctx, config) {
  const cfg = { enabled: true, ...(config ?? {}) };
  if (!cfg.enabled) return;

  // Use the same web search/fetch as Hermes (via DSH's built-in tools or external API)
  const webTool = defineTool({
    name: "pai_web_ops",
    description: "Web search and fetch operations. Searches the web and fetches content from URLs.",
    parameters: {
      action: {
        type: "string",
        required: true,
        enum: ["search", "fetch", "search_and_fetch"],
        description: "Web operation to perform"
      },
      query: { type: "string", description: "Search query" },
      url: { type: "string", description: "URL to fetch" },
      urls: { type: "array", items: { type: "string" }, description: "URLs to fetch (for search_and_fetch)" },
      max_results: { type: "integer", description: "Max search results", default: 10, minimum: 1, maximum: 50 },
      recency_days: { type: "integer", description: "Limit results to last N days", minimum: 1, maximum: 365 },
      safe_search: { type: "boolean", description: "Enable safe search", default: true },
    },
    output: {
      schema: { type: "json" },
      render: (_args, value) => [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value, null, 2) }]
    },
    async execute(args) {
      const action = args.action;
      
      try {
        const mnemonTools = ctx.tools;
        if (!mnemonTools) {
          return { error: "Tools service not available" };
        }
        
        const getTool = (name) => mnemonTools.get(name);
        
        if (action === "search") {
          if (!args.query) return { error: "query required" };
          
          // Use the built-in web_search tool if available
          const tool = getTool("web_search");
          if (tool) {
            const exec = await mnemonTools.execute({
              callId: `web-search-${Date.now()}`,
              name: "web_search",
              arguments: {
                query: args.query,
                max_results: args.max_results || 10,
                recency_days: args.recency_days,
                safe_search: args.safe_search !== false,
              },
              signal: AbortSignal.none,
              agent: undefined,
            });
            return exec.isError ? { error: exec.error?.message || "Search failed" } : exec.value;
          }
          
          // Fallback: return guidance
          return { 
            error: "web_search tool not available in this DSH instance",
            hint: "Ensure DSH is configured with web search capability"
          };
        }
        
        if (action === "fetch") {
          if (!args.url) return { error: "url required" };
          
          // Use the built-in web_fetch tool if available
          const tool = getTool("web_fetch");
          if (tool) {
            const exec = await mnemonTools.execute({
              callId: `web-fetch-${Date.now()}`,
              name: "web_fetch",
              arguments: { url: args.url },
              signal: AbortSignal.none,
              agent: undefined,
            });
            return exec.isError ? { error: exec.error?.message || "Fetch failed" } : exec.value;
          }
          
          // Fallback: manual fetch
          try {
            const response = await fetch(args.url, {
              headers: {
                "User-Agent": "Mozilla/5.0 (compatible; DSH Bot/1.0)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
              },
              signal: AbortSignal.timeout(30000),
            });
            const text = await response.text();
            return { url: args.url, status: response.status, content: text.slice(0, 50000) };
          } catch (e) {
            return { error: `Fetch failed: ${e.message}` };
          }
        }
        
        if (action === "search_and_fetch") {
          if (!args.query && (!args.urls || !args.urls.length)) {
            return { error: "query or urls required" };
          }
          
          let urls = args.urls || [];
          
          if (args.query && !urls.length) {
            const tool = getTool("web_search");
            if (!tool) return { error: "web_search tool not available for search_and_fetch" };
            
            const searchExec = await mnemonTools.execute({
              callId: `search-fetch-${Date.now()}`,
              name: "web_search",
              arguments: {
                query: args.query,
                max_results: args.max_results || 5,
                recency_days: args.recency_days,
                safe_search: args.safe_search !== false,
              },
              signal: AbortSignal.none,
              agent: undefined,
            });
            
            if (searchExec.isError) return { error: searchExec.error?.message || "Search failed" };
            
            const results = searchExec.value;
            if (Array.isArray(results)) {
              urls = results.map(r => r.url || r.link).filter(Boolean);
            } else if (results?.results) {
              urls = results.results.map(r => r.url || r.link).filter(Boolean);
            }
          }
          
          if (!urls.length) return { error: "No URLs to fetch" };
          
          const fetchTool = getTool("web_fetch");
          const results = [];
          
          for (const url of urls.slice(0, 10)) {
            try {
              let content;
              if (fetchTool) {
                const exec = await mnemonTools.execute({
                  callId: `fetch-${Date.now()}-${Math.random()}`,
                  name: "web_fetch",
                  arguments: { url },
                  signal: AbortSignal.none,
                  agent: undefined,
                });
                content = exec.isError ? `Error: ${exec.error?.message}` : exec.value;
              } else {
                const response = await fetch(url, {
                  headers: { "User-Agent": "Mozilla/5.0 (compatible; DSH Bot/1.0)" },
                  signal: AbortSignal.timeout(15000),
                });
                content = await response.text();
              }
              results.push({ url, content: typeof content === "string" ? content.slice(0, 30000) : content });
            } catch (e) {
              results.push({ url, error: e.message });
            }
          }
          
          return { results };
        }
        
        return { error: `Unsupported action: ${action}` };
      } catch (err) {
        return { error: `${action}: ${err.message}` };
      }
    },
  });

  ctx.tools.register(webTool);
}

export default { Config, apply, inject, name };