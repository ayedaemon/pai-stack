---
name: python
description: Read, understand, and work with any Python codebase fast — detect env, framework, deps, entrypoints, tests.
---
# Python Project

> Read, understand, and work with any Python codebase fast — detect env, framework, deps, entrypoints, tests.

## When to use
- IF the user mentions a Python project, `*.py`, `pyproject.toml`, `requirements.txt`, `uv`, etc., OR asks to read/debug/build a Python app, THEN you MUST execute this skill.
- IF `skill://stack-discovery` detects a Python stack, THEN you MUST execute this skill.
- Preconditions: project path under `/opt/data/workspace/...` exists; KB may have `Projects/<Name>/README.md`

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
7. Plan work & Execution:
   - For read-only: summarize stack, entrypoint, how to run, and test cmd.
   - For edits: propose smallest diff, add/update tests in `tests/`.
   - **Execution Enforcements**:
     - ALWAYS use `uv run <command>` (e.g., `uv run pytest`, `uv run python main.py`) to execute code, tests, or scripts to ensure isolated, correct environment usage.
     - NEVER build the project into egg files or wheels (e.g., `python setup.py bdist_egg`, `uv build`) unless the user explicitly requests a package build.
    - If Docker present → also retrieve `Skills/docker/SKILL.md`; if Postgres/SQLAlchemy → also `Skills/sql/SKILL.md`
8. Write & cite:
   - Update `Projects/<Name>/docs/architecture.md` or `issues/<slug>.md` with findings (stack, entrypoints, run/test commands) + `file:lines` citations
   - Post concise summary in originating Telegram topic only, with citations

## Python Patterns & Development Guidelines

When writing, editing, or planning Python code, you MUST adhere to the following conventions:

### 1. Modern Syntax & Typing (Python 3.10+)
- Always use strict type hinting. Use modern syntax like `list[str]` instead of `typing.List` and `X | Y` instead of `typing.Union`.
- Prefer `pydantic.BaseModel` for data validation/API boundaries and `@dataclass` for internal models. Avoid bare dictionaries or tuple soup for complex structures.

### 2. Async & Concurrency
- Use `asyncio` for I/O bound tasks. Prefer `httpx` or `aiohttp` over synchronous `requests` in async contexts.
- **Anti-Pattern**: NEVER block the event loop (e.g., using `time.sleep()` or heavy CPU-bound synchronous calls inside `async def`).

### 3. Logging & Security Posture (Default-On)
- Always implement robust structured logging (e.g., standard `logging` or `loguru`). Catch exceptions and log them with context rather than silently failing.
- Default to secure practices: NEVER hardcode secrets (use environment variables/`os.getenv`), validate all inputs, and use ORMs or parameterized queries to prevent SQL injection.

### 4. Framework Baselines (FastAPI / SQLAlchemy)
- **FastAPI**: Leverage dependency injection (`Depends()`) for auth/DB sessions. Keep routes clean by pushing business logic to service layers.
- **SQLAlchemy**: Use modern declarative models (V2.0 style). Prefer `async_session` in async contexts and always manage sessions safely (e.g., context managers).

### 5. Critical Anti-Patterns to Avoid
- **Mutable Default Arguments**: `def func(items=[])` is forbidden. Use `items=None` and initialize inside.
- **Bare Exceptions**: `except:` or `except Exception: pass` is forbidden. Catch specific exceptions.
- **Arrow Code**: Avoid deeply nested control flow. Return early to keep the happy path flat.

## Verification
- Verify that `uv run` was used for any execution or test commands.
- Verify that no `.egg-info` or `.egg` files were generated unless explicitly requested.

## Outputs
- Primary: KB update with Python stack summary (manager, version, framework, entrypoints, run/test commands) + citations
- Changelog: what was inspected, what would change, source `file:lines`
- Next step: proposed diff or run command, isolated to topic

## Related files
- `Projects/<Name>/README.md`
- `Projects/<Name>/docs/architecture.md`
- `Projects/<Name>/config.md` (secret refs like `env DATABASE_URL`)
- `Skills/docker/SKILL.md` (if `Dockerfile` present)
- `Skills/sql/SKILL.md` (if DB layer detected)

## Notes for Hermes
- Keep headings specific (`## Python version`, `## Framework`, `## Entrypoints`) — better retrieval chunks.
- Prefer `pyproject.toml:lines` citations over guessing. If file missing, state gap: "No pyproject.toml — inferred from requirements.txt:12".
- Never `pip install` globally without asking; suggest `uv sync` / `pip install -e .` in project context.
- For polyglot repos, run `stack-discovery` first to confirm Python is primary.
