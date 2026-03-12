# memory-cli — Requirements

**Captured:** 2026-03-11

## What it is
A CLI tool for storing and retrieving contextual memory. Not a library. Not a UI. A CLI that AI agents (like Claude) and humans call to tuck away information and find it later by relevance.

## Core Philosophy
- **The AI never sees the storage directly** — the CLI is the only interface. No file browsing, no accidental context blowup.
- **Storage is opaque** — SQLite/graph DB, not human-readable markdown files. Prevents AI agents from being "nosy" and loading everything into context.
- **Like neurons** — memories are nodes, relationships are edges. Pull one node, connected nodes activate.
- **Connections are captured, not inferred** — relationships exist because things were discussed/captured together in the same context. The context of the moment IS the connection. No post-hoc inference needed.
- **No LLM at search time (light mode)** — pure algorithmic search. Fast, deterministic.
- **Haiku earns tokens at ingestion and heavy search** — extraction of entities/relationships at write time, re-ranking at query time.

## Write Paths

### 1. Manual Quick Capture
- One-liner CLI command to tuck away info fast
- Auto-tags at write time:
  - Timestamp
  - Current project (infer from pwd/git repo)
  - Topic/tags (user-provided)
- Example: `memory add "email creds are in 1password" --tags email,credentials`
- Example with link: `memory add "stuff" --tag-ids 1,2 --link <node-id> "<edge reason>"`
- `--link` creates an edge to an existing node at write time with an explicit reason for the connection

### 2. Conversation Ingestion
- Feed a conversation (or chunk of one) into the CLI
- Haiku extracts entities, facts, and relationships automatically
- Wires them into the graph — nodes for entities/concepts, edges for relationships
- Example: a conversation mentioning "QMD", "BM25", "Tobi Lütke", "SQLite" creates nodes for each and edges like "QMD uses BM25", "QMD built by Tobi Lütke", "QMD stores in SQLite"

### 3. Write-and-Wire (linking new memories to old)
- When a memory is retrieved, used in a conversation, and a new memory is saved back — the CLI allows linking the new memory to the old one
- The connection reason: the conversation that bridged them
- This means the graph grows and RE-WIRES over time — old nodes gain new edges to new nodes every time they're used together
- Memories created days or weeks apart become connected because a later discussion brought them together
- Example: Memory A ("email creds in 1password") was created March 1. On March 11, during a conversation about deploying email service, Memory A is retrieved and used. A new Memory B ("email service deployed to prod, uses SES") is saved and linked to Memory A. Now they're connected through the March 11 discussion even though they were created 10 days apart.

## Storage Model

### Graph-based (not flat files)
- **Nodes** = facts, entities, concepts, states, things
  - Properties: content, timestamp, project, tags, source
- **Edges** = relationships between nodes
  - Created at capture time from co-occurrence: things discussed together in the same conversation/capture are connected
  - Edge carries the REASON for connection (same conversation, same project, same time window, shared tag)
  - No post-hoc inference — the context of capture IS the relationship
