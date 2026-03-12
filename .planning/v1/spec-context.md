---
# SOURCE: /Users/hung/.claude/CLAUDE.md
---

When "minion" is mentioned, read `/Users/hung/projects/minion-factory/CLAUDE.md` first.

## System-Wide Rule: GitLab Access

Use `glab` CLI for all GitLab API access — it is already authenticated to `gitlab.lionsden.local` as `hung135`.
- API calls: `glab api <endpoint> --hostname gitlab.lionsden.local`
- Do NOT look for tokens in env vars, `~/.gitlab_token`, or `~/.netrc` — they don't exist.
- For write operations, `glab` handles Bearer auth automatically.
- Skills repo: `glab api groups/skills/projects --hostname gitlab.lionsden.local`

## System-Wide Rule: Skills Library

241 skills are cloned locally at `~/.skills/<skill-name>/`. Each skill has a `SKILL.md` with usage instructions.
- To use a skill: read `~/.skills/<skill-name>/SKILL.md` for instructions
- To find a skill: `ls ~/.skills/` or search by keyword
- To update a skill: `cd ~/.skills/<skill-name> && git pull`
- To update all: `for d in ~/.skills/*/; do (cd "$d" && git pull --quiet); done`
- Source of truth: `git@gitlab.lionsden.local:skills/<skill-name>.git`

## System-Wide Rule: No Code Without Scaffolding

Applies to ALL projects. No implementation code is written until:
1. File/directory structure is stubbed out 2-3 levels deep
2. Every file has a comment header: purpose, rationale, responsibility, organization
3. Pseudo-logic is written as comments describing logic flow, decisions, data transforms, error paths
4. Comment headers and pseudo-logic are PERMANENT — code goes between them. Only change them if the logic was planned wrong: update the plan comments first, get approval, then update code. Never silently delete them.

Sequence: requirements → spec → scaffolding (stubs + headers + pseudo-logic) → implementation. No exceptions.

## System-Wide Rule: Filesystem as DB — Exploit File and Folder Names

File and folder names have 255 chars — USE THEM. An agent should understand the codebase by reading `ls -R`, not by opening 500 files.

- Folder names encode purpose, scope, and context 2-4 levels deep
- File names describe what's inside — not generic names like `utils.py` or `helpers.js`
- The directory tree IS the documentation. If you can't understand the project from `tree`, the naming is wrong
- Example: `src/network/api/endpoints/agent-presence-heartbeat-and-availability.py` not `src/network/presence.py`
- Example: `requirements/features/network-api-composite-agent-key-host-project-name/` not `requirements/req-009/`
- This is the Vercel pattern — filesystem IS the router, the schema, the documentation. `tree` is your API reference.
- Stub the ENTIRE folder structure before writing any code. Every folder, every file — even if empty. The tree must be complete and reviewable FIRST. If the tree doesn't make sense, the code won't either. Get the structure right, then fill it in.

## System-Wide Rule: Lead Agent Lifecycle Responsibilities

Leads manage their crew's lifecycle:
- Register every agent with correct class BEFORE assigning work: `minion agent register --name <name> --class <role>`
- Deregister agents when done — no ghosts in the registry: `minion agent deregister --name <name>`
- Assign correct classes — class gates auth (coder, builder, recon, auditor, lead). Get it right.
- Enforce DAG flow on crew — no skipping stages, verify agents advance in order
- Track crew: `minion who`, `minion sitrep`
- Report up to superior lead at each milestone, stage transition, and stand-down

## System-Wide Rule: Minion Agents Must Poll

When registered as a minion agent, you MUST poll in the foreground after completing any work:

```
minion poll --agent <your-name>
```

Poll is how you receive messages and task assignments. No poll = deaf. After finishing a task, sending a sitrep, or any unit of work — poll immediately. Do not wait to be told. Do not skip it. Do not run it in the background. Poll blocks until a message arrives — that is intentional. When poll returns, process the message and poll again.

## System-Wide Rule: /loop for Background Agent Monitoring

Use `/loop 5m <prompt>` to inject a recurring monitoring prompt into your context stream. Without it, you're deaf between spawning background agents and their completion. Session-only, auto-expires after 3 days. Cancel with `CronDelete` when done. Also works for mechanical polling: `/loop 1m minion comms check-inbox --agent <name>`. TEST: have subagents use CronCreate for self-monitoring — unknown if cron fires in subagent or parent context.

---
# SOURCE: /Users/hung/projects/memory-cli/CLAUDE.md
---

