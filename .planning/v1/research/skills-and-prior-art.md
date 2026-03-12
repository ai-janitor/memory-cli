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
