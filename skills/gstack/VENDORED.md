# gstack skills — vendored provenance

Source: https://github.com/garrytan/gstack (MIT, (c) 2026 Garry Tan)
Version: 1.91.27.0 / commit c285d88 (fetched 2026-10-06, shallow clone)

Scope: curated workflow subset (26 dirs). Browser-dependent skills
(qa, qa-only, scrape, skillify, browse, design-*, canary, benchmark,
ios-*) intentionally excluded — they need gstack's browse/design
binaries, which are not installed in this stack.

Layout: `gstack` (router, from repo-root SKILL.md) + `gstack-<name>`
for each skill (upstream `--prefix` naming). Frontmatter reduced to
`name` + `description` per repo convention and the Hermes host profile
(name matches directory); bodies verbatim.

Vetting (2026-10-06, via `skill-security-auditor`):
23 PASS clean; `autoplan` CRITICAL = RegExp.exec false positive in a
TS helper; `careful` HIGH = legit `python3 -c` JSON-escaping in a hook
script (hooks don't execute under Hermes/DSH anyway). Safe to install.

Discovery: no compose/config change needed — `./skills` is already
mounted into Hermes (`/opt/pai/skills` via `skills.external_dirs`) and
DSH (`/data/dsh/.agents/skills` via `DSH_AGENTS_HOME`), so both agents
pick these up via `skills_list()` on next session/container start.

Upgrade: re-clone gstack, re-copy the same 26 dirs, re-apply the
frontmatter reduction, update Version/commit above.
