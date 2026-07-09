# Agent Bootstrap — memory-cli

Project: graph-based memory CLI (`memory <noun> <verb>`).
Stack: Python + SQLite + sqlite-vec. See `CLAUDE.md` for maintenance mode.

## Code Discovery

Use the installed **`codebase`** binary. Do **not** invoke `codebase-memory-mcp`
by name, and do **not** confuse this repo with the separate project
`~/projects/codebase-memory-mcp`.

```sh
codebase --help
```

Canonical invoke (from help):

```text
codebase                         # MCP server on stdio (agents auto-detect)
codebase cli <tool> [json]       # single tool, one-shot
codebase install|uninstall|update
codebase config <list|get|set|reset>
codebase --version
```

UI (optional, persisted): `--ui=true|false`, `--port=N` (default 9749).

### Tools

`index_repository`, `search_graph`, `query_graph`, `trace_path`,
`get_code_snippet`, `get_graph_schema`, `get_architecture`, `search_code`,
`list_projects`, `delete_project`, `index_status`, `detect_changes`,
`manage_adr`, `ingest_traces`

### Preferred shape

```sh
codebase cli <tool> '<json>'
```

Prefer flags / `--args-file` when available (`cli <tool> --help`); raw JSON is deprecated.

### Project key (this repo)

```text
Users-hung-projects-memory-cli
```

If missing from `codebase cli list_projects`, index first:

```sh
codebase cli index_repository '{"repo_path":"/Users/hung/projects/memory-cli"}'
```

### Priority order

1. `search_graph` — symbol / route / class patterns
2. `trace_path` — caller/callee impact
3. `get_code_snippet` — specific function/class source
4. `query_graph` — complex graph questions
5. `get_architecture` — high-level summary
6. `search_code` — string/regex through indexed code
7. Fall back to `rg`/file reads only when CLI has no coverage or for non-code/config

### Examples

```sh
codebase cli search_graph '{"project":"Users-hung-projects-memory-cli","name_pattern":".*Neuron.*"}'
codebase cli search_code '{"project":"Users-hung-projects-memory-cli","pattern":"spreading.?activation","mode":"compact","limit":20}'
codebase cli get_architecture '{"project":"Users-hung-projects-memory-cli"}'
```

If CLI unavailable or project unindexed: say so, then `rg`/source reads.
Do not report “MCP unavailable” as the blocker; interface is the `codebase` CLI.

## Fleet / team

No droid project team for `memory-cli` yet (`droid list` has no `project=memory-cli`).
Do not treat retired `codebase-memory-mcp-*` droids as this repo’s crew.

## Product constraints (see also CLAUDE.md)

- Opaque storage — agents must not browse the DB
- Maintenance: **maintain-operate-orchestration**; acceptance-test-first; pytest multi-run baseline
- Never Haiku for coding (runtime product features only)
