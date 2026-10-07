---
name: pair-programming
description: Peer-to-peer shared-blackboard collaboration via .pair/ queue + atomic mv claim + worktree isolation. Load on session start when .pair/ (or legacy pair/) exists, or when user mentions pair/blackboard/queue/claim.
---

# Pair Programming — Shared Blackboard

> Peer discipline. Single queue, no lead. Files are the API (`.pair/AGENT_CONTRACT.md`
> is normative — this skill is the workflow). Shared pai-stack glue (EXECUTION_DIR,
> propose-before-write, citations) is canonical in the `agents` skill.

## When to use

* IF `.pair/` (or legacy `pair/`) exists in the project root, THEN load this skill at session start.
* IF user mentions pair, blackboard, queue, or claim, THEN load it.
* Helpers resolve the board via `scripts/pair/pairlib.py` (`--pair-dir` > `PAIR_DIR` > nearest `.pair/` up from cwd). The board is hidden + untracked; the lock is `os.rename` on the shared volume, not git.

## Paths (canonical naming — both agents identical)

Container-absolute only: `/opt/data/workspace/<...>` (see `path.py --map`).
Normalize every pasted/human path on intake: `python3 scripts/pair/path.py <path>`.
Host forms in a task file = malformed, return to queue. (Contract §2.)

## Setup rule (first session in a project — either agent does it once)

The board lives at `<project>/.pair/` (hidden + untracked by design; the lock
is `os.rename` on the shared volume, not git):

1. If no `.pair/queue/` exists: scaffold with `python3 scripts/pair/init.py <project>`
   (or `PAIR_DIR=<project>/.pair python3 scripts/pair/init.py --here`).
2. Ensure `.pair/` is gitignored: if `<project>/.gitignore` exists and has no
   `.pair/` entry, append `.pair/` (+ `.pair/telegram-groups.local.md`). If the
   project has no `.gitignore` yet, create one containing `.pair/`. Never commit
   the board — `git status` must not show `.pair/` as untracked noise.
3. Pin the project: fill `.pair/telegram-groups.md` (`EXECUTION_DIR` container +
   host paths, `group_chat_id`, `human_ids`, member bots); real IDs per
   deployment go in `.pair/telegram-groups.local.md` (gitignored) + `BRIDGE_*`
   env. To capture IDs: add both bots to the group, post one `@`-tagged
   message, then read the chat id back (bridge `--discover`, or the bots'
   binding/state files) and record it plus any forum `topic_id`s as scope
   rows. Title-tag routing (§Group-message routing) keys off this table —
   no row, no action.

## Poll rule (every session touching pair — hermes AND dsh)

1. `python3 scripts/pair/status.py` (or `ls .pair/queue/`) — claim oldest runnable
   `status: pending` via `python3 scripts/pair/claim.py <slug> <my-id>`
   (`os.rename` = lock; gone = someone else got it, pick another).
2. If none claimable, continue other work. Re-poll every ~5 turns / 10 min.
3. Never claim `_example.md`. Never hold two claims at once — one claim, finish or return it, then poll again. Never touch `.pair/claims/<other-owner>/*` except review comments.

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
* Update `.pair/STATE.md` + append `.pair/log.md` on every transition.
* Merge NEVER follows done automatically — human confirmation + tests-first
  (`gitops` §Finishing) required. No raw secrets in `.pair/` files ever.

## Notify rule — Telegram first, files always (contract §9)

Telegram is the primary peer/human channel; `.pair/` files are the record.
Both agents must be in the project's Telegram group (mapping in
`.pair/telegram-groups.md`) AND poll `.pair/queue/` every ~5 turns — either
path alone delivers, together they converge fast:

* On every transition (`claim`/`done`/return/review-comment): first write the
  file event (`claim.py`/`done.py`/append + `log.md`), then post one status line
  to the group tagging the peer + human, e.g. `@dsh claimed ` + backtick-slug +
  backtick + ` — working in ...` or `REVIEW ` + backtick-slug + backtick +
  `: <verdict> — merge? Y/N`. One line, no threads.
* Mention discipline: only human `@` creates work (`@hermes <task> |
  acceptance: <cmd>`). Agent `@peer` coordinates (bot-to-bot mode lets agents
  see each other's addressed messages now — but file-truth still rules, and
  agent text never creates tasks, only review comments). Loop discipline:
  never auto-reply to a peer's reply more than twice per slug without a human
  message in between; then escalate.
  No `@` → silence. `@both` → hermes answers, dsh stands by unless the queue
  file names him.
* Never paste host paths, secrets, or merge without human Y/N. If Telegram is
  unreachable, keep working the files — the poll rule covers liveness and the
  bridge backfills announcements when it returns.

## Group-message routing — title tag + chat/topic mapping

Act on a group message only when all three resolve; otherwise stay silent
(silence is the default, not an error):

1. **Title tag (first line decides who):** leading `@hermes` → hermes acts;
   `@dsh` → dsh acts; `@both` → hermes acts, dsh stands by unless named by a
   queue file. No leading tag → silence (group chatter is not work). The tag
   may carry a slug (`@dsh <slug> ...`) to bind the message to a claim.
2. **Chat mapping (decides where):** look up `msg.chat.id` in the
   *project-local* `<EXECUTION_DIR>/.pair/telegram-groups.local.md`
   (real IDs; template in `telegram-groups.md`). Match → lock
   `EXECUTION_DIR` to that row for the whole turn; never touch another
   project. No match → silence + one hint line pointing at the mapping file.
   One group = one `EXECUTION_DIR`; a chat listed under two projects is
   misconfigured — act for neither, tell the human.
3. **Topic/thread (decides scope):** `message_thread_id` present →
   treat as subscope: replies stay in-thread, and a new topic means a new
   session/slug, never a hijack of another topic's work. Absent → general.
4. **Sender gate:** human senders via project allowlists; bot senders only
   when explicitly listed AND bot-to-bot mode is on (both our bots have it).
   Cap bot-triggered chains per §Notify loop discipline.
5. **File mirror:** any work agreed in chat lands in `.pair/queue|claims`
   within the same turn — chat is view, files are truth (contract §9).

## Poke — fallback wake (docker-socket environments only)

Where both agents hold the docker socket, `poke.py` is a faster doorbell than
polling: `python3 scripts/pair/poke.py <peer> "<prompt>"` (detached launch;
poll `.pair/pokes/<peer>-<ts>.log` — poke prints the exact cat command). Record
lands in `.pair/log.md`. Never foreground-wait on a peer: the 60s exec cap
kills the client. On hosts without pai-stack/docker (plain deploy), skip poke
entirely — Telegram + poll is the whole transport (contract §10).
