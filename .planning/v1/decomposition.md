# Decomposition — v1

## Spec Units (13)

---

### #1 — CLI Dispatch & Output Formatting
**Covers:** §7.1 Grammar, §7.3 Help, §7.4 Output Format
**Requirements traced:** noun-verb routing (`memory <noun> <verb>`), 6 nouns (neuron, tag, attr, edge, meta, batch), help at every level, JSON/text output, exit codes 0/1/2, --format flag, configurable default
**Dependencies:** None (Tier 0)
**Why one unit:** The dispatch layer, help system, and output formatting are a single skeleton that all other specs plug into. Cannot be tested independently if split.

---

### #2 — Config & Initialization
**Covers:** §7.2 Init & Config
**Requirements traced:** `memory init`, ~/.memory/config.json, db path, embedding model settings, search defaults, Haiku API key env var, --config and --db overrides
**Dependencies:** None (Tier 0)
**Why one unit:** Config loading is one coherent behavior. Init creates config + DB. All other specs depend on config being loadable.

---

### #3 — Schema & Migrations
**Covers:** §2 Storage, §9 Metadata & Integrity (schema versioning, migrations)
**Requirements traced:** SQLite DB file, WAL mode, neurons table, edges table, tag registry table, attribute registry table, FTS5 virtual table, vec0 virtual table, FTS sync triggers, schema version tracking, auto-migration on startup
**Dependencies:** #2 Config (needs db path from config)
**Why one unit:** All tables, indexes, virtual tables, and triggers form one coherent schema. Migrations operate on the schema as a whole. Split would create circular dependencies between table definitions.

---

### #4 — Tag & Attribute Registries
**Covers:** §5 Tags, §6 Attributes
**Requirements traced:** tag registry (integer IDs, lowercase normalization, auto-create on reference), attribute registry (same pattern), tag CRUD (`tag add/list/remove`), attr CRUD (`attr add/list/remove`), no empty tags
**Dependencies:** #3 Schema (registry tables must exist)
**Why one unit:** Tags and attributes share the exact same registry pattern. Implementing one gives you the other. Tag filtering logic (AND/OR) is used by search but defined here as the filtering primitive.

---

### #5 — Embedding Engine
**Covers:** §8 Embedding
**Requirements traced:** llama-cpp-python in-process loading, nomic-embed-text-v1.5 Q8_0, 768 dimensions, task prefix handling (search_document/search_query), embed on demand, batch re-embed (blank/stale vectors), model loads once per invocation, embedding decoupled from storage
**Dependencies:** #2 Config (model path, n_ctx from config), #3 Schema (vectors table for storage)
**Why one unit:** The embedding engine is a self-contained wrapper around llama-cpp-python. It handles model loading, prefix prepending, and vector generation. Other specs call it but don't need to know its internals.

---

