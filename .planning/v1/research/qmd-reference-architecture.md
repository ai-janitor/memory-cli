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