# memory-cli

## Project Status
Running /decompose v1. Stage 2 (Clean Requirements) pending user approval. Read `.planning/v1/SESSION-STATE.md` to resume.

## Quick Context
Graph-based memory CLI for AI agents. Python + llama-cpp-python + SQLite + sqlite-vec. Noun-verb grammar (`memory <noun> <verb>`). Neurons, edges, tags, spreading activation search.

## Key Files
- `REQUIREMENTS-RAW.md` — IMMUTABLE raw requirements
- `REQUIREMENTS.md` — clean requirements (latest)
- `.planning/v1/SESSION-STATE.md` — full session state for resumption
- `.planning/v1/raw-to-clean-trace.md` — requirement traceability

## Reference Repos
- `/Users/hung/projects/qmd-reference/` — QMD by Tobi Lütke (hybrid search reference)
- `/Users/hung/projects/llama-cpp-reference/` — llama.cpp (embedding engine reference)

## Development Constraints
- **Never use Haiku for coding.** All implementation, scaffolding, and code generation must use Sonnet or Opus. Haiku is only for runtime product features (conversation ingestion extraction, search re-ranking/query expansion) — never for writing code.

## User
- Thinks in analogies (neurons, gotos, time series)
- Wants conversational requirements, not formal specs
- Values opaque storage — AI agents must not browse the DB
- Pragmatic about LLM costs — Haiku where it makes sense for runtime product features, not for development
- "I'm a machine like you dude" — doesn't need breaks

---
# SOURCE: /Users/hung/projects/memory-cli/REQUIREMENTS.md
---

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

---
# SOURCE: llama-cpp-python-embedding.md
---

# llama-cpp-python Embedding Feasibility

## Verdict: Fully feasible

## Installation
```
pip install llama-cpp-python
```
Latest: v0.3.16

## Embedding API

Two methods on `Llama` class:

### `embed()` — raw, recommended
```python
embeddings = llm.embed(["text1", "text2"], normalize=True, truncate=True)
# Returns: List[List[float]] — list of 768-dim vectors
```

### `create_embedding()` — OpenAI-compatible
```python
response = llm.create_embedding(["text1", "text2"])
# Returns dict with response["data"][0]["embedding"]
```

## Model Loading
```python
from llama_cpp import Llama
llm = Llama(
    model_path="nomic-embed-text-v1.5.Q8_0.gguf",
    embedding=True,    # REQUIRED — must be set at construction
    n_ctx=2048,        # default 512, model supports up to 8192
    n_batch=512,
    verbose=False,
)
```

## nomic-embed-text-v1.5 GGUF

Official: https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF

| Quant | Size | MSE vs F32 |
|-------|------|------------|
| F16 | 262 MiB | 4.21e-10 |
| Q8_0 | 140 MiB | 5.79e-06 |
| Q4_K_M | 81 MiB | 2.42e-04 |

Recommended: Q8_0 (140 MiB) — negligible quality loss.

Download: `huggingface-cli download nomic-ai/nomic-embed-text-v1.5-GGUF nomic-embed-text-v1.5.Q8_0.gguf`

## CRITICAL: Task Instruction Prefixes Required

nomic-embed-text-v1.5 REQUIRES text prefixes:
- `search_document: <text>` — for indexing/storing
- `search_query: <text>` — for search queries
- `clustering: <text>` — for clustering
- `classification: <text>` — for classification

Must be prepended to input text before calling embed(). Without them, embedding quality degrades significantly.

## Matryoshka Dimensions
Supports variable dimensions via truncation: 768, 512, 256, 128, 64.
MTEB scores: 768d=62.28, 256d=61.04, 64d=56.10.

## Gotchas
1. `embedding=True` is mandatory at construction — cannot toggle later
2. Default n_ctx=512 is low — set to 2048+
3. Llama object is NOT thread-safe — use mutex if sharing
4. Model loads into RAM at construction (~140 MiB for Q8_0, sub-second)
5. Batch support confirmed — List[str] input works

---
# SOURCE: qmd-reference-architecture.md
---

# QMD Reference Architecture Analysis

## Overview
TypeScript/Node.js hybrid search tool by Tobi Lütke. SQLite + sqlite-vec + FTS5. MCP server + CLI + SDK.