### #6 — Neuron CRUD & Storage
**Covers:** §2.1 Neurons, §3.1 Manual Quick Capture, §3.3 Write-and-Wire
**Requirements traced:** neuron add (one-liner capture), neuron get (by ID), neuron list, neuron update, neuron archive, auto-tags (timestamp, project from pwd/git), user tags additive, --link flag with reason, embed immediately on write, FTS5 sync (via triggers from #3)
**Dependencies:** #3 Schema, #4 Tag/Attr registries (tag resolution), #5 Embedding (embed on write)
**Why one unit:** All neuron write operations share the same flow: validate → store → tag → embed → optionally link. Read operations (get/list) are the retrieval primitives that search builds on. Split would require the implementing agent to decide where embed-on-write lives.

---

### #7 — Edge Management
**Covers:** §2.2 Edges, §2.3 Capture Context
**Requirements traced:** edge add (with reason and weight), edge remove, edge list (by neuron), --link flag integration with neuron add, write-and-wire (link new neuron to previously retrieved), circular references valid, capture context linking
**Dependencies:** #3 Schema (edges table), #6 Neuron CRUD (neurons must exist to link)
**Why one unit:** Edge operations are simple CRUD plus the write-and-wire flow. Small enough to be one spec, too dependent on neurons to stand alone as a helper.

---

### #8 — Light Search Pipeline
**Covers:** §4.1 Light Search, §4.3 Search Output, §11 Spreading Activation
**Requirements traced:** BM25 keyword matching (FTS5), vector similarity (sqlite-vec two-step query), RRF fusion (rank-based), spreading activation (Python BFS, linear decay, configurable rate, visited set), tag filtering (AND/OR), temporal decay, fan-out depth (--fan-out-depth N, default 1), pagination (--limit/--offset), --explain scoring breakdown, edge weight modulation in activation
**Dependencies:** #3 Schema (FTS5 + vec0 tables), #4 Tags (tag filtering), #5 Embedding (query embedding), #6 Neurons (result hydration), #7 Edges (graph traversal)
**Why one unit:** All components serve one user command: `memory neuron search`. BM25, vector, RRF fusion, and spreading activation must be integrated in one scoring pipeline. Splitting would require judgment calls about how scores combine.

---

### #9 — Heavy Search (Haiku-Assisted)
**Covers:** §4.2 Heavy Search
**Requirements traced:** Haiku re-ranks light search results, Haiku generates query expansion (related search terms), returns raw data only (no synthesis), re-runs light search with expanded terms
**Dependencies:** #8 Light Search (operates on light search results, re-invokes with expanded queries), #2 Config (Haiku API key)
**Why one unit:** Small scope but distinct behavior from light search. Haiku integration is isolated — it takes light results in, produces re-ranked results out. Cannot be tested without light search.

---

### #10 — Traversal Modes
**Covers:** §4.4 Traversal Modes
**Requirements traced:** timeline (walk forward/backward chronologically from a neuron), goto (follow edges to connected neurons regardless of time)
**Dependencies:** #6 Neurons (timeline ordering), #7 Edges (goto follows edges)
**Why one unit:** Two related navigation behaviors that don't involve search scoring. Distinct from search (no BM25, no vectors, no activation). Small but independently testable.

---

### #11 — Conversation Ingestion
**Covers:** §3.2 Conversation Ingestion
**Requirements traced:** JSONL session file parsing, Haiku extracts entities/facts/relationships, creates neurons and edges from extracted data, source is Claude Code .claude/ session files, batch operation
**Dependencies:** #6 Neuron CRUD (bulk neuron creation), #7 Edge Management (bulk edge creation), #5 Embedding (embed created neurons), #2 Config (Haiku API key)
**Why one unit:** End-to-end pipeline: parse JSONL → call Haiku → create neurons/edges. Distinct from manual capture. Haiku is the core logic here.

---

### #12 — Export/Import
**Covers:** §7.5 Export/Import
**Requirements traced:** export neurons by tag filter or all (JSON format), import with strict schema enforcement (structure, tag registry, vector dimensions, edge references), validate-only dry run mode, backup = copy .db file
**Dependencies:** #6 Neurons, #7 Edges, #4 Tags (tag filtering for export, registry validation for import), #5 Embedding (dimension validation)
**Why one unit:** Export and import are symmetric operations on the same data format. Import validation is the complex part — it checks everything. Cannot split without duplicating the schema definition.

---

### #13 — Metadata & Integrity
**Covers:** §9 Metadata & Integrity (except schema versioning, which is in #3)
**Requirements traced:** DB-level metadata (model name, vector dimensions, neuron/vector stats), vector dimension enforcement, config/DB drift detection on startup (compare config.json vs DB metadata), model change marks all vectors stale
**Dependencies:** #2 Config (reads config), #3 Schema (metadata table), #5 Embedding (model info)
**Why one unit:** Integrity checks are a cross-cutting concern but form one coherent startup validation flow: load config → load DB metadata → compare → warn/block. Small but critical.

---

## Dependency Graph

```
Tier 0 (no dependencies):
  #1 CLI Dispatch & Output
  #2 Config & Initialization

Tier 1 (depends on Tier 0):
  #3 Schema & Migrations          → #2

Tier 2 (depends on Tier 1):
  #4 Tag & Attribute Registries   → #3
  #5 Embedding Engine             → #2, #3
  #13 Metadata & Integrity        → #2, #3, #5

Tier 3 (depends on Tier 2):
  #6 Neuron CRUD & Storage        → #3, #4, #5

Tier 4 (depends on Tier 3):
  #7 Edge Management              → #3, #6
  #10 Traversal Modes             → #6, #7
  #12 Export/Import                → #4, #5, #6, #7

Tier 5 (depends on Tier 4):
  #8 Light Search Pipeline        → #3, #4, #5, #6, #7

Tier 6 (depends on Tier 5):
  #9 Heavy Search                 → #2, #8
  #11 Conversation Ingestion      → #2, #5, #6, #7
```

## Proposed Build Order (waves)

**Wave A:** #1 CLI Dispatch, #2 Config & Init
**Wave B:** #3 Schema & Migrations
**Wave C:** #4 Tag/Attr Registries, #5 Embedding Engine, #13 Metadata & Integrity
**Wave D:** #6 Neuron CRUD
**Wave E:** #7 Edge Management, #10 Traversal, #12 Export/Import
**Wave F:** #8 Light Search Pipeline
**Wave G:** #9 Heavy Search, #11 Conversation Ingestion

7 waves. Waves A, C, E, G have parallel specs within them.
