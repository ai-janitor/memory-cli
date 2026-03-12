# Session State — memory-cli v2

**Last updated:** 2026-03-11
**Stage:** 7 (Scaffold) — Tree approved, content fan-out next
**Next:** Generate scaffold context blob → prompt assembly → content agents fill files with headers + pseudo-logic

## Context for fresh session

This is a Python CLI project for graph-based AI agent memory. 13 specs, all written. Scaffold tree (148 files) approved.

### Key files to read on resume
1. This file
2. `/Users/hung/projects/memory-cli/CLAUDE.md` — project rules
3. `/Users/hung/projects/memory-cli/REQUIREMENTS.md` — clean requirements
4. `/Users/hung/projects/memory-cli/.planning/v1/decomposition.md` — 13 spec units, 7 waves, dependency graph
5. `/Users/hung/projects/memory-cli/.planning/v1/upstream-feedback.md` — all findings (resolved)
6. All specs at `/Users/hung/projects/memory-cli/.planning/v1/specs/*.md` (13 files)

### What's done
- v1 closed, tagged `v1-endpoint` (git tag)
- Stages 0-6 complete: raw → clean → research → decompose → spec tree → specs
- All 10 open findings from v1 resolved (S-1 through S-10)
- Stage 7b: Scaffold tree created (148 files: 65 source + 83 tests + 3 root)
- Tree approved by user

### What's next
- Stage 7c: Coordinator setup — generate scaffold context blob, claim registry, prompt assembly
- Stage 7d: Content agents fill empty files with comment headers + pseudo-logic (per-spec, wave by wave)
- Stage 7e: Reflect gates after each wave
- Stage 7f: Convergence gate
- Stage 7g: Cross-reference reconciliation
- Then: Stage 8 (Implement), Stage 9 (Verify)

### Resolved findings quick reference
- S-1: Block tag/attr removal when in use, show ref count
- S-2: Add `neuron restore` command
- S-3: Temporal decay: `e^(-λt)`, half-life default 30 days
- S-4: Tag filtering post-activation confirmed
- S-5: Bidirectional edge traversal
- S-6: Star topology for capture context
- S-7: Session dedup via session_id + --force
- S-8: Vector export opt-in (--include-vectors)
- S-9: haiku.model in config (default: claude-haiku-4-5-20251001)
- S-10: warnings array in JSON envelope

### Development constraints
- **Never use Haiku for coding.** Sonnet or Opus only for implementation.
- Haiku is only for runtime product features (ingestion extraction, search re-ranking)
- Filesystem-as-DB naming: file/folder names describe contents
- No code without scaffolding: headers + pseudo-logic first, then code between them
- Comment headers and pseudo-logic are PERMANENT

### Tech stack
- Python + llama-cpp-python + SQLite + sqlite-vec + FTS5
- nomic-embed-text-v1.5 Q8_0 (140 MiB, 768 dims)
- Task prefixes: search_document: / search_query:
- RRF fusion k=60, BFS spreading activation, two-step vector queries
- Project-scoped stores (.memory/) + global (~/.memory/)

### Build waves (for content fan-out ordering)
```
Wave A: #1 CLI Dispatch, #2 Config
Wave B: #3 Schema & Migrations
Wave C: #4 Tags, #5 Embedding, #13 Metadata
Wave D: #6 Neuron CRUD
Wave E: #7 Edges, #10 Traversal, #12 Export/Import
Wave F: #8 Light Search
Wave G: #9 Heavy Search, #11 Ingestion
```

### Scaffold tree ownership (spec → files)
Run `find src/memory_cli -name '*.py' | sort` to see all source files.
Each package maps to a spec: cli/ → #1, config/ → #2, db/ → #3, registries/ → #4, embedding/ → #5, neuron/ → #6, edge/ → #7, search/ → #8, search/heavy/ → #9, traversal/ → #10, ingestion/ → #11, export_import/ → #12, integrity/ → #13.
