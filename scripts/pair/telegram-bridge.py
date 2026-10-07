#!/usr/bin/env python3
"""pair telegram-bridge v0 — @mention UX without docker exec or HTTP wake.

Two directions, both file-grounded (Telegram is view, .pair/ files are truth):

  inbound  (human → file): long-poll getUpdates with the BRIDGE bot token,
             double-allowlist (chat + sender), parse `@hermes|@dsh ...`,
             draft .pair/queue/<slug>.md or append review comments.
  outbound (file → human): watch .pair/queue|claims|done mtimes, post one
             status line per new claim/done to the group via sendMessage.

Why a 3rd bot token: Telegram allows exactly one getUpdates consumer per
token. Reusing the hermes/dsh tokens 409-conflicts their own pollers.
Create via @BotFather, keep in BRIDGE_TELEGRAM_BOT_TOKEN only.

Why file-only (no HTTP wake): agents already poll .pair/queue every ~5 turns
/ 10 min per the pair skill, so delegation works with zero creds. v1 may add
HTTP wake; v0 must not need API_SERVER_KEY or DSH admin sessions.

Usage:
  BRIDGE_TELEGRAM_BOT_TOKEN=<tok> python3 scripts/pair/telegram-bridge.py --discover
  BRIDGE_TELEGRAM_BOT_TOKEN=<tok> python3 scripts/pair/telegram-bridge.py --check
  BRIDGE_TELEGRAM_BOT_TOKEN=<tok> python3 scripts/pair/telegram-bridge.py --once
  BRIDGE_TELEGRAM_BOT_TOKEN=<tok> python3 scripts/pair/telegram-bridge.py --daemon [--interval 15]

Env:
  BRIDGE_TELEGRAM_BOT_TOKEN  own bot token (required for --discover/--once/--daemon)
  BRIDGE_GROUP_CHAT_ID       group chat id, e.g. -1001234567890 (required to post)
  BRIDGE_ALLOWED_CHATS       csv extra chat ids (optional, default = GROUP_CHAT_ID)
  BRIDGE_ALLOWED_USERS       csv numeric sender ids: DM+group access
  BRIDGE_GROUP_ALLOWED_USERS csv numeric sender ids: group-only access
Stdlib only.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Portable roots: --pair-dir > PAIR_DIR env > walk up from cwd for .pair/
# (legacy pair/ fallback) > this script's own repo (backwards compat).
# EXECUTION_DIR is derived per project (parent of .pair/ mapped to the
# container prefix), never hardcoded — so a checkout without pai-stack
# (e.g. ytune alone on another host) works unchanged.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pairlib import find_pair as resolve_pair  # noqa: E402


def container_execution_dir(pair_dir: Path) -> str:
    """Project root (parent of pair/) expressed in container form.

    Inside pai-stack containers the workspace mounts at
    /opt/data/workspace; on a bare host checkout we map via
    $WORKSPACE_DIR (or ~/Personal) the same way scripts/pair/path.py does.
    """
    prefix = "/opt/data/workspace"
    project_root = pair_dir.parent.resolve()
    ws = os.environ.get("WORKSPACE_DIR") or os.path.join(os.path.expanduser("~"), "Personal")
    ws = ws.rstrip("/")
    try:
        rel = str(project_root)
        if rel == ws or rel.startswith(ws + "/"):
            return prefix + rel[len(ws):]
    except Exception:
        pass
    if "/Personal/" in str(project_root):
        return prefix + "/" + str(project_root).split("/Personal/", 1)[1]
    return str(project_root)


PAIR = resolve_pair()
POKES = PAIR / "pokes"
STATE_PATH = POKES / "bridge-state.json"
GROUPS_DOC = PAIR / "telegram-groups.md"
EXECUTION_DIR = container_execution_dir(PAIR)

API_BASE = "https://api.telegram.org"
CONTAINER_PREFIX = "/opt/data/workspace"

SECRET = re.compile(
    r"sk-[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{8,}"
    r"|xox[bpas]-[A-Za-z0-9-]{8,}|Bearer [A-Za-z0-9._\-]{8,}"
)
ACCEPT_OK = re.compile(
    r"^(pytest|npm test|go test|make test|ruff|tsc|cargo test|test -f|grep -q|echo|python3 scripts/pair/status\.py)\b"
)
ACCEPT_DENY = re.compile(r"\b(docker|push|rm\s+-rf|curl|wget|ssh|mkfs|dd\s)\b")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{2,60}-\d{4}-\d{2}-\d{2}$")


def fail(msg: str) -> int:
    print(f"bridge: {msg}", file=sys.stderr)
    return 1


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"offset": 0, "posted": []}


def save_state(s: dict) -> None:
    POKES.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
    tmp.rename(STATE_PATH)


def csv_env(name: str) -> set:
    return {p.strip() for p in os.environ.get(name, "").split(",") if p.strip()}


def api(token: str, method: str, params: dict | None = None):
    data = json.dumps(params or {}).encode() if params is not None else None
    req = urllib.request.Request(
        f"{API_BASE}/bot{token}/{method}",
        data=data,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        body = json.loads(r.read().decode())
    if not body.get("ok"):
        raise RuntimeError(f"telegram {method}: {body.get('description')}")
    return body.get("result")


def send_text(token: str, chat_id: str, text: str) -> None:
    # Telegram cap ~4096 chars; keep status lines tiny by construction.
    api(token, "sendMessage", {"chat_id": chat_id, "text": text[:3500]})


def ts_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def append_log(actor: str, event: str, slug: str, note: str) -> None:
    with (PAIR / "log.md").open("a", encoding="utf-8") as f:
        f.write(f"{ts_now()} | {actor} | {event} | {slug} | {note}\n")


def slug_from(text: str, chat_id: str) -> str:
    m = re.search(r"([a-z0-9][a-z0-9-]{2,60})-\d{4}-\d{2}-\d{2}", text)
    if m:
        return m.group(0)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    digest = abs(hash(f"{chat_id}|{text}")) % 1296
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "task"
    return f"{base}-{date}-{digest:04d}"[:80]


def draft_queue(slug: str, task: str, acceptance: str, sender: str) -> Path:
    if not SLUG.match(slug):
        raise ValueError(f"bad slug {slug!r} (want kebab-YYYY-MM-DD)")
    if SECRET.search(task + acceptance):
        raise ValueError("refused: possible raw secret (use env refs)")
    if not ACCEPT_OK.search(acceptance.strip()):
        raise ValueError("refused: acceptance not in allowlist (pytest|npm test|...|test -f|grep -q|...)")
    if ACCEPT_DENY.search(acceptance):
        raise ValueError("refused: acceptance contains denied command")
    front = (
        f"---\nslug: {slug}\nstatus: pending\nowner: unclaimed\n"
        f"execution_dir: {EXECUTION_DIR}\nbranch: pair/{slug}\n"
        f"worktree: .worktrees/{slug}\nacceptance: {acceptance.strip()}\n"
        f"rounds_left: 2\ncreated_by: human\n---\n"
    )
    body = front + f"\n## Task\n\n{task.strip()}\n\n## Context\n\nVia Telegram bridge from {sender}. File truth wins; confirm scope before claiming.\n\n## Verdict\n\n(leave empty until done)\n"
    dest = PAIR / "queue" / f"{slug}.md"
    if dest.exists():
        raise ValueError(f"already exists: pair/queue/{slug}.md")
    dest.write_text(body, encoding="utf-8")
    append_log("bridge", "queue", slug, f"draft from telegram sender {sender}")
    return dest


def handle_human_text(text: str, sender: str, chat_id: str) -> str | None:
    """Returns reply text for the group, or None for silence."""
    low = text.lower()
    has_hermes = "@hermes" in low or "@pair_hermes" in low
    has_dsh = "@dsh" in low or "@pair_dsh" in low
    if not (has_hermes or has_dsh or text.startswith("/approve")):
        return None  # single-speaker rule: no @ → silence
    if text.startswith("/approve"):
        parts = text.split()
        if len(parts) != 2:
            return "usage: /approve <slug-YYYY-MM-DD>"
        append_log("human", "approve", parts[1], "telegram confirm")
        return f"approved `{parts[1]}` — agents may claim it."
    if "review" in low:
        m = re.search(r"([a-z0-9][a-z0-9-]{2,60}-\d{4}-\d{2}-\d{2})", text)
        if not m:
            return "which slug? `review <slug-YYYY-MM-DD> ...`"
        slug = m.group(1)
        target = PAIR / "claims" / f"{slug}.md"
        if not target.is_file():
            return f"`{slug}` not in claims/ — nothing to review."
        with target.open("a", encoding="utf-8") as f:
            f.write(f"\n## Review comment (human, {ts_now()})\n{text.strip()}\n")
        append_log("bridge", "review-comment", slug, f"from telegram sender {sender}")
        return f"noted on `.pair/claims/{slug}.md` — owner must address."
    # New work: `@hermes|@dsh <task> | acceptance: <cmd>`
    if "| acceptance:" in low:
        task_part, _, acc_part = text.partition("| acceptance:")
        task = re.sub(r"@\w+", "", task_part).strip()
        slug = slug_from(task + acc_part, chat_id)
        try:
            draft_queue(slug, task or text, acc_part.strip(), sender)
        except ValueError as e:
            return f"draft refused: {e}"
        if has_hermes and has_dsh:
            return f"drafted `{slug}` — @both seen, hermes leads, dsh stands by unless queue names him. Confirm with `/approve {slug}`."
        who = "@hermes" if has_hermes else "@dsh"
        return f"drafted `{slug}` for {who} — confirm with `/approve {slug}`."
    return "format: `@hermes <task> | acceptance: <cmd>` — acceptance allowlist: pytest|npm test|test -f|grep -q|..."


def inbound_once(token: str, allowed_chats: set, allowed_senders: set) -> int:
    st = load_state()
    updates = api(token, "getUpdates", {"timeout": 10, "offset": st.get("offset", 0) + 1,
                                        "allowed_updates": ["message", "edited_message"]})
    n = 0
    for u in updates or []:
        st["offset"] = max(st.get("offset", 0), u.get("update_id", 0))
        msg = u.get("message") or u.get("edited_message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        sender = str((msg.get("from") or {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if not chat_id or not text:
            continue
        if chat_id not in allowed_chats or sender not in allowed_senders:
            continue  # silent drop: zero token burn beyond this process
        if "via_bot" in msg or (msg.get("from") or {}).get("is_bot"):
            continue  # bots never relay bot messages; files are the relay
        reply = handle_human_text(text, sender, chat_id)
        if reply:
            try:
                send_text(token, chat_id, reply)
            except Exception as e:
                print(f"bridge: send failed: {e}", file=sys.stderr)
        n += 1
    save_state(st)
    return n


def pair_snapshot() -> dict:
    snap = {}
    for rel in ("queue", "claims", "done"):
        d = PAIR / rel
        try:
            snap[rel] = sorted(p.name for p in d.iterdir()
                               if p.suffix == ".md" and not p.name.startswith("."))
        except FileNotFoundError:
            snap[rel] = []
    return snap


def outbound_once(token: str, chat_id: str) -> int:
    st = load_state()
    posted = set(st.get("posted", []))
    snap = pair_snapshot()
    fresh = []
    for rel in ("queue", "claims", "done"):
        for name in snap[rel]:
            key = f"{rel}/{name}"
            if key not in posted:
                fresh.append(key)
    # Cap burst so a backlog never floods the group.
    for key in sorted(fresh)[:5]:
        rel, name = key.split("/", 1)
        slug = name[:-3]
        if rel == "queue":
            msg = f"queued `{slug}` — agents may claim via `claim.py {slug} <owner>`."
        elif rel == "claims":
            msg = f"claimed `{slug}` — owner working in `.worktrees/{slug}`."
        else:
            msg = f"REVIEW `{slug}` — see `.pair/done/{slug}.md` verdict. Human merge? Y/N"
        try:
            send_text(token, chat_id, msg)
        except Exception as e:
            print(f"bridge: send failed: {e}", file=sys.stderr)
            break
        posted.add(key)
        append_log("bridge", f"announce-{rel}", slug, f"telegram post to {chat_id}")
    st["posted"] = sorted(posted)[-500:]
    save_state(st)
    return len(fresh)


def cmd_discover(token: str) -> int:
    updates = api(token, "getUpdates", {"timeout": 10, "offset": -10,
                                        "allowed_updates": ["message", "my_chat_member"]})
    print("recent chats (post one message in the group, re-run):")
    seen = set()
    for u in updates or []:
        for holder in (u.get("message"), u.get("edited_message"), u.get("my_chat_member")):
            if not holder:
                continue
            c = holder.get("chat") or {}
            cid = str(c.get("id", ""))
            if cid and cid not in seen:
                seen.add(cid)
                print(f"  chat_id={cid} type={c.get('type')} title={c.get('title')}")
    print("fill BRIDGE_GROUP_CHAT_ID + .pair/telegram-groups.md with the -100... id")
    return 0


def cmd_check() -> int:
    problems = []
    contract = PAIR / "AGENT_CONTRACT.md"
    if not contract.is_file():
        # Portable projects keep the contract in pai-stack; a project-local
        # .pair/ without it is fine (queue/claims/done are the interface).
        print(f"note: {PAIR}/AGENT_CONTRACT.md not present (ok — contract lives in pai-stack)")
    print(f"pair: {PAIR}  execution_dir: {EXECUTION_DIR}")
    if not GROUPS_DOC.is_file():
        problems.append(".pair/telegram-groups.md missing")
    else:
        txt = GROUPS_DOC.read_text(encoding="utf-8")
        if "<fill" in txt:
            print("note: .pair/telegram-groups.md still has <fill> placeholders (ok until group created)")
    for rel in ("queue", "claims", "done"):
        if not (PAIR / rel).is_dir():
            problems.append(f".pair/{rel}/ missing")
    print(f"snapshot: {pair_snapshot()}")
    if problems:
        return fail("; ".join(problems))
    print("check ok: mapping pinned, .pair/ dirs present, stdlib only")
    return 0


def main(argv: list[str]) -> int:
    global PAIR, POKES, STATE_PATH, GROUPS_DOC, EXECUTION_DIR
    pair_arg = None
    for i, a in enumerate(argv):
        if a == "--pair-dir" and i + 1 < len(argv):
            pair_arg = argv[i + 1]
    if pair_arg or os.environ.get("PAIR_DIR"):
        PAIR = resolve_pair(pair_arg)
        POKES = PAIR / "pokes"
        STATE_PATH = POKES / "bridge-state.json"
        GROUPS_DOC = PAIR / "telegram-groups.md"
        EXECUTION_DIR = container_execution_dir(PAIR)
    if "--discover" in argv:
        token = os.environ.get("BRIDGE_TELEGRAM_BOT_TOKEN", "")
        if not token:
            return fail("set BRIDGE_TELEGRAM_BOT_TOKEN first")
        return cmd_discover(token)
    if "--check" in argv or len(argv) == 1:
        return cmd_check()
    token = os.environ.get("BRIDGE_TELEGRAM_BOT_TOKEN", "")
    group = os.environ.get("BRIDGE_GROUP_CHAT_ID", "")
    allowed_chats = csv_env("BRIDGE_ALLOWED_CHATS") | ({group} if group else set())
    allowed_senders = csv_env("BRIDGE_ALLOWED_USERS") | csv_env("BRIDGE_GROUP_ALLOWED_USERS")
    # Fall back to the existing hermes-group env so operators don't maintain two lists.
    allowed_chats |= csv_env("HERMES_TELEGRAM_GROUP_ALLOWED_CHATS")
    allowed_senders |= csv_env("HERMES_TELEGRAM_ALLOWED_USERS") | csv_env("HERMES_TELEGRAM_GROUP_ALLOWED_USERS")
    if "--once" in argv:
        if not token or not group:
            return fail("need BRIDGE_TELEGRAM_BOT_TOKEN + BRIDGE_GROUP_CHAT_ID")
        if not allowed_senders:
            return fail("refusing open group: set BRIDGE_ALLOWED_USERS (deny-by-default)")
        ni = inbound_once(token, allowed_chats, allowed_senders)
        no = outbound_once(token, group)
        print(f"once: inbound={ni} outbound_pending={no}")
        return 0
    if "--daemon" in argv:
        if not token or not group:
            return fail("need BRIDGE_TELEGRAM_BOT_TOKEN + BRIDGE_GROUP_CHAT_ID")
        if not allowed_senders:
            return fail("refusing open group: set BRIDGE_ALLOWED_USERS (deny-by-default)")
        interval = 15
        for i, a in enumerate(argv):
            if a == "--interval" and i + 1 < len(argv):
                interval = max(5, int(argv[i + 1]))
        print(f"bridge daemon: group={group} interval={interval}s (Ctrl-C to stop)")
        while True:
            try:
                inbound_once(token, allowed_chats, allowed_senders)
                outbound_once(token, group)
            except Exception as e:
                print(f"bridge: cycle failed: {e}", file=sys.stderr)
            time.sleep(interval)
    print(__doc__.strip().splitlines()[0], file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
