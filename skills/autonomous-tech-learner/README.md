# Autonomous Tech Learner

The **Autonomous Tech Learner** is an MCP skill designed to put your AI agent (like Hermes) into a persistent, autonomous learning loop. Instead of just answering questions off the top of its head or making assumptions about your codebase, the agent will actively study official documentation and source code to gain deep, factual knowledge.

## How it Works

When triggered, the agent uses a **Hybrid Objective-Driven Approach**:
1. **Goal Setting**: The agent defines 3 to 5 specific "Learning Objectives" based on your request.
2. **Deep Dive**: It uses web search tools to read official docs, GitHub repos, and developer forums.
3. **Persistence**: Instead of losing what it learned when the context window clears, it permanently stores its synthesized notes and source URLs in **Research Brain** (native Markdown file vault).
4. **Safety**: The agent stops as soon as it meets its objectives. A hard "Safety Timeout" prevents it from looping forever.

## How to Trigger the Skill

You can trigger this skill by giving your agent a direct instruction. Here are some examples of how to prompt Hermes or any connected agent:

**Example 1: Deep Dive into a Framework**
> "I want to start using React Server Components. Please use the `autonomous-tech-learner` skill to research the best practices, gotchas, and how they handle state. Store your findings in Research Brain."

**Example 2: Complex Debugging**
> "We are getting a weird memory leak in our FastAPI WebSockets. Please use the `autonomous-tech-learner` skill to research common WebSocket memory leaks in FastAPI and Uvicorn. Once your learning objectives are met, tell me what you found."

**Example 3: Architectural Decisions**
> "Use the `autonomous-tech-learner` skill to study how graph relations work versus standard foreign keys. I need to know which one we should use for our next feature."

## Why use this instead of just asking a question?

1. **Combats Hallucination**: The agent is forced to read the *actual* documentation instead of relying on its training data.
2. **Long-Term Memory**: Because it writes to Research Brain, other agents in the `pai-stack` (and future sessions) can instantly query this knowledge without needing to learn it all over again.
3. **Actionable Wisdom**: The skill specifically instructs the agent to focus on *why* things work and *how* to apply them to debugging, rather than just copy-pasting tutorials.
