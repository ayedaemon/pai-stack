/**
 * dsh-pai-memory — DSH plugin for memory management.
 *
 * Provides: pai_memory_ops tool with actions:
 * - remember, recall, forget, search
 * - list_spaces, create_space, delete_space
 * - stats, health
 */

import z from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";

export const name = "pai-memory";
export const inject = ["tools"];

export const Config = z.object({
  enabled: z.boolean().default(true),
});

export function apply(ctx, config) {
  const cfg = { enabled: true, ...(config ?? {}) };
  if (!cfg.enabled) return;

  const memoryTool = defineTool({
    name: "pai_memory_ops",
    description: "Memory management via Mnemon. Provides remember, recall, search, and space management. Uses the dsh-mnemon plugin's mnemon_* tools internally.",
    parameters: {
      action: {
        type: "string",
        required: true,
        enum: [
          "remember", "recall", "forget", "search",
          "list_spaces", "create_space", "delete_space",
          "stats", "health"
        ],
        description: "Memory operation to perform"
      },
      content: { type: "string", description: "Content to remember" },
      category: { type: "string", enum: ["preference", "decision", "fact", "insight", "context", "general"], description: "Memory category", default: "general" },
      importance: { type: "integer", description: "Importance 1-5", default: 3, minimum: 1, maximum: 5 },
      tags: { type: "array", items: { type: "string" }, description: "Tags for the memory" },
      entities: { type: "array", items: { type: "string" }, description: "Named entities" },
      query: { type: "string", description: "Search query for recall/search" },
      mode: { type: "string", enum: ["smart", "keyword", "basic"], description: "Recall mode", default: "smart" },
      limit: { type: "integer", description: "Max results", default: 10, minimum: 1, maximum: 50 },
      memory_id: { type: "string", description: "Memory ID to forget" },
      memory_body_id: { type: "string", description: "Memory space ID" },
      space_name: { type: "string", description: "Space name for create_space" },
      space_description: { type: "string", description: "Space description for create_space" },
      space_provider: { type: "string", description: "Provider ID for create_space" },
    },
    output: {
      schema: { type: "json" },
      render: (_args, value) => [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value, null, 2) }]
    },
    async execute(args) {
      const action = args.action;
      
      try {
        // These operations delegate to the mnemon_* tools provided by dsh-mnemon plugin
        // We provide a unified interface that calls the appropriate mnemon tool
        
        const mnemonTools = ctx.tools;
        if (!mnemonTools) {
          return { error: "Memory tools not available. Ensure dsh-mnemon plugin is loaded." };
        }
        
        const getTool = (name) => mnemonTools.get(name);
        
        if (action === "remember") {
          if (!args.content) return { error: "content required" };
          const tool = getTool("mnemon_remember");
          if (!tool) return { error: "mnemon_remember tool not available" };
          
          const exec = await mnemonTools.execute({
            callId: `remember-${Date.now()}`,
            name: "mnemon_remember",
            arguments: {
              content: args.content,
              category: args.category || "general",
              importance: args.importance || 3,
              tags: args.tags || [],
              entities: args.entities || [],
              source: "agent",
              memoryBodyId: args.memory_body_id,
            },
            signal: AbortSignal.none,
            agent: undefined,
          });
          return exec.isError ? { error: exec.error?.message || "Failed to remember" } : exec.value;
        }
        
        if (action === "recall") {
          if (!args.query) return { error: "query required" };
          const tool = getTool("mnemon_recall");
          if (!tool) return { error: "mnemon_recall tool not available" };
          
          const exec = await mnemonTools.execute({
            callId: `recall-${Date.now()}`,
            name: "mnemon_recall",
            arguments: {
              query: args.query,
              mode: args.mode || "smart",
              limit: args.limit || 10,
              memoryBodyIds: args.memory_body_id ? [args.memory_body_id] : undefined,
            },
            signal: AbortSignal.none,
            agent: undefined,
          });
          return exec.isError ? { error: exec.error?.message || "Failed to recall" } : exec.value;
        }
        
        if (action === "search") {
          if (!args.query) return { error: "query required" };
          const tool = getTool("mnemon_document_search");
          if (!tool) return { error: "mnemon_document_search tool not available" };
          
          const exec = await mnemonTools.execute({
            callId: `search-${Date.now()}`,
            name: "mnemon_document_search",
            arguments: {
              query: args.query,
              limit: args.limit || 10,
            },
            signal: AbortSignal.none,
            agent: undefined,
          });
          return exec.isError ? { error: exec.error?.message || "Failed to search" } : exec.value;
        }
        
        if (action === "forget") {
          if (!args.memory_id) return { error: "memory_id required" };
          const tool = getTool("mnemon_forget");
          if (!tool) return { error: "mnemon_forget tool not available" };
          
          const exec = await mnemonTools.execute({
            callId: `forget-${Date.now()}`,
            name: "mnemon_forget",
            arguments: {
              id: args.memory_id,
              memoryBodyId: args.memory_body_id,
            },
            signal: AbortSignal.none,
            agent: undefined,
          });
          return exec.isError ? { error: exec.error?.message || "Failed to forget" } : exec.value;
        }
        
        if (action === "list_spaces") {
          const tool = getTool("mnemon_memory_bodies");
          if (!tool) return { error: "mnemon_memory_bodies tool not available" };
          
          const exec = await mnemonTools.execute({
            callId: `spaces-${Date.now()}`,
            name: "mnemon_memory_bodies",
            arguments: {},
            signal: AbortSignal.none,
            agent: undefined,
          });
          return exec.isError ? { error: exec.error?.message || "Failed to list spaces" } : exec.value;
        }
        
        if (action === "create_space") {
          if (!args.space_name) return { error: "space_name required" };
          const tool = getTool("mnemon_memory_body_create");
          if (!tool) return { error: "mnemon_memory_body_create tool not available" };
          
          const exec = await mnemonTools.execute({
            callId: `create-space-${Date.now()}`,
            name: "mnemon_memory_body_create",
            arguments: {
              name: args.space_name,
              description: args.space_description || "",
              providerId: args.space_provider,
              reason: "Created via pai_memory_ops",
              confidence: "high",
            },
            signal: AbortSignal.none,
            agent: undefined,
          });
          return exec.isError ? { error: exec.error?.message || "Failed to create space" } : exec.value;
        }
        
        if (action === "delete_space") {
          if (!args.memory_body_id) return { error: "memory_body_id required" };
          const tool = getTool("mnemon_memory_body_update");
          if (!tool) return { error: "mnemon_memory_body_update tool not available" };
          
          const exec = await mnemonTools.execute({
            callId: `delete-space-${Date.now()}`,
            name: "mnemon_memory_body_update",
            arguments: {
              memoryBodyId: args.memory_body_id,
              active: false,
            },
            signal: AbortSignal.none,
            agent: undefined,
          });
          return exec.isError ? { error: exec.error?.message || "Failed to deactivate space" } : exec.value;
        }
        
        if (action === "stats") {
          const tool = getTool("mnemon_status");
          if (!tool) return { error: "mnemon_status tool not available" };
          
          const exec = await mnemonTools.execute({
            callId: `stats-${Date.now()}`,
            name: "mnemon_status",
            arguments: {},
            signal: AbortSignal.none,
            agent: undefined,
          });
          return exec.isError ? { error: exec.error?.message || "Failed to get stats" } : exec.value;
        }
        
        if (action === "health") {
          const tool = getTool("mnemon_status");
          if (!tool) return { error: "mnemon_status tool not available" };
          
          const exec = await mnemonTools.execute({
            callId: `health-${Date.now()}`,
            name: "mnemon_status",
            arguments: {},
            signal: AbortSignal.none,
            agent: undefined,
          });
          return exec.isError ? { error: exec.error?.message || "Health check failed" } : exec.value;
        }
        
        return { error: `Unsupported action: ${action}` };
      } catch (err) {
        return { error: `${action}: ${err.message}` };
      }
    },
  });

  ctx.tools.register(memoryTool);
}

export default { Config, apply, inject, name };