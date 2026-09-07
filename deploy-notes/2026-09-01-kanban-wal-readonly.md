# 2026-09-01 — kanban.db-wal "read-only" warning

## Symptom

Hermes dashboard log (recurring):

```
WARNING hermes_dashboard_plugin_kanban: Kanban event stream error:
kanban.db (kanban.db) is not writable:
file /opt/hermes/data/kanban/boards/terminal-portfolio/kanban.db-wal
is read-only for this user.
```

The kanban worker still operates (the WAL fallback lets reads continue), but
the WebSocket event stream keeps retrying and re-emitting the warning on
every reconnect.

## Root cause

`hermes/entrypoint.sh` (the pai-stack patch) does `chown -R` of
`/opt/hermes/data` to `${HERMES_UID}:${HERMES_GID}` but never adjusts the
process umask. SQLite creates `kanban.db-wal` and `kanban.db-shm` using the
inherited umask (`022`), so each new WAL/SHM file is born with mode `0644`.

The kanban dashboard plugin (`hermes_cli.kanban_db`) opens the DB in WAL
mode, then on a later connection finds the WAL it just created is no longer
writable (different uid from the worker dispatcher, different container
layer, or simply a chown that reset group bits) → `EACCES` → warning.

The same hazard exists for `state.db`, `response_store.db`, and
`projects.db`, but they happened to be opened only by the gateway so far.

## Fix

In `hermes/entrypoint.sh`:

1. `umask 000` after the existing `chown -R`, so SQLite (and any other
   library) creates new files at `0666` from the start.
2. A one-shot `find … -exec chmod a+rw {} +` over all `*.db*` files under
   `/opt/hermes/data` to back-fix any existing WAL/SHM that was created
   with the old umask. This is idempotent and a no-op when permissions are
   already correct.

## Why not just chmod the running container

The dashboard plugin holds the DB open and recreates the WAL every time
SQLite re-tries. `chmod u+rw` from inside the container is silently reverted
the moment SQLite opens the file again (`chmod` reports
`mode of 'kanban.db-wal' retained as 0644`). The only way to make the fix
stick is at process start, before any DB is opened.

## Verified locally

```bash
$ stat -c '%a %n' /opt/hermes/data/kanban/boards/terminal-portfolio/kanban.db*
666 /opt/hermes/data/kanban/boards/terminal-portfolio/kanban.db
666 /opt/hermes/data/kanban/boards/terminal-portfolio/kanban.db-shm
666 /opt/hermes/data/kanban/boards/terminal-portfolio/kanban.db-wal
666 /opt/hermes/data/kanban/boards/terminal-portfolio/kanban.db.dispatch.lock
666 /opt/hermes/data/kanban/boards/terminal-portfolio/kanban.db.init.lock
```

(applied by running the patched snippet directly inside the running
container — will also re-apply automatically on next `deploy.sh`.)

## Deploy

Sync from the MacBook after Syncthing catches the change, then:

```bash
cd ~/Personal/github.com/ayedaemon/pai-stack
./deploy.sh        # rebuilds the hermes image with the new entrypoint
```

After redeploy the warning stops within one watchdog tick (~30 s). No data
migration required — the `-wal` file is preserved across the restart.