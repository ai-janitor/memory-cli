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
