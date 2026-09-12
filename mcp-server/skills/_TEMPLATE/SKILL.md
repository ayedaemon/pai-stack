# <Skill Name>

> One-line purpose: when and why to use this skill.

## When to use
- Trigger phrases / intents: <e.g. "create a skill for X", "every time we do Y">
- Preconditions: <project in AGENTS.md, files that should exist>

## Inputs
- Required: <KB files, repo path in /opt/data/workspace, user-provided params>
- Optional: <context_refs, mode>

## Steps
1. Retrieve relevant context from CodeGraph: `GET /search?type=semantic` scoped to the project.
2. Plan: confirm scope and output location (usually `Skills/<name>/SKILL.md` in the project or bundled MCP).
3. Draft the artifact directly (research, plan, or implementation) grounded in retrieved context.
4. Review the draft — reject if out-of-scope or missing citations.
5. Write final artifact to `/opt/data/workspace/<project>/<path>` with a short changelog (what/why/sources). Save findings to `findings.md`.
6. Verify via CodeGraph search that the new file is indexed and retrievable.

## Outputs
- Primary artifact: `<path in project>`
- Changelog: short note of what changed and source files, written to `progress.md`

## Related files
- `/opt/data/workspace/<project>/task_plan.md`
- `/opt/data/workspace/<project>/findings.md`
- `skill://planning`

## Notes for Hermes
- Keep skill short, imperative, file:lines-grounded. Prefer specific H2/H3 headings for better retrieval.
- On reuse, retrieve this skill first and follow its steps.
- Write output to `/opt/data/workspace/<project>/` and update `progress.md` with what changed.
