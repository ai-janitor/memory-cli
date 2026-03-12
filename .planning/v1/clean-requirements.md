# memory-cli — Clean Requirements (v1)

## 1. Product Definition
- A CLI tool for storing and retrieving contextual memory
- Callable by AI agents (via Bash) and humans
- AI-first design — grammar, output, and behavior optimized for agent consumption

## 2. Storage
- All data stored in a single opaque database file — not human-readable, not browsable
- AI agents cannot access storage directly — CLI is the only interface
- Graph-based storage: neurons (nodes) and edges (relationships)
- Single-file backup (copy the DB)
- Design must not preclude multi-DB / sharding in future versions

### 2.1 Neurons
- A neuron represents a fact, entity, concept, state, or thing
- Properties: content, timestamp, project, tags, source, attributes
- Every neuron has at minimum: timestamp and project (auto-captured from pwd/git)

### 2.2 Edges
- An edge represents a relationship between two neurons
- Every edge carries a REASON for the connection
- Edges have a weight (default 1.0) that modulates spreading activation strength
- Edges are created at capture time from co-occurrence (things discussed together)
- Edges can be created explicitly via CLI (`--link` flag or `edge add` command)
- Circular references are valid — the graph can contain cycles
- The graph grows and re-wires over time as old neurons gain new edges through later conversations

### 2.3 Capture Context
- A conversation or capture session is itself a context that links all neurons created or referenced within it
- Connections are captured, not inferred — the context of the moment IS the relationship

## 3. Write Operations

### 3.1 Manual Quick Capture
- One-liner CLI command to store a fact
- Auto-tags: timestamp, current project (from pwd/git)
- User-provided tags are additive
- Optional: link to existing neuron with a reason at write time
- Embeds immediately on write (model loads in-process)

### 3.2 Conversation Ingestion
- Feed a Claude Code session transcript (JSONL) into the CLI
- Haiku extracts entities, facts, and relationships
- Creates neurons and edges from the extracted data
- Source of ingested data is Claude Code's `.claude/` session files

### 3.3 Write-and-Wire
- When a neuron is retrieved, used in a conversation, and a new neuron is saved — the new neuron can be linked to the old one
- The edge reason references the conversation that bridged them
- Neurons created at different times become connected through later discussions

## 4. Search & Retrieval

### 4.1 Light Search (algorithmic, no LLM)
- BM25 keyword matching
- Vector similarity (semantic)
- Graph traversal via spreading activation — activation spreads along edges, decays linearly per hop
- Tag filtering: AND (`--tags`) and OR (`--tags-any`)
- Temporal decay — recent neurons rank higher
- Configurable fan-out depth (`--fan-out-depth N`, default 1)

### 4.2 Heavy Search (Haiku-assisted)
- Haiku re-ranks results for deeper relevance
- Haiku generates query expansion (related search terms)
- Returns raw data — no synthesis or summarization by the LLM

### 4.3 Search Output
- Match: the neuron(s) that hit the query
- Fan out: connected neurons with the REASON they're connected
- Caller decides whether to pull the next neuron (progressive disclosure)
- Pagination: `--limit N --offset M`
- No synthesis, no summarization — raw data only
- Debug mode: `--explain` shows scoring breakdown (BM25, vector, hop, decay)

### 4.4 Traversal Modes
- Timeline: walk forward/backward chronologically from a neuron
- Goto: follow edges to connected neurons regardless of creation time

## 5. Tags
- Context descriptors about the conversation/moment the memory came from
- Not just category labels — carry context about WHY a memory exists
- Tag registry: managed enum of known tags, stored as integer IDs
- All tags normalized to lowercase on write
- Tags can be referenced by name (auto-resolved to ID, auto-created) or by ID
- Tags included in embedding input (they carry semantic meaning)
- Tag filtering: AND and OR, no complex grouping in v1
- No empty tags possible — auto-capture ensures minimum context

