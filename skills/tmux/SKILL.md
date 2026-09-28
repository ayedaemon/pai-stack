---
name: tmux
description: "Remote control tmux sessions for interactive CLIs (python, gdb, etc.) by sending keystrokes and scraping pane output. Session is always named hermes-<execution_dir-basename> on the hermes socket."
---

# tmux Skill

Use tmux as a programmable terminal multiplexer for interactive work. Works on Linux and macOS with stock tmux; avoid custom config by using a private socket.

## Session naming (mandatory)

- Every Hermes chat already declares `EXECUTION_DIR = /opt/data/workspace/<project>` on Turn 1 (see `agents` skill). Derive the tmux session from it — never invent a free-form name:
  ```bash
  PROJECT=$(basename "$EXECUTION_DIR" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g; s/-\+/-/g; s/^-//; s/-$//')
  SESSION="hermes-$PROJECT"   # e.g. EXECUTION_DIR=/opt/data/workspace/pai-stack -> hermes-pai-stack
  ```
- One session per `EXECUTION_DIR`. Run different tools in different windows/panes of that same session (`new-window`, `split-window`), not in new sessions.
- Only append a `-<suffix>` (e.g. `hermes-pai-stack-debug`) when you genuinely need a second concurrent session for the same project; state why in your reply.
- If `EXECUTION_DIR` is the workspace root itself, use `SESSION="hermes-workspace"`.

## Quickstart (isolated hermes socket)

```bash
PROJECT=$(basename "$EXECUTION_DIR" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g; s/-\+/-/g; s/^-//; s/-$//')
SESSION="hermes-$PROJECT"                              # e.g. hermes-pai-stack
SOCKET_DIR=${TMPDIR:-/tmp}/hermes-tmux-sockets         # well-known dir for all hermes sockets
mkdir -p "$SOCKET_DIR"
SOCKET="$SOCKET_DIR/hermes.sock"                       # keep hermes sessions separate from your personal tmux
tmux -S "$SOCKET" new -d -s "$SESSION" -n shell
tmux -S "$SOCKET" send-keys -t "$SESSION":0.0 -- 'python3 -q' Enter
tmux -S "$SOCKET" capture-pane -p -J -t "$SESSION":0.0 -S -200  # watch output
tmux -S "$SOCKET" kill-session -t "$SESSION"                   # clean up
```

After starting a session ALWAYS tell the user how to monitor the session by giving them a command to copy paste (substitute the real `$SESSION` value):

```
To monitor this session yourself:
  tmux -S "${TMPDIR:-/tmp}/hermes-tmux-sockets/hermes.sock" attach -t hermes-pai-stack

Or to capture the output once:
  tmux -S "${TMPDIR:-/tmp}/hermes-tmux-sockets/hermes.sock" capture-pane -p -J -t hermes-pai-stack:0.0 -S -200
```

This must ALWAYS be printed right after a session was started and once again at the end of the tool loop.  But the earlier you send it, the happier the user will be.

## Socket convention (hermes socket)

- Agents MUST place tmux sockets under `HERMES_TMUX_SOCKET_DIR` (defaults to `${TMPDIR:-/tmp}/hermes-tmux-sockets`) and use `tmux -S "$SOCKET"` so we can enumerate/clean them. Create the dir first: `mkdir -p "$HERMES_TMUX_SOCKET_DIR"`.
- Default socket path to use unless you must isolate further: `SOCKET="$HERMES_TMUX_SOCKET_DIR/hermes.sock"`.
- Never use a `claude` socket path (`claude-tmux-sockets/`, `claude.sock`) — this stack is Hermes-only; saying "claude socket" confuses users. Always say "hermes socket" in plans and replies.

## Targeting panes and naming

- Target format: `{session}:{window}.{pane}`, defaults to `:0.0` if omitted. Session is always `hermes-<project-basename>` (see above); keep window names short (e.g. `shell`, `py`, `gdb`).
- Use `-S "$SOCKET"` consistently to stay on the private hermes socket path. If you need user config, drop `-f /dev/null`; otherwise `-f /dev/null` gives a clean config.
- Inspect: `tmux -S "$SOCKET" list-sessions`, `tmux -S "$SOCKET" list-panes -a`.

