# Agent Contract — Shared Blackboard Pair Programming

> Drop-in contract. Any agent that implements this file + `skills/pair-programming/SKILL.md`
> can replace Hermes or DSH with zero container changes. Version: 1.

## 1. Paths (all inside the repo = shared space)

```
pair/
  AGENT_CONTRACT.md   # this file (normative)
  STATE.md            # human dashboard, updated on every claim/done
  queue/<slug>.md     # status: pending, owner: unclaimed
  claims/<slug>.md    # status: claimed, owner set (the lock)
  done/<slug>.md      # status: done, verdict filled
  log.md              # append-only: `YYYY-MM-DDTHH:MMZ | actor | event | slug`
scripts/pair/         # python3 helpers (stdlib only), runnable from host + both containers
                      # status.py, claim.py, done.py, poke.py — python3 ships in both images
skills/pair-programming/SKILL.md  # poll/work/return/notify discipline (both agents load it)
```

Planning discipline files stay in `.planning/` (see `planning` skill).
Knowledge graduates to `research/` + ADRs (see `research` skill). `pair/` is
operational only — never a knowledge base.

## 2. Canonical paths (both agents, no exceptions)

Every path in pair/ files, prompts, poke messages, and agent reports is the
CONTAINER-absolute form: `/opt/data/workspace/<...>`. Both agents mount the
workspace at the identical path (verified: same realpath, same listing), so a
container path is unambiguous to either side.

Host forms (`~/Personal/...`, `/Users/.../Personal/...`) must NEVER appear —
normalize on intake with `python3 scripts/pair/path.py <path>` (also accepts
`--to host` for your own copy-paste and `--map` for the table). A task file
containing a host-form path is malformed: return it to queue with the reason.

## 3. Task file schema (frontmatter is normative)

```yaml
---
slug: <kebab>-YYYY-MM-DD          # unique, matches filename
status: pending|claimed|done      # location must match: queue/claims/done/
owner: unclaimed|hermes|dsh|<id>  # who holds the lock
execution_dir: /opt/data/workspace/<path>  # EXECUTION_DIR invariant (agents skill)
branch: pair/<slug>               # distinct branch per task
worktree: .worktrees/<slug>       # per gitops skill, never peer's worktree
acceptance: <exact test cmd>      # how done is proven
rounds_left: 2                    # hard cap on handoffs, decrement per return
created_by: hermes|dsh|human
---
## Task
## Context
## Verdict                    # filled only on done
```

## 4. Claim rule (the lock)

Claim = `python3 scripts/pair/claim.py <slug> <my-id>` (atomic move
pair/queue/<slug>.md -> pair/claims/<slug>.md) + set
`status: claimed`, `owner: <me>` in the moved file + append `log.md` +
update `STATE.md`. Same filesystem → the move is atomic. If the source file is
gone, someone else claimed it: re-list, pick another. Never copy — move.
Hold at most ONE claim at a time — finish or return it before claiming again.
Never edit `claims/<other-owner>/*.md` except to add a review comment
section (interim review path).

## 5. Work rule

1. `git worktree add .worktrees/<slug> -b pair/<slug> <base>` (clean tree only,
   per `gitops` skill — propose command, wait for approval if human is present;
   autonomous between gates: record approval basis in task file).
2. Work ONLY inside `.worktrees/<slug>`. Never read peer's `.worktrees/<other>/`.
3. Same `EXECUTION_DIR`-into-worktree rule as `gitops`: all commands prefixed
   `cd <worktree> &&`.
4. Prove with `acceptance` command in the worktree. Paste output into `## Verdict`.
5. Return = `python3 scripts/pair/done.py <slug> "<verdict>"` (moves
pair/claims/<slug>.md -> pair/done/<slug>.md) + `status: done` +
log + STATE. Or return to queue with `rounds_left - 1` + reason if blocked.

## 6. Poll rule (liveness)

On session start + every ~5 turns or 10 min: list `pair/queue/`, claim oldest
runnable `pending`. If none, continue own work. File writes never wake anyone —
polling + explicit notify (`python3 scripts/pair/poke.py <peer> "<prompt>"`
launches DETACHED; reporter polls `pair/pokes/<peer>-<ts>.log`) is the transport.
Foreground runs exceed the 60s exec cap, so detached+poll is mandatory, not optional.

Notify matrix (both directions verified, same socket both agents hold):

| From | To hermes | To dsh |
|---|---|---|
| hermes | — (own poll) | `pai_docker_ops(action="exec", service="dsh", cmd="...")` or `python3 scripts/pair/poke.py dsh "<prompt>"` over the mounted socket |
| dsh | `docker exec hermes /opt/hermes/.venv/bin/hermes-agent -q "<prompt>"` or `python3 scripts/pair/poke.py hermes "<prompt>"` | — (own poll) |
| human/host | `make pair-poke p=hermes [m="..."]` | `make pair-poke p=dsh [m="..."]` |

Unknown future peer ids: `poke.py` logs without exec — their next poll delivers.

## 7. Human gates (non-bypassable)

1. Plan approval — task enters `queue/` only after human approves scope.
2. Interim review — human may comment on `claims/<slug>.md`; owner must address.
3. Merge — `done/` ≠ merged. Merge into integration branch only on explicit
   human confirmation, tests-first per `gitops` finishing flow.
4. No raw secrets in any `pair/` file (env refs only). Helpers grep before accept.

## 8. Rounds + escalation

`rounds_left` starts at 2, decrements on every queue-return. At 0 → move to
`done/` with `verdict: blocked — escalated`, stop, notify human.
3-strike protocol (planning skill) applies to errors inside a claim.