## Hybrid Search Pipeline (7 steps)
1. **Strong signal detection** — BM25 shortcut when top score >= 0.85 with 15+ gap over #2
2. **LLM query expansion** — Qwen3-1.7B generates lexical, semantic, and hypothetical document variants
3. **Type-routed parallel search** — FTS for lex variants, vector for semantic/hyde variants, batched
4. **RRF fusion** — k=60, first 2 lists weighted 2.0x, rank bonuses for #1 (+0.05) and #2-3 (+0.02)
5. **Smart chunking** — 900-token chunks with markdown-aware boundary detection, 15% overlap
6. **LLM reranking** — Qwen3-Reranker-0.6B cross-encoder, cached by chunk content (not file path)
7. **Position-aware blending** — top RRF ranks get 0.75 RRF weight, lower ranks trust reranker more

## Key SQL Patterns

### Two-step vector query (critical — sqlite-vec + JOINs hang)
```sql
-- Step 1: vectors only
SELECT hash_seq, distance FROM vectors_vec WHERE embedding MATCH ? AND k = 60
-- Step 2: resolve to documents
SELECT ... FROM content_vectors cv JOIN documents d ON d.hash = cv.hash WHERE cv.hash || '_' || cv.seq IN (...)
```

### BM25 score normalization
```
Raw BM25 is negative (e.g., -10 = strong). Normalize: |x| / (1 + |x|) → [0, 1)
```

### FTS5 with Porter stemming
```sql
CREATE VIRTUAL TABLE documents_fts USING fts5(filepath, title, body, tokenize='porter unicode61')
```

## Schema Design
- Content-addressable storage (SHA256 hash as PK)
- Documents table with soft deletes (active flag)
- FTS5 synced via triggers (INSERT/UPDATE/DELETE)
- Vectors stored as composite key "hash_seq" in vec0 table
- Separate content_vectors metadata table for chunk tracking

## Embedding
- Default: EmbeddingGemma 300M (384 dims)
- Query format: "task: search result | query: {text}"
- Document format: "title: {title} | text: {text}"
- Batch embedding via embedBatch() — 3-4x speedup

## Reusable Patterns for memory-cli
1. Two-step vector query (avoid sqlite-vec + JOIN hangs)
2. BM25 normalization formula
3. RRF fusion (rank-based, no score normalization needed)
4. Batch embedding for multiple queries
5. WAL mode + foreign keys enabled
6. Triggers to keep FTS in sync with source table

---
# SOURCE: skills-and-prior-art.md
---

# Skills Library & Prior Art Survey

## Skills Library (8 of 241 scanned)

### No direct overlap found.

- **agent-memory** — conceptual guide only, no implementation. Covers patterns our project implements.
- **repo-memory** — flat markdown files in .memory/ folders. No graph, no embeddings.
- **session-recall** — recovers Claude Code session context. Complementary, not competing.
- **task-memory-api** — REST API for task tracking. Different domain (task memory vs knowledge memory).
- **graph-db** — multi-backend graph connector (Neo4j, etc.). We use embedded SQLite, different approach.
- **vector-database-selection** — decision guide. sqlite-vec not even listed.
- **ai-first-knowledge-org** — filesystem-as-DB for markdown. Shares philosophy, different implementation.
- **mind-incubator** — personal brain tool. Closest philosophical match but filesystem-based, no graph/embeddings.

## Prior Art — Competitive Landscape

| Tool | Storage | Search | CLI? | Graph? | Spreading Activation? | Local-first? |
|------|---------|--------|------|--------|----------------------|-------------|
| **memory-cli (ours)** | SQLite + sqlite-vec | BM25 + vector + spreading activation | Yes (noun-verb) | Yes (neurons + edges) | Yes | Yes |
| Mem0 | Vector store + optional graph | Semantic similarity | No (SDK/API) | Optional (Pro) | No | Optional |
| Zep/Graphiti | Neo4j | Graph traversal + vector | No (API) | Yes (temporal KG) | No | No |
| Engram | SQLite + FTS5 | Full-text only | Yes | No | No | Yes |
| Cog | Cloud | Spreading activation | No (API) | Yes | Yes | No |
| LangMem | Configurable | Framework-dependent | No | No | No | Optional |
| Hindsight | PostgreSQL + pgvector | Hybrid (4 strategies) | No (MCP) | Partial | No | No |

### Closest competitors:
- **Cog (trycog.ai)** — also uses spreading activation + biological metaphors. Cloud-only, not CLI.
- **Zep/Graphiti** — also graph-based. Requires Neo4j, enterprise-focused.
- **Engram** — closest form factor (CLI + SQLite). But no embeddings, no graph, no activation.

