---
name: autonomous-tech-learner
description: Puts the agent into an objective-driven learning loop on specific tech topics. The agent queries official docs and forums, storing synthesized knowledge in Open Notebook until its learning objectives are met or a safety timeout occurs.
---
# Autonomous Tech Learner

> Puts the agent into a goal-oriented learning loop on specific tech topics.
> The agent queries official docs, source code, and dev forums to gain tech-specific knowledge over time.
> Synthesized knowledge is stored in Open Notebook to make the agent smarter about the codebase, debugging, and advanced concepts.

## Core Pattern

```
Learn → Synthesize → Store (Open Notebook) → Repeat until Objectives Met (or Timeout)
```

## Setup & Initialization

Before starting the learning loop, the agent MUST:
1. **Define Learning Objectives**: Explicitly list 3 to 5 specific questions, concepts, or root causes you need to understand. These are your primary exit conditions.
2. **Set a Safety Timeout**: Set a hard "circuit breaker" limit (e.g., 20 turns). This is your fallback exit condition to prevent infinite loops.
3. **Verify Open Notebook**: Ensure `notebook_ops` is available so knowledge can be saved. If `notebook_ops` is not available, you must abort or ask the user to start the Open Notebook service.

## The Learning Loop

For every iteration of the loop, follow this sequence:

### 1. Research & Retrieve
Use native web search and URL reading tools to access:
- **Official Documentation**: Prioritize official docs for the source of truth.
- **Source Code**: Read actual implementations if available (e.g., GitHub).
- **Forums/Discussions**: Check developer forums (e.g., StackOverflow, GitHub Issues) for real-world usage, gotchas, and edge cases.

### 2. Synthesize & Connect
- Analyze the retrieved information.
- Extract advanced concepts, best practices, gotchas, and debugging tips.
- Connect this new knowledge to the context of the user's current project or codebase (if applicable).

### 3. Store in Open Notebook
Use `notebook_ops` to permanently record the knowledge:
- `create_notebook` (if a notebook for this topic doesn't exist).
- `add_note` to add structured markdown notes containing the synthesized concepts, code snippets, and best practices.
- `add_source_url` to save the URLs of the official docs or forums for future reference.

### 4. Check Exit Conditions
Evaluate your progress against the exit conditions:
- **IF all Learning Objectives are confidently answered**: End the loop and output a summary of what was learned.
- **IF the Safety Timeout is reached**: End the loop immediately to prevent infinite searching and summarize what was found so far.
- **Otherwise**: Formulate the next specific query based on the remaining unanswered objectives and return to Step 1.

## Critical Rules

### 1. Persistent Storage is Mandatory
Do NOT just keep the learned knowledge in your context window. It MUST be written to Open Notebook so it survives context loss and benefits future sessions.

### 2. Prioritize High-Quality Sources
Always attempt to find the official documentation or source code before relying on third-party blogs or forums.

### 3. Focus on Actionable Knowledge
Don't just copy-paste tutorials. Extract *why* something works, *how* it applies to debugging, and advanced concepts that improve codebase quality.

### 4. Hybrid Termination Protocol
Do not research aimlessly. Your primary goal is to answer the Learning Objectives. As soon as they are met, stop. If you cannot find the answer, the Safety Timeout MUST be respected to gracefully abort.

## When to Use

- When tasked with debugging a complex issue involving an unfamiliar technology.
- When asked to refactor or improve code using "advanced concepts" of a framework.
- When the user explicitly requests the agent to study or learn a new stack/topic before making changes.
- When you need to deepen your understanding of a specific library to make architectural decisions.
