# CodeGraph — Code Intelligence

> Query code structure, call chains, and impact analysis via CodeGraph HTTP API.

## When to use
- Before editing code: get context on functions/classes you're modifying
- When debugging: trace call chains to find root cause
- When refactoring: analyze blast radius of changes
- When asked about architecture: get module summary and dependencies
- Before code review: understand impact of changes

## Inputs
- Required: symbol name (function, class, method) or file path
- Optional: depth of analysis, specific tool to use

## Steps
1. Identify what you need: symbol context, callers/callees, impact analysis, or search
2. Query CodeGraph via HTTP:
   - `GET /context/:symbol` — full context (source, callers, callees, deps)
   - `GET /callers/:symbol` — who calls this function
   - `GET /callees/:symbol` — what this function calls
   - `GET /impact/:path` — blast radius of file changes
   - `GET /search?q=:query` — semantic symbol search
   - `GET /map` — most-connected files overview
3. Analyze results — identify affected files, test coverage needs, and risk areas
4. Apply changes with awareness of call chain implications
5. Write result to issue file (status: in-progress/review) with `file:lines` citations

## Outputs
- Context analysis with affected files and risk assessment
- Updated issue file with codegraph findings
- Changelog entry in originating Telegram topic

## Related files
- `hermes/config.yaml.j2:150` — codegraph.api_url configuration
- `codegraph/server.js:1` — HTTP wrapper implementation
- `docker-compose.yaml:69` — codegraph service definition

## Notes for Hermes
- CodeGraph runs in graph-only mode (no embeddings) — fast queries, minimal RAM
- All queries go through HTTP API at `http://codegraph:20128`
- Results are cached in-memory by CodeGraph — repeated queries are fast
- For large codebases, start with `/map` to understand structure before deep-diving
