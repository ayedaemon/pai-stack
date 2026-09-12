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
   - `GET /search?q=:query&type=hybrid|symbol|text` — multi-modal search (hybrid AST symbols + ripgrep full text)
   - `GET /symbols/:name` — consolidated symbol intelligence (definition, context, callers, callees, graph)
   - `GET /impact/:path` — blast radius of file changes
   - `GET /map` — most-connected files overview
   - `POST /reindex` — trigger workspace reindexing
3. Analyze results — identify affected files, test coverage needs, and risk areas
4. Apply changes with awareness of call chain implications
5. Write result to `findings.md` in the active task plan directory (status: in-progress/review) with `file:lines` citations

## Outputs
- Context analysis with affected files and risk assessment
- `findings.md` updated with codegraph results and `file:lines` citations

## Related files
- `hermes/config.yaml:124` — codegraph.api_url configuration
- `codegraph/server.js:1` — HTTP wrapper implementation
- `docker-compose.yaml:60` — codegraph service definition

## Notes for Hermes
- CodeGraph runs in hybrid mode: Tree-sitter for AST symbol graphs + ripgrep for blazing fast full-text search
- All queries go through HTTP API at `http://codegraph:20128`
- Use `GET /search?q=<term>&type=hybrid` for searching both symbols and content
- Use `GET /symbols/<name>` to fetch full context, callers, and callees in a single query
- For large codebases, start with `/map` to understand structure before deep-diving
