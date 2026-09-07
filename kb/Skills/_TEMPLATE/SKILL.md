# <Skill Name>

> One-line purpose: when and why to use this skill.

## When to use
- Trigger phrases / intents: <e.g. "create a skill for X", "every time we do Y">
- Preconditions: <project in AGENTS.md, files that should exist>

## Inputs
- Required: <KB files, repo path in /workspace, user-provided params>
- Optional: <context_refs, mode>

## Steps
1. Retrieve relevant KB context (AGENTS.md + Projects/<Name>/README.md, docs/architecture.md).
2. Plan: confirm scope and output location (usually `Skills/<name>/SKILL.md` or `Projects/<Name>/...`).
3. Draft the artifact directly (research, plan, or implementation) grounded in retrieved context.
4. Review the draft — reject if out-of-scope or missing citations.
5. Write final artifact yourself into `/opt/data/Personal/silverbulletKB/<path>` with a short changelog (what/why/sources).
6. Verify via KB search that the new page is retrievable; update `AGENTS.md` or `References/` if scope changed.

## Outputs
- Primary artifact: `<path in silverbulletKB>`
- Changelog: short note of what changed and source files

## Related files
- `Projects/<Name>/README.md`
- `References/<topic>.md`
- `AGENTS.md:`

## Notes for Hermes
- Keep skill short, imperative, file:lines-grounded. Prefer specific H2/H3 headings for better retrieval.
- On reuse, retrieve this skill first and follow its steps.
