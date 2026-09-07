# kanban.default_model — deploy notes

## What this does

Adds a new config knob `kanban.default_model` that controls which model the
kanban dispatcher uses to spawn workers on tasks that don't already have a
per-task `model_override`. Default: empty (legacy behaviour).

Precedence (highest wins):

1. Per-task `model_override` (set at create-time, or via `kanban set-model`)
2. `kanban.default_model` (this new setting — applied to every other task)
3. Assignee profile's own `model` config (legacy fallback)

## Files

| File                                                                                  | Status     | Purpose                                                              |
| ------------------------------------------------------------------------------------- | ---------- | -------------------------------------------------------------------- |
| `hermes/config.yaml`                                                                  | ✅ updated | adds the `kanban:` block with `default_model: personal/gemini-fallback` |
| `hermes/kanban-default-model.patch`                                                   | ✅ created | unified diff for the Hermes source tree (apply during Docker build)  |
| `hermes_cli/config_defaults.py` (inside the image)                                    | needs patch | new `kanban.default_model` field                                     |
| `hermes_cli/kanban_db.py` `_default_spawn()` (inside the image)                       | needs patch | thread the config through to `-m <model> --provider <name>`           |

The source-tree patches are NOT applied automatically — they must be applied when
the Hermes Docker image is built, because the running container bundles its own
copy of `/opt/hermes/hermes_cli/`.

## How to roll this out

### 1. Sync this folder to the MacBook

Syncthing already mirrors `~/Personal` (`/opt/data/Personal`). After the rpi
syncs, the changes appear at `~/Personal/github.com/ayedaemon/pai-stack/hermes/`.

### 2. Review the changes on the MacBook

```bash
cd ~/Personal/github.com/ayedaemon/pai-stack
git diff hermes/config.yaml                          # the kanban: block
cat   hermes/kanban-default-model.patch              # the source-tree patch
```

### 3. Apply the source-tree patch to the Hermes image

The patch targets files that live INSIDE the running `hermes` container, not on the
rpi host. Two ways to apply it:

**(a) Patch at build time — preferred for permanence.** Add the patch to the
Dockerfile / build context so every future build includes it. For example, in
`docker/Dockerfile.hermes` (path may vary):

```dockerfile
COPY hermes/kanban-default-model.patch /tmp/kanban-default-model.patch
RUN cd /opt/hermes \
 && patch -p1 < /tmp/kanban-default-model.patch \
 && rm /tmp/kanban-default-model.patch
```

**(b) Hot-patch a running container (testing only — survives until the next
`docker compose up`).** From the rpi:

```bash
docker compose cp hermes/kanban-default-model.patch hermes:/tmp/k.patch
docker compose exec hermes bash -lc '
  cd /opt/hermes && \
  patch -p1 < /tmp/k.patch && \
  rm /tmp/k.patch'
docker compose restart hermes
```

### 4. Run `./deploy.sh` as usual

```bash
./deploy.sh
```

The `hermes/config.yaml` change is picked up automatically (Ansible copies it
into the container's mounted config on every run).

### 5. Verify

After the deploy completes:

```bash
# Inside the hermes container
docker compose exec hermes hermes kanban inspect-config  # if you have one
# OR (direct)
docker compose exec hermes python3 -c "
from hermes_cli.config import load_config
from hermes_cli.kanban_db import _default_spawn
import inspect
print('default_model:', (load_config().get('kanban') or {}).get('default_model'))
"
```

Then create a kanban task with no `model_override` and watch the worker log:

```bash
tail -f /opt/data/kanban/logs/<task-id>.log
```

The first line of the worker should show the `personal/gemini-fallback` model
loaded, not `personal/free-chat`.

## Rolling back

To disable the new behaviour without removing the patch:

- Set `kanban.default_model: ""` (or remove the block) in `hermes/config.yaml`,
  redeploy. The dispatcher falls back to the assignee profile's model.

To fully revert:

- `git revert` the `config.yaml` change and `docker compose build hermes` to
  rebuild without the patch.