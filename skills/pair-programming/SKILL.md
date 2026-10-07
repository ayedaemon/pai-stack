---
name: pair-programming
description: Peer-to-peer shared-blackboard collaboration via pair/ queue + atomic mv claim + worktree isolation. Load on session start when pair/ exists, or when user mentions pair/blackboard/queue/claim.
---

# Pair Programming — Shared Blackboard

> Peer discipline. Single queue, no lead. Files are the API (`pair/AGENT_CONTRACT.md`
> is normative — this skill is the workflow). Shared pai-stack glue (EXECUTION_DIR,
> propose-before-write, citations) is canonical in the `agents` skill.

## When to use

* IF `pair/` exists in the repo root, THEN load this skill at session start.
* IF user mentions pair, blackboard, queue, or claim, THEN load it.

## Paths (canonical naming — both agents identical)

Container-absolute only: `/opt/data/workspace/<...>` (see `path.py --map`).
Normalize every pasted/human path on intake: `python3 scripts/pair/path.py <path>`.
Host forms in a task file = malformed, return to queue. (Contract §2.)

## Poll rule (every session touching pair — hermes AND dsh)

1. `python3 scripts/pair/status.py` (or `ls pair/queue/`) — claim oldest runnable
   `status: pending` via `python3 scripts/pair/claim.py <slug> <my-id>`
   (`os.rename` = lock; gone = someone else got it, pick another).
2. If none claimable, continue other work. Re-poll every ~5 turns / 10 min.
3. Never claim `_example.md`. Never hold two claims at once — one claim, finish or return it, then poll again. Never touch `pair/claims/<other-owner>/*` except review comments.

## Work rule

1. Contract §5: own worktree `.worktrees/<slug>` on `pair/<slug>`, clean tree only.
   Load `gitops` skill for worktree + finishing flow; load `planning` skill for
   3+ step tasks (findings after every 2 reads, `path:line` anchors).
2. Work ONLY in your worktree. Never read peer worktrees.
3. `terrain` first when running: `pai_terrain_ops(action="projects")`, index if
   missing, then `search` before reading (or `grep` + targeted reads if down).
4. Prove with the task's `acceptance` command in the worktree; paste output into `## Verdict`.

## Return rule

* Done: `python3 scripts/pair/done.py <slug> "<verdict one-liner>"` (moves claims→done).
* Blocked: decrement `rounds_left`, move back to `queue/` with reason; at 0 →
  `done/` as `blocked — escalated`, notify human.
* Update `pair/STATE.md` + append `pair/log.md` on every transition.
* Merge NEVER follows done automatically — human confirmation + tests-first
  (`gitops` §Finishing) required. No raw secrets in `pair/` files ever.

## Poke — wake the peer (files don't notify; both agents do this)

After queueing a task for the peer: `python3 scripts/pair/poke.py <peer> "<prompt>"`
(detached launch; poll `pair/pokes/<peer>-<ts>.log` — poke prints the exact cat
command). Record lands in `pair/log.md`. No poke → peer finds it on next poll;
poke = sooner. Never foreground-wait on a peer: the 60s exec cap kills the client.

* From hermes: `pai_docker_ops(action="exec", service="dsh", cmd="...")` also works;
  `poke.py dsh` wraps the same `docker exec dsh /opt/dsh/bin/dsh --profile headless`
  one-shot over the mounted socket (60s cap — poke returns fast, peer works async).
* From dsh: `docker exec hermes /opt/hermes/.venv/bin/hermes-agent -q "<prompt>"`
  directly, or `poke.py hermes` (same thing wrapped).
* Unknown future peers: `poke.py` logs without exec — their poll delivers.
