# Raw-to-Clean Traceability — v1

Every item in REQUIREMENTS-RAW.md mapped to its clean requirement or marked out-of-scope.

## Raw Section → Clean Section

| Raw Item | Clean Ref | Status |
|----------|-----------|--------|
| What it is — CLI tool | §1 Product Definition | traced |
| AI never sees storage | §2 Storage | traced |
| Storage is opaque | §2 Storage | traced |
| Like neurons | §2.1 Neurons | traced |
| Connections captured not inferred | §2.3 Capture Context | traced |
| No LLM at light search | §4.1 Light Search | traced |
| Haiku at ingestion/heavy search | §3.2, §4.2 | traced |
| Manual quick capture | §3.1 | traced |
| Auto-tags (timestamp, project) | §3.1 | traced |
| --link flag | §3.1, §3.3 | traced |
| Conversation ingestion | §3.2 | traced |
| Haiku extracts entities | §3.2 | traced |
| Write-and-wire | §3.3 | traced |
| Graph grows/re-wires | §3.3 | traced |
| Nodes = facts/entities/concepts | §2.1 Neurons | traced |
| Edges with REASON | §2.2 Edges | traced |
| Capture context first-class | §2.3 | traced |
| Time series + gotos | §4.4 Traversal Modes | traced |
| SQLite, opaque, not browsable | §2 Storage | traced |
| Embeddings in same DB | §8 Embedding | traced |
| BM25/FTS5 in same DB | §4.1 Light Search | traced |
| Single file backup | §2 Storage | traced |
| Storage vs embedding separation | §8 Embedding | traced |
| Tags in embedding input | §8 Embedding, §5 Tags | traced |
| Embedding decoupled from storage | §8 Embedding | traced |
| llama-cpp-python in-process | §8 Embedding | **HOW** — moved to design |
| Model loads once per invocation | §8 Embedding | traced (behavioral) |
| nomic-embed-text-v1.5 | §8 Embedding | traced (constraint) |
| Batch re-embed (blank/stale) | §8 Embedding | traced |
| BM25 keyword matching | §4.1 | traced |
| Vector similarity | §4.1 | traced |
| Graph traversal / spreading activation | §4.1, §11 | traced |
| Tag filtering AND/OR | §4.1, §5 | traced |
| Temporal decay | §4.1 | traced |
| Haiku re-ranks | §4.2 | traced |
| Query expansion | §4.2 | traced |
| Match, fan out, show why | §4.3 | traced |
| Progressive disclosure | §4.3 | traced |
| Tags as context descriptors | §5 | traced |
| Tag registry (enum, integer IDs) | §5 | traced |
| Lowercase normalization | §5 | traced |
| Tag by name or ID | §5 | traced |
| Byte-efficient timestamps | §5, §9 | traced |
| Attribute registry | §6 | traced |
| CLI grammar noun-verb | §7.1 | traced |
| Nouns: neuron, tag, attr, edge, meta, batch | §7.1 | traced |
| memory init | §7.2 | traced |
| Config at ~/.memory/config.json | §7.2 | traced |
| Config contents (db_path, llama.*, defaults.*) | §7.2 | **HOW** — config structure is design |
| --config and --db overrides | §7.2 | traced |
| Help per noun | §7.3 | traced |
| Output format json/text | §7.4 | traced |
| Exit codes 0/1/2 | §7.4 | traced |
| Pagination --limit --offset | §4.3 | traced |
| --explain debug mode | §4.3 | traced |
| Export by tags or all | §7.5 | traced |
| Import with schema enforcement | §7.5 | traced |
| --validate-only | §7.5 | traced |
| DB schema migrations | §9 | traced |
| Config/DB drift detection | §9 | traced |
| Conflicting memories — recency wins | §10 | traced |
| Circular references allowed | §10 | traced |
| Embedding down → BM25 fallback | §10 | traced |
| No empty tags | §10, §5 | traced |
| Fan-out depth configurable | §4.1, §11 | traced |
| Concurrent access — WAL mode | §10 | traced |
| Sensitive data — out of scope | §10, §12 | traced |
| Model change → stale vectors | §9 | traced |
| Spreading activation | §11 | traced |
| Linear decay default | §11 | traced |
| Recursive CTEs in SQLite | §11 | **HOW** — moved to design |
| Sharding — future, don't preclude | §12 | traced |
| All command examples | §7 CLI Interface | traced |
| neuron archive command | §7 CLI Interface | traced |
| edge remove command | §7 CLI Interface | traced |
| batch ingest (session JSONL) | §3.2, §7 | traced |

## HOW Contamination Flagged (3 items moved to design)

1. **llama-cpp-python binding** — this is an implementation choice. Clean requirement: "embedding model runs in-process, no external service dependency"
2. **Config JSON structure** (llama.model_path, llama.n_gpu_layers, etc.) — this is schema design. Clean requirement: "config file stores all settings including embedding model configuration"
3. **Recursive CTEs in SQLite** — this is an implementation technique. Clean requirement: "graph traversal supports spreading activation with configurable depth and decay"

## User-Directed Additions (not from raw, from user instruction)

| Item | Clean Ref | Source |
|------|-----------|--------|
| Never use Haiku for coding/implementation | §12 Development Constraints | User instruction 2026-03-11 |
| All coding uses Sonnet or Opus | §12 Development Constraints | User instruction 2026-03-11 |
| Haiku only for runtime product features | §12 Development Constraints | User instruction 2026-03-11 |

## Out of Scope (explicitly)
- Encryption / sensitive data handling
- Complex boolean tag grouping syntax
- Multi-DB / sharding (design must not preclude)
- MCP server
- LLM synthesis in output
- Human-browsable storage
