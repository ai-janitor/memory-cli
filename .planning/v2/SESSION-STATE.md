# Session State — memory-cli v2

**Last updated:** 2026-03-12
**Stage:** 8 COMPLETE (Implement) — All 7 waves done. 1324 tests passing.
**Next:** Stage 9 (Verify — run tests, integration checks)

## Context for fresh session

This is a Python CLI project for graph-based AI agent memory. 13 specs, all written. Scaffold tree (181 files) with content: 95 source + 86 test files, all filled with comment headers + pseudo-logic. 30,606 total lines. Zero empty files. pyproject.toml written.

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
- Stage 7b: Scaffold tree created (181 files: 95 source + 86 tests)
- Tree approved by user
- **Stage 7c-7d: Content fan-out COMPLETE** — all files filled across 7 waves:
  - Wave A: CLI Dispatch (#1, 21 files) + Config (#2, 10 files) ✓
  - Wave B: Schema & Migrations (#3, 11 files) ✓
  - Wave C: Tag/Attr Registries (#4, 10 files) + Embedding (#5, 18 files) + Metadata/Integrity (#13, 14 files) ✓
  - Wave D: Neuron CRUD (#6, 16 files) ✓
  - Wave E: Edges (#7, 10 files) + Traversal (#10, 6 files) + Export/Import (#12, 12 files) ✓
  - Wave F: Light Search (#8, 22 files) ✓
  - Wave G: Heavy Search (#9, 12 files) + Ingestion (#11, 16 files) ✓
- Root files: pyproject.toml, src/memory_cli/__init__.py, tests/__init__.py, tests/conftest.py ✓
- **Stage 7e: Reflect gates COMPLETE** — 5 parallel agents spot-checked all 7 waves:
  - Wave A: 8 findings fixed (`.exit_code`→`.status`, wrong import path, incomplete pseudo-logic)
  - Wave B: 1 finding fixed (`run_migrations`→`run_pending_migrations` in __init__.py)
  - Wave C: PASS (clean)
  - Waves D+E: 3 findings fixed (neuron_id type `str`→`int`, `edge_type`→`reason`, embedding OperationType.INDEX)
  - Waves F+G: PASS (clean)

- **Stage 7f: Convergence gate COMPLETE** — 7 cross-boundary checks:
  - CLI→Neuron: PASS
  - Neuron→Embedding: fixed `write_vector(neuron_id: str→int)`, `write_vectors_batch` same
  - Neuron→Registry: PASS
  - Neuron→Edge: PASS
  - Search→Embedding: PASS
  - Search→DB: fixed vec0 table name `neuron_embeddings`→`neurons_vec` (matches schema)
  - CLI→Config→DB: PASS

- **Stage 7g: Cross-reference reconciliation COMPLETE** — final sweep:
  - Fixed `neuron_id: str→int` in conflict_handler_skip_overwrite_error.py
  - Fixed vec0 table name `neuron_embeddings`→`neurons_vec` in vector_retrieval_two_step_knn.py
  - Fixed `write_vectors_batch` neuron_id type str→int
  - Verified no remaining UUID/str neuron_id mismatches across all source files

### What's next
- Stage 8: Implement — fill code between permanent comment headers, wave by wave
- Stage 9: Verify — run tests, integration checks

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

### Scaffold tree ownership (spec → files)
Run `find src/memory_cli -name '*.py' | sort` to see all source files.
Each package maps to a spec: cli/ → #1, config/ → #2, db/ → #3, registries/ → #4, embedding/ → #5, neuron/ → #6, edge/ → #7, search/ → #8, search/heavy/ → #9, traversal/ → #10, ingestion/ → #11, export_import/ → #12, integrity/ → #13.