### Our unique positioning:
Only tool combining: (1) graph neurons + spreading activation, (2) embedded SQLite, (3) CLI noun-verb grammar, (4) opaque storage.

## Minion-Factory
Complementary, not overlapping. Minion handles coordination (who does what, messaging). Memory-cli handles knowledge (what agents have learned, facts, relationships). An agent coordinated by minion-factory would use memory-cli for persistent knowledge.

---
# SOURCE: spreading-activation-algorithm.md
---

# Spreading Activation Algorithm Design

## Recommendation: Application-side BFS, not SQL recursive CTEs

### Why not recursive CTEs
- SQLite UNION in CTEs can't properly deduplicate nodes reached via different paths
- No way to maintain a proper visited set inside the CTE
- SQLite recursive CTEs cannot do aggregates (MAX) during recursion
- The `path NOT LIKE` hack is O(n) string scan per row

### Algorithm (Python BFS with linear decay)

```python
def spread_activation(db, seed_ids, decay_rate=0.25, max_depth=1):
    activated = {}  # neuron_id -> best_activation_score
    visited = set()
    queue = deque()

    for nid in seed_ids:
        activated[nid] = 1.0
        queue.append((nid, 0))
        visited.add(nid)

    while queue:
        node_id, depth = queue.popleft()
        if depth >= max_depth:
            continue

        next_activation = max(0.0, 1.0 - (depth + 1) * decay_rate)
        if next_activation <= 0:
            continue

        # Batch: get all neighbors for current node
        neighbors = db.execute(
            "SELECT target_id FROM edges WHERE source_id = ?",
            (node_id,)
        ).fetchall()

        for (neighbor_id,) in neighbors:
            if neighbor_id in visited:
                activated[neighbor_id] = max(
                    activated.get(neighbor_id, 0), next_activation
                )
                continue
            visited.add(neighbor_id)
            activated[neighbor_id] = next_activation
            queue.append((neighbor_id, depth + 1))

    return activated
```

### Decay Function
Linear: `activation = max(0, 1.0 - hop * decay_rate)` with default decay_rate=0.25
- Hop 0: 1.00 (seed)
- Hop 1: 0.75
- Hop 2: 0.50
- Hop 3: 0.25
- Hop 4: 0.00 (natural cutoff)

### Score Combination
Use **max** for re-visited nodes. Closest meaningful connection wins.

### Performance
- Depth 1 (default): S+1 queries for S seed nodes. Trivial even at 100K nodes.
- Depth 3: Use batch queries per depth level to keep SQL round-trips to max_depth + 1.
- Index requirements: `CREATE INDEX idx_edges_source ON edges(source_id)` (essential)

### Optimization: Batch neighbor queries
```python
placeholders = ','.join('?' * len(current_level))
neighbors = db.execute(
    f"SELECT source_id, target_id FROM edges WHERE source_id IN ({placeholders})",
    current_level
).fetchall()
```

### Edge Schema Needs
- `source_id, target_id, reason, weight (default 1.0), created_at`
- Index on source_id, index on target_id
- Weight column lets edges modulate activation: activation * edge_weight

### Bidirectional Traversal
Store edges in both directions OR query `WHERE source_id = ? OR target_id = ?` (both columns indexed).

### Optional Enhancements
- Activation threshold (e.g., 0.1) to drop noise at deep hops
- Fan-out limit per node (--max-neighbors) to prevent hub domination
- Edge weight modulation: `next_activation * edge_weight`

---
# SOURCE: sqlite-vec-and-fts5.md
---

# sqlite-vec + FTS5 Feasibility

## Verdict: Fully feasible. Both confirmed working in Python.

## sqlite-vec

### Installation
```
pip install sqlite-vec
```

### Loading in Python
```python
import sqlite3
import sqlite_vec

db = sqlite3.connect("memory.db")
db.enable_load_extension(True)
sqlite_vec.load(db)
db.enable_load_extension(False)
```

### GOTCHA: macOS system Python
macOS system SQLite does NOT support extension loading. Fix: use Homebrew Python or pysqlite3 package.

### SQL Syntax
```sql
-- Create vector table
CREATE VIRTUAL TABLE vec_neurons USING vec0(
  neuron_id INTEGER PRIMARY KEY,
  embedding float[768]
);

-- Insert (blob format via Python)
INSERT INTO vec_neurons(neuron_id, embedding) VALUES (?, ?);
-- Vector as struct.pack(f'{768}f', *values)

-- KNN query
SELECT neuron_id, distance
FROM vec_neurons
WHERE embedding MATCH :query_vector AND k = 20
ORDER BY distance;
```