## 6. Attributes
- Key-value metadata on neurons
- Attribute keys stored as IDs in a registry (same pattern as tags)
- CLI is the only admin interface for attributes
- Examples: project, source, status (active/superseded/archived), custom values

## 7. CLI Interface

### 7.1 Grammar
- AI-first noun-verb pattern: `memory <noun> <verb> [args]`
- Nouns: neuron, tag, attr, edge, meta, batch

### 7.2 Init & Config
- `memory init` creates global config and DB at `~/.memory/`
- `memory init --project` creates project-scoped config and DB at `.memory/` in cwd
- Config resolution chain: `--config` flag → walk up from cwd for `.memory/config.json` → `~/.memory/config.json`
- Project-scoped memory is isolated — its own DB, its own config
- Config includes: db path, embedding model settings, defaults for search behavior, Haiku API key env var
- `--config` and `--db` flags override for edge cases
- `memory init` is a top-level command (exception to noun-verb grammar, like `git init`)

### 7.3 Help
- `memory help` — list all nouns
- `memory <noun> help` — list all verbs for a noun
- `memory <noun> <verb> --help` — flags and usage

### 7.4 Output Format
- Default: JSON (for AI callers)
- Alternative: plain text (for humans)
- Configurable default in config.json
- Exit codes: 0=success/found, 1=not found, 2=error

### 7.5 Export/Import
- Export neurons by tag filter or all: `memory neuron export --tags X --format json`
- Import with strict schema enforcement: validates structure, tag registry, vector dimensions, edge references
- Validate-only dry run mode
- Backup: copy the .db file

## 8. Embedding
- Embedding model loaded in-process via llama-cpp-python binding
- Model: nomic-embed-text-v1.5 (GGUF, ~260MB, 768 dimensions)
- Model loads once per CLI invocation (~300-500ms tax per call)
- Embedding input: content text + tags concatenated, no structural noise
- Task prefix prepended transparently by CLI: `search_document:` when storing, `search_query:` when searching (required by nomic-embed-text-v1.5)
- Storage format is separate from embedding input format
- Embedding is decoupled — can store without embedding, re-embed later
- Batch re-embed: finds blank vectors (never embedded) and stale vectors (content updated after vector timestamp)
- Search queries also need embedding (same model, same invocation)

## 9. Metadata & Integrity
- DB-level metadata tracks: model name, vector dimensions, schema version, neuron/vector stats
- Vector dimension enforcement — all vectors must match configured dimensions
- Config/DB drift detection: CLI compares config.json against DB metadata on startup, warns and blocks inconsistent operations
- Model change: updating model in config marks all vectors stale
- DB schema version with automatic migrations on startup

## 10. Edge Cases
- Conflicting memories: both live, most recent outranks by default
- Circular references: valid, spreading activation uses visited set
- Embedding unavailable at search: fallback to BM25-only
- Concurrent access: single user, multiple agents, SQLite WAL mode, serialized writes with busy timeout
- Sensitive data: out of scope for v1, user responsibility

## 11. Spreading Activation (search algorithm)
- Search hits a neuron → activation spreads along edges to neighbors → decays linearly with distance
- Default linear decay: hop 1 = 0.75, hop 2 = 0.50, hop 3 = 0.25
- Configurable decay rate
- Fan-out depth configurable per query, default 1

## 12. Development Constraints
- Haiku is ONLY used as a runtime component inside the product (conversation ingestion, search re-ranking/query expansion)
- All coding, scaffolding, and implementation work uses Sonnet or Opus — never Haiku
- When spawning subagents for implementation tasks, explicitly use `model: "sonnet"` or `model: "opus"`

## 13. Non-Requirements (v1)
- NOT a markdown file manager
- NOT human-browsable storage
- NO LLM synthesis in output
- NO file-per-memory directory structure
- NO MCP server — Bash invocation only
- NO encryption
- NO complex tag boolean grouping syntax
- NO multi-DB / sharding (design must not preclude it)