## Finding sessions

- List sessions on your active hermes socket with metadata: `./scripts/find-sessions.sh -S "$SOCKET"`; add `-q hermes-<project>` to filter to this chat's project.
- Scan all sockets under the shared directory: `./scripts/find-sessions.sh --all` (uses `HERMES_TMUX_SOCKET_DIR` or `${TMPDIR:-/tmp}/hermes-tmux-sockets`).

## Sending input safely

- Prefer literal sends to avoid shell splitting: `tmux -S "$SOCKET" send-keys -t target -l -- "$cmd"`
- When composing inline commands, use single quotes or ANSI C quoting to avoid expansion: `tmux ... send-keys -t target -- $'python3 -m http.server 8000'`.
- To send control keys: `tmux ... send-keys -t target C-c`, `C-d`, `C-z`, `Escape`, etc.

## Watching output

- Capture recent history (joined lines to avoid wrapping artifacts): `tmux -S "$SOCKET" capture-pane -p -J -t target -S -200`.
- For continuous monitoring, poll with the helper script (below) instead of `tmux wait-for` (which does not watch pane output).
- You can also temporarily attach to observe: `tmux -S "$SOCKET" attach -t "$SESSION"`; detach with `Ctrl+b d`.
- When giving instructions to a user, **explicitly print a copy/paste monitor command** alongside the action don't assume they remembered the command.

## Spawning Processes

Some special rules for processes:

- when asked to debug, use lldb by default
- when starting a python interactive shell, always set the `PYTHON_BASIC_REPL=1` environment variable. This is very important as the non-basic console interferes with your send-keys.

## Synchronizing / waiting for prompts

- Use timed polling to avoid races with interactive tools. Example: wait for a Python prompt before sending code:
  ```bash
  ./scripts/wait-for-text.sh -t "$SESSION":0.0 -p '^>>>' -T 15 -l 4000
  ```
- For long-running commands, poll for completion text (`"Type quit to exit"`, `"Program exited"`, etc.) before proceeding.

## Interactive tool recipes

- **Python REPL**: `tmux ... send-keys -- 'python3 -q' Enter`; wait for `^>>>`; send code with `-l`; interrupt with `C-c`. Always with `PYTHON_BASIC_REPL`.
- **gdb**: `tmux ... send-keys -- 'gdb --quiet ./a.out' Enter`; disable paging `tmux ... send-keys -- 'set pagination off' Enter`; break with `C-c`; issue `bt`, `info locals`, etc.; exit via `quit` then confirm `y`.
- **Other TTY apps** (ipdb, psql, mysql, node, bash): same pattern—start the program, poll for its prompt, then send literal text and Enter.

## Cleanup

- Kill a session when done: `tmux -S "$SOCKET" kill-session -t "$SESSION"`.
- Kill all sessions on a socket: `tmux -S "$SOCKET" list-sessions -F '#{session_name}' | xargs -r -n1 tmux -S "$SOCKET" kill-session -t`.
- Remove everything on the private socket: `tmux -S "$SOCKET" kill-server`.

## Helper: wait-for-text.sh

`./scripts/wait-for-text.sh` polls a pane for a regex (or fixed string) with a timeout. Works on Linux/macOS with bash + tmux + grep.

```bash
./scripts/wait-for-text.sh -t session:0.0 -p 'pattern' [-F] [-T 20] [-i 0.5] [-l 2000]
```

- `-t`/`--target` pane target (required)
- `-p`/`--pattern` regex to match (required); add `-F` for fixed string
- `-T` timeout seconds (integer, default 15)
- `-i` poll interval seconds (default 0.5)
- `-l` history lines to search from the pane (integer, default 1000)
- Exits 0 on first match, 1 on timeout. On failure prints the last captured text to stderr to aid debugging.