### Performance (768-dim)
- 1K vectors: trivial (<5ms)
- 100K vectors: ~75ms per query
- Storage: 100K vectors at 768-dim float32 = ~300 MB

### Critical: Two-step queries
sqlite-vec + JOINs cause hangs (known issue). Query vec table alone first, then JOIN results to main tables.

## FTS5

### Built into Python sqlite3 — zero setup needed

```sql
CREATE VIRTUAL TABLE neurons_fts USING fts5(
  content,
  tags,
  tokenize='porter unicode61'
);
```

### BM25 Scoring
```sql
SELECT rowid, bm25(neurons_fts, 10.0, 1.0) as score
FROM neurons_fts
WHERE neurons_fts MATCH 'search terms'
ORDER BY score;  -- ascending (raw scores are negative)
```

Raw BM25 scores are negative. Normalize: `|x| / (1 + |x|)` → [0, 1).

### Coexistence
FTS5 and sqlite-vec coexist in same database, no conflicts.

## Hybrid Fusion: RRF

Reciprocal Rank Fusion — uses rank positions, not raw scores. No normalization needed.

```python
def reciprocal_rank_fusion(fts_results, vec_results, k=60):
    scores = {}
    for rank, doc_id in enumerate(fts_results):
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
    for rank, (doc_id, _) in enumerate(vec_results):
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

k=60 is the standard. Used by Azure AI Search, Weaviate, etc.

---
# SOURCE: _findings.md
---

# Research Findings Summary — v1

## Key Takeaways That Affect Design

### 1. nomic-embed-text-v1.5 requires task prefixes (UPSTREAM IMPACT)
The model REQUIRES text prefixes for quality embeddings:
- `search_document: <text>` when indexing neurons
- `search_query: <text>` when searching
This must be handled transparently by the CLI — the caller should not need to know about prefixes.

### 2. Q8_0 quant is 140 MiB, not ~260 MB
Original estimate was for F16. Q8_0 has negligible quality loss (MSE 5.79e-06) at nearly half the size.

### 3. sqlite-vec + JOINs hang (CRITICAL)
Known issue: querying sqlite-vec virtual tables with JOINs causes indefinite hangs. Must use two-step pattern: query vec table alone first, then JOIN results to main tables.

### 4. macOS system Python can't load sqlite-vec
System SQLite doesn't support extension loading. Require Homebrew Python or pysqlite3.

### 5. Spreading activation: use application-side BFS, not recursive CTEs
SQLite recursive CTEs can't properly handle visited sets or score aggregation during traversal. ~30 lines of Python BFS is simpler, correct, and fast enough (sub-ms at depth 1).

### 6. BM25 scores are negative — need normalization
FTS5 bm25() returns negative scores. Normalize with `|x| / (1 + |x|)` to get [0, 1) range.

### 7. RRF is the right fusion approach
Reciprocal Rank Fusion uses rank positions, not raw scores. No score normalization needed between BM25 and vector. k=60 is standard. ~20 lines of Python.

### 8. FTS5 sync via triggers
QMD uses INSERT/UPDATE/DELETE triggers to keep FTS5 in sync with source tables. Proven pattern.

### 9. Batch embedding for search queries
When heavy search generates multiple query variants, batch them into one embed() call to avoid reloading the model.

### 10. No competing tool combines our feature set
Closest: Cog (spreading activation, cloud-only), Zep (graph, Neo4j), Engram (SQLite CLI, no graph). Our combination of graph + spreading activation + embedded SQLite + CLI noun-verb grammar + opaque storage is unique.

## Reusable Patterns from QMD
- Two-step vector query pattern
- BM25 normalization formula
- FTS5 trigger sync
- RRF fusion implementation
- Porter unicode61 tokenizer config

## What We Do NOT Need from QMD
- Smart chunking (our neurons are atomic facts, not documents)
- LLM query expansion (our light search is algorithmic only)
- Reranking pipeline (our heavy search uses Haiku differently — re-rank + query expansion, not cross-encoder)
- Content-addressable storage (our neurons are mutable, not content-hashed)
- MCP server (explicitly out of scope)

---
# SOURCE: decomposition.md
---

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

---
# SOURCE: upstream-feedback.md
---

# Upstream Feedback — v1

## Source: Stage 3 Research

### R-1: Task instruction prefixes required for nomic-embed-text-v1.5
**Layer:** Requirements (§8 Embedding)
**Finding:** The embedding model requires text prefixes (`search_document:` for indexing, `search_query:` for searching) for quality embeddings. Current requirements say "content text + tags concatenated" but don't mention prefixes.
**Impact:** The CLI must transparently prepend the correct prefix based on operation type (write vs search). This is a WHAT requirement — the embedding input format must include task-appropriate prefixes.
**Status:** Resolved — added to REQUIREMENTS.md §8.

### R-2: Model size is 140 MiB (Q8_0), not ~260 MB
**Layer:** Requirements (§8 Embedding)
**Finding:** The Q8_0 quantization is 140 MiB with negligible quality loss (MSE 5.79e-06). The ~260 MB estimate was for F16/F32.
**Impact:** Informational. The recommended quantization is Q8_0 unless precision is critical.
**Status:** Informational.

### R-3: sqlite-vec two-step query pattern required
**Layer:** Design constraint
**Finding:** sqlite-vec virtual tables with JOINs cause indefinite hangs (known issue). Must query vec table alone, then JOIN results separately.
**Impact:** All vector search code must follow the two-step pattern. This is a design constraint, not a requirement.
**Status:** Noted for decomposition.

### R-4: macOS system Python incompatibility
**Layer:** Design constraint
**Finding:** macOS system SQLite doesn't support extension loading. sqlite-vec requires Homebrew Python or pysqlite3.
**Impact:** Installation docs / init command must verify Python environment. May need to document prerequisite.
**Status:** Noted for decomposition.

### R-5: Spreading activation — application-side, not SQL
**Layer:** Design decision (replaces flagged HOW item #3 from clean requirements)
**Finding:** Recursive CTEs cannot properly handle visited sets or score aggregation. Application-side BFS is simpler, correct, and performant (~30 lines of Python).
**Impact:** Confirms the HOW flag was correct. Implementation uses Python BFS, not SQL.
**Status:** Noted for decomposition.

### R-6: BM25 score normalization needed for --explain output
**Layer:** Design constraint
**Finding:** FTS5 bm25() returns negative scores. For the --explain debug mode, scores need normalization: `|x| / (1 + |x|)` → [0, 1).
**Impact:** Affects search output formatting when --explain is used.
**Status:** Noted for decomposition.

### R-7: Edge weight modulation in spreading activation
**Layer:** Design consideration
**Finding:** Research suggests edges with a weight column (default 1.0) allow activation to be modulated per-edge. Hub nodes can be capped with --max-neighbors.
**Impact:** Edge schema may want a weight column. Not in current requirements.
**Status:** Resolved — added to REQUIREMENTS.md §2.2. Edge weight in v1.

### R-9: Project-scoped memory stores (Source: Stage 6 Wave A reflect gate)
**Layer:** Requirements (§7.2 Init & Config)
**Finding:** User wants per-project memory stores in addition to global. `memory init` = global (~/.memory/), `memory init --project` = project-scoped (.memory/ in cwd). Config resolution walks up from cwd looking for .memory/config.json, falls back to ~/.memory/config.json. Like .git/ discovery.
**Impact:** Config loading must implement ancestor-directory walk. `memory init` is a top-level command exception to noun-verb grammar. Each store is isolated (own DB, own config).
**Status:** Resolved — added to REQUIREMENTS.md §7.2.

### R-10: `memory init` as grammar exception (Source: Stage 6 Wave A reflect gate)
**Layer:** Requirements (§7.1 Grammar, §7.2 Init & Config)
**Finding:** `memory init` is a top-level command, not noun-verb. This is an intentional exception like `git init`. The #1 CLI Dispatch spec proposed `memory meta init` but user prefers bare `memory init`.
**Status:** Resolved — added to REQUIREMENTS.md §7.2.

### R-8: Development constraint — Haiku never for coding
**Layer:** Process
**Finding:** User-directed constraint. Haiku is only for runtime product features (conversation ingestion, search re-ranking). All coding uses Sonnet or Opus.
**Status:** Captured in CLAUDE.md and REQUIREMENTS.md §12.

---
# SPEC CLAIM PROTOCOL
---

1. Read `.planning/v1/spec-claims.md` — find your assigned spec.
2. Change `[ ]` to `[claimed]` for your spec.
3. Read your spec-tree preamble file (path listed in claims).
4. Write your spec to `.planning/v1/specs/<spec-name>.md`.
5. Derive from upstream inputs in this blob only.
6. Mark your spec `[done]` in the claims registry.
7. Report: spec written, key decisions, findings.