- **Capture context is first-class** — a conversation or capture session is itself a context node that links everything discussed within it
- **Time series + gotos** — the DB is a chronological timeline of facts, but edges act like goto statements that jump across time to connected nodes. Two traversal modes:
  1. **Timeline** — walk forward/backward chronologically from a node (what else was happening around this time?)
  2. **Goto** — follow edges to connected nodes regardless of when they were created (what's connected to this fact?)

### Database, not files
- SQLite or graph DB — opaque, not browsable
- Embeddings stored in the same DB (sqlite-vec or similar)
- BM25 full-text index in the same DB (FTS5)
- Single file backup = copy the DB

### Storage vs. Embedding separation
- **Storage format** — optimized for structure, relationships, byte efficiency (columns, not JSON)
- **Embedding input** — optimized for semantic meaning: raw content text + tags concatenated (e.g., "email creds are in 1password | email, credentials, memory-cli"). No JSON syntax, no timestamps, no structural noise
- **Embedding is decoupled from storage** — can store now and embed later, re-embed when switching models, add tags and re-embed just that node
- Tags carry semantic meaning and SHOULD be included in the embedding input — they enrich the vector with contextual concepts

### Embedding Engine — llama-cpp-python (in-process)
- `llama-cpp-python` binding loads the GGUF model directly in the CLI process
- No server, no HTTP, no daemon — fully self-contained
- Model loads once per CLI invocation (~300-500ms), then embeds as needed
- Used for both writes (embed new memories) AND searches (embed the query)
- **Batch re-embed command** — iterates the DB for:
  1. **Blank vectors** — nodes that were stored but never embedded
  2. **Stale vectors** — nodes whose content/tags were updated AFTER the vector's timestamp
  - Model loads once, processes all pending, exits
  - Processes only what's needed, skips nodes that are current
- **Model: nomic-embed-text-v1.5** (~260MB GGUF, 768 dimensions)
- llama.cpp also installed via brew (v8270) for reference/tooling

## Search

### Light Search (no tokens burned)
- BM25 keyword matching (instant, ~1ms)
- Vector similarity (semantic, ~50-200ms)
- Graph traversal — follow edges from matched nodes to related nodes
- Tag/category filtering
- Temporal decay — recent memories rank higher

### Heavy Search (Haiku-assisted)
- Haiku re-ranks results for deeper relevance
- Query expansion — Haiku generates related search terms
- Still returns raw data, not Haiku's interpretation
- Burns tokens but cheap (Haiku-tier)

### Output — Match, Fan Out, Show Why
- **Match** — find the node(s) that hit the query
- **Fan out** — show connected nodes with the REASON they're connected (e.g., "discussed together on 2026-03-11 in memory-cli project")
- **Caller decides** — whether to pull the next node or not (progressive disclosure)
- Returns raw memory content, ranked by relevance
- No synthesis, no summarization — CLI returns data, caller decides what to do

## Tags
- Every node has tags — context descriptors about the conversation/moment the memory came from
- Tags are NOT just category labels — they carry context about WHY this memory exists
- Tags assigned at write time (manual or auto-extracted)
- Used as a filter dimension alongside semantic search
- **Tag filtering:** `--tags` = AND (must have all), `--tags-any` = OR (any match). Basic boolean, no grouping syntax in v1.
- Examples: project name, topic, type (credential, preference, fact, procedure), conversation participants, trigger event
- **Byte-efficient timestamps** — tags carry timestamps but stored as compact representations (e.g., uint32 Unix epoch = 4 bytes, not ISO string = 24 bytes). Storage efficiency matters at scale across many nodes and tags.
- **Tag registry** — managed enum of known tags. Tags stored as integer IDs referencing a registry table, not repeated strings. Saves space, prevents typos, enforces consistency. All tags normalized to lowercase on write. Tags can be referenced by name (auto-resolved to ID, auto-created if new) or by ID directly (`--tag-ids 1,2`).
  - `memory tags list` — show all known tags
  - `memory tags add "new-tag"` — register a new tag
  - `memory tags merge "old" "correct"` — consolidate duplicates/typos
- **Attribute registry** — managed key-value metadata on nodes. Same pattern as tags — known attribute keys stored as IDs. The CLI is the only admin interface since the DB is opaque.
  - `memory attr list` — show known attribute keys
  - `memory attr set <node-id> <key> <value>` — set attribute on a node
  - `memory attr get <node-id>` — show all attributes on a node
  - Examples: project, source (manual/conversation/ingestion), status (active/superseded/archived), custom key-values

## Edge Cases (decided)
- **Conflicting memories** — both versions live in the DB (history preserved), but most recent timestamp outranks older. Not deletion — recency weighting. The caller sees both if needed but newer wins by default.
- **Circular references** — allowed. The graph CAN be circular (A→B→C→A). Spreading activation uses a visited set to avoid infinite loops, but circular data is valid and expected.
- **Embedding server down at search time** — fallback to BM25-only search. Degrade gracefully, don't error out.
- **No empty tags** — there's always context. CLI auto-captures timestamp + project (from pwd/git) at minimum. User-provided tags are additive. Empty tags are impossible by design.
- **Fan-out limits** — `--fan-out-depth N` flag controls how many hops from the matched node (0=match only, 1=direct connections, 2=two hops, etc.). Default 1. Spreading activation decay reduces score at each hop.
- **Concurrent access** — single user, multiple agents. SQLite WAL mode for concurrent reads. Writes are serialized (one at a time) with busy timeout — fine at v1 scale since writes are fast appends, not updates.
- **Sensitive data** — out of scope for v1. User responsibility. Encryption is a future consideration.
- **Model change** — DB metadata tracks which model generated vectors. `memory meta set model "new-model"` marks all vectors stale, `memory batch embed` re-embeds them.

## CLI Grammar — AI-first, noun-verb pattern

`memory <noun> <verb> [args]`

### Nouns:
- `neuron` — facts, memories, content
- `tag` — tag registry
- `attr` — attribute registry and node metadata
- `edge` — connections between nodes
- `meta` — DB-level metadata (model, vector dimensions, version, stats). Enforces vector dimension consistency.
- `batch` — bulk operations (re-embed, ingest)

### Init & Config:
```
memory init                # creates ~/.memory/config.json + ~/.memory/memory.db
```
- Config at `~/.memory/config.json` is the root of everything:
  - `db_path` — where the SQLite DB lives
  - `llama.model_path` — GGUF embedding model location
  - `llama.vector_dim` — embedding dimensions (768 for nomic)
  - `llama.n_gpu_layers` — GPU offloading
  - `llama.pooling` — pooling strategy (mean)
  - `llama.normalize` — normalization mode
  - `defaults.fan_out_depth` — default hop depth
  - `defaults.decay` — decay function (linear)
  - `defaults.limit` — default result count
  - `defaults.format` — output format (json)
  - `haiku_api_key_env` — env var name for Haiku API key
- Everything fans out from this config
- `--config <path>` flag overrides config location for edge cases
- `--db <path>` flag overrides db location

### Help:
```
memory help                # list all nouns
memory <noun> help         # list all verbs for a noun
memory <noun> <verb> --help  # flags and usage for a specific command
```

### Commands:
```
memory neuron add "content" --tags email,creds --link #id "reason"
memory neuron get #a3f7c2
memory neuron search "query" --fan-out-depth 2 --tags email,aws --tags-any deploy,prod
memory neuron list --tags email --limit 10
memory neuron export --tags email --format json
memory neuron export --all --format json
memory neuron import < neurons.json
memory neuron import --validate-only < neurons.json

memory tag list
memory tag add "new-tag"
memory tag merge "old" "correct"

memory attr set #a3f7c2 status archived
memory attr get #a3f7c2
memory attr list

memory edge add #a3f7c2 #c9f2a1 "reason"
memory edge list #a3f7c2

memory meta list
memory meta set model "nomic-embed-text-v2"

memory neuron archive #a3f7c2

memory edge remove #a3f7c2 #c9f2a1

memory batch embed
memory batch status
memory batch ingest <session-jsonl-path>
```

## Output & Behavior
- **Output format** — `--format json` (default, for AI callers) or `--format text` (human-readable). Configurable default in config.json.
- **Pagination** — `--limit N --offset M` for progressive disclosure through results
- **Exit codes** — 0=success/found, 1=not found, 2=error. Predictable for scripting and AI callers.
- **Debug/explain mode** — `--explain` flag shows why a result ranked where it did (BM25 score, vector score, fan-out hop, decay applied)
- **DB schema migrations** — DB carries a schema version number. CLI detects outdated schema and runs migrations automatically on startup.
- **Config/DB drift detection** — on startup, CLI compares config.json values (model, vector_dim, etc.) against DB metadata. If they differ, warn the user and block operations that would produce inconsistent data (e.g., embedding with wrong dimensions). Suggest corrective action (`memory batch embed` or update config).

## Key Non-Requirements
- NOT a markdown file manager
- NOT human-browsable storage
- NO LLM synthesis in output
- NO file-per-memory directory structure

## Key Design Concepts (accepted)

### Spreading Activation (search model)
The actual algorithm for the "neuron" pattern. Search hits a node → activation spreads along edges to neighbors → decays with distance → produces ranked fan-out. This IS the search model. Well-established in cognitive science and AI. Implementable as a graph traversal with decay weights.

### Recursive CTEs in SQLite (graph traversal)
SQLite can model a full property graph (nodes table + edges table) and traverse it with `WITH RECURSIVE` queries. No Neo4j needed. Fast at this scale. This is the implementation path — plain SQLite as the graph engine.

## Concepts for Further Discussion
- **Bi-temporal modeling** — two time dimensions: valid time (when fact was true) vs. transaction time (when recorded). Enables "what did I know as of date X?" queries. Relevant if facts get updated or contradicted.
- **Content-addressable storage** — hash content = ID (like Git). Free dedup and change detection. QMD uses SHA-256 for this.
- **Bloom filters for tags** — probabilistic set membership in a few bytes. Byte-efficient tag lookups at scale. Worth evaluating if tag volume gets high.
- **Zettelkasten method** — Luhmann's atomic-note-with-links system. The value is in the links, not the notes. Validates this design's emphasis on edges over nodes.

## Inspiration / Prior Art
- QMD (Tobi Lütke) — hybrid search architecture, SQLite + sqlite-vec + FTS5, but markdown-first (we're DB-first)
- MemSearch (Zilliz) — conversation ingestion pattern, file watcher
- Graphiti (Zep) — temporal knowledge graph with entity extraction, episodic memory
- The video tier list recommended three-tier (Obsidian + QMD + SQLite) — we're collapsing that into one tool

## Open Questions
- ~~Language choice~~ — **decided: Python** with `llama-cpp-python` binding. Model loads in-process, no server dependency.
- ~~Embedding model~~ — **decided: nomic-embed-text-v1.5** (~260MB, 768 dimensions)
- ~~How does Claude call this~~ — **decided: Bash tool invocation.** No MCP. Claude calls `memory <noun> <verb>` via Bash like any CLI.
- ~~Export/backup format~~ — **decided: backup = copy the .db file.** For selective export: `memory neuron export --tags <tags> --format json` extracts a subset of neurons by tag. Import via `memory neuron import < file.json` with strict schema enforcement — validates structure, tag registry, vector dimensions, edge references. `--validate-only` for dry run. Enables sharing, seeding new DBs, or moving knowledge between systems.
- Conversation ingestion format — pipe in raw text? JSON transcript?
- ~~Spreading activation decay~~ — **decided: linear decay**, configurable. Default drops evenly per hop (hop 1: 0.75, hop 2: 0.50, hop 3: 0.25).
- **Sharding / multi-DB** — v1 is single DB, but design should not preclude spanning multiple DBs or sharding later (e.g., per-project DBs, archive shards)
