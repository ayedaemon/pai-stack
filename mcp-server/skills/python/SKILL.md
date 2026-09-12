# Python Project

> Read, understand, and work with any Python codebase fast — detect env, framework, deps, entrypoints, tests.

## When to use
- Trigger: user mentions Python project, `*.py`, `pyproject.toml`, `requirements.txt`, `Pipfile`, `poetry`, `uv`, or asks to read/debug/build a Python app
- Preconditions: project path under `/opt/data/workspace/...` exists; KB may have `Projects/<Name>/README.md`
- Auto-use: when `stack-discovery` detects `pyproject.toml` / `requirements*.txt` / `setup.py` / `.py` files

## Inputs
- Required: project root path (e.g. `/opt/data/workspace/github.com/<org>/<repo>` or `Projects/<Name>` mapping)
- Optional: specific issue/task focus, Python version constraint, framework hint

## Steps
1. Retrieve scoped KB: `AGENTS.md` + `Projects/<Name>/**` + relevant `issues/<slug>.md`. Cite `file:lines`.
2. Scan project root (1 level) and list: `pyproject.toml`, `setup.py`, `setup.cfg`, `requirements*.txt`, `Pipfile`, `poetry.lock`, `uv.lock`, `Makefile`, `.python-version`, `runtime.txt`, `tox.ini`, `Dockerfile` if present.
3. Detect package manager & Python version:
   - `pyproject.toml: [tool.poetry]` → Poetry; `[tool.uv]` / `uv.lock` → uv; `Pipfile` → pipenv; else pip + `requirements.txt`
   - Read `requires-python`, `.python-version`, `runtime.txt`, or `Dockerfile: FROM python:X`
   - Record `file:lines` for version constraint.
4. Detect framework & type:
   - Grep for `import django` / `from django` / `manage.py` → Django
   - `from fastapi` / `import fastapi` → FastAPI
   - `from flask` / `import flask` → Flask
   - `import sqlalchemy` / `alembic` → check Postgres skill if DB present
   - Check `pyproject.toml: [tool.pytest]` / `tests/` / `test_*.py` for test runner
   - Note CLI vs library vs service (look for `if __name__ == "__main__"`, `__main__.py`, `app.py`, `main.py`, `wsgi.py`, `asgi.py`)
5. Map entrypoints & structure:
   - List `src/`, `app/`, `<package>/`, `tests/`, `scripts/` top-level dirs
   - Read `pyproject.toml: [tool.setuptools.packages]` or `[project.scripts]` for entrypoints
   - Read `Makefile` / `justfile` / `package.json` scripts if polyglot
   - Trace `main.py` / `app.py` / `manage.py` 20 lines to find run command
6. Inspect deps & health:
   - Read `pyproject.toml: [project.dependencies]` or `requirements.txt` — flag pinned vs unpinned, known vuln patterns
   - Check `pyproject.toml: [tool.ruff]` / `[tool.black]` / `[tool.mypy]` / `pyright` for lint/type setup
   - Look for `.env.example`, `.env`, `config.py`, `settings.py` — note secret refs, never raw secrets
7. Plan work:
   - For read-only: summarize stack, entrypoint, how to run (`pip install -r requirements.txt` vs `poetry install` vs `uv sync`), test cmd (`pytest`, `python -m unittest`, `tox`)
   - For edits: propose smallest diff, add/update tests in `tests/`, run `python -m py_compile` + relevant test suite before claiming done
   - If Docker present → also retrieve `Skills/docker/SKILL.md`; if Postgres/SQLAlchemy → also `Skills/postgres/SKILL.md`
8. Write & cite:
   - Update `Projects/<Name>/docs/architecture.md` or `issues/<slug>.md` with findings (stack, entrypoints, run/test commands) + `file:lines` citations
   - Post concise summary in originating Telegram topic only, with citations

## Outputs
- Primary: KB update with Python stack summary (manager, version, framework, entrypoints, run/test commands) + citations
- Changelog: what was inspected, what would change, source `file:lines`
- Next step: proposed diff or run command, isolated to topic

## Related files
- `Projects/<Name>/README.md`
- `Projects/<Name>/docs/architecture.md`
- `Projects/<Name>/config.md` (secret refs like `env DATABASE_URL`)
- `Skills/docker/SKILL.md` (if `Dockerfile` present)
- `Skills/postgres/SKILL.md` (if DB layer detected)

## Notes for Hermes
- Keep headings specific (`## Python version`, `## Framework`, `## Entrypoints`) — better retrieval chunks.
- Prefer `pyproject.toml:lines` citations over guessing. If file missing, state gap: "No pyproject.toml — inferred from requirements.txt:12".
- Never `pip install` globally without asking; suggest `uv sync` / `pip install -e .` in project context.
- For polyglot repos, run `stack-discovery` first to confirm Python is primary.
