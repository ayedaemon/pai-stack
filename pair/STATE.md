# Pair State — human dashboard

**Updated:** 2026-10-06 (gitkeep done, docs in progress)
**EXECUTION_DIR:** repo root (`pai-stack` itself)

| Area | State |
|---|---|
| `queue/` | 1 example (never claim `_example`) + `pair-review-final-2026-10-06` (claim last) |
| `claims/` | `pair-gitkeep-2026-10-06` (dsh) + `pair-docs-2026-10-06` (dsh) |
| `done/` | `pair-gitkeep-2026-10-06` (dsh, pass pending review) |
| Blocked | none |
| Next review | DSH returns both claims → Hermes takes review-final → merge on human confirm |

## Rules in force (added 2026-10-06)

* One held claim per agent (contract §3, skill poll rule).
* Detached poke + poll `pair/pokes/<peer>-<ts>.log` is mandatory (60s cap).

## Transport (verified 2026-10-06, container-side)

* `dsh --profile headless --patch scripts/pair/dsh-headless-gateway.yml` → gateway → `ok`.
* `poke.py` carries `--patch` always; unknown peers log-only.

## Recently done

(none — see `pair/log.md` for event history)
