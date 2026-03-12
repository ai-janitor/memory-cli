# Session State — memory-cli v1

**Last updated:** 2026-03-11
**Stage:** 6 (Specifications) — COMPLETE
**Iteration status:** CLOSED — ready for v1-endpoint tag

## What happened in v1

1. **Stage 0 (Orient)** — found project, identified as v1
2. **Stage 1 (Raw)** — REQUIREMENTS-RAW.md verified, snapshot taken
3. **Stage 2 (Clean)** — 13-section clean requirements derived, user approved
4. **Stage 3 (Research)** — 5 research areas: QMD reference, llama-cpp-python, sqlite-vec/FTS5, spreading activation, skills/prior art. All feasibility confirmed.
5. **Stage 4 (Decompose)** — 13 spec units identified across 7 build waves, boundary map with 22 edges
6. **Stage 5 (Spec Tree)** — 5 categories, 13 spec files with preambles
7. **Stage 6 (Specs)** — All 13 specs written. Wave A sequential with reflect gate, Waves B-G parallel. 10 open findings recorded in upstream-feedback.md.

## Key decisions made in v1

- Python + llama-cpp-python + SQLite + sqlite-vec + FTS5
- nomic-embed-text-v1.5 Q8_0 (140 MiB, 768 dims)
- Task prefixes required (search_document: / search_query:)
- RRF fusion for hybrid search (k=60)
- Application-side BFS for spreading activation (not SQL CTEs)
- Two-step vector query pattern (sqlite-vec + JOINs hang)
- Project-scoped memory stores (.memory/ in cwd, like .git/)
- `memory init` as top-level grammar exception
- Edge weights (default 1.0) for activation modulation
- Haiku only for runtime features, never for coding

## Deferred to v2

- Test contract extraction
- Cross-spec contract reconciliation
- Scaffold (Stage 7)
- Implementation (Stage 8)
- Verify (Stage 9)
- 10 open findings (S-1 through S-10 in upstream-feedback.md)

## Artifacts on disk

```
.planning/v1/
├── SESSION-STATE.md
├── raw-snapshot.md
├── clean-unbiased.md
├── clean-requirements.md
├── raw-to-clean-trace.md
├── decomposition.md
├── boundary-dependency-map.md
├── upstream-feedback.md
├── spec-context.md
├── spec-claims.md
├── stage-clean-checklist.md
├── stage-research-checklist.md
├── stage-decompose-checklist.md
├── stage-spec-tree-checklist.md
├── stage-specs-checklist.md
├── research/
│   ├── _findings.md
│   ├── llama-cpp-python-embedding.md
│   ├── qmd-reference-architecture.md
│   ├── skills-and-prior-art.md
│   ├── spreading-activation-algorithm.md
│   └── sqlite-vec-and-fts5.md
├── spec-tree/
│   ├── _overview.md
│   ├── foundation/ (3 files)
│   ├── registries-and-embedding/ (3 files)
│   ├── neuron-and-graph/ (2 files)
│   ├── search-and-retrieval/ (3 files)
│   └── ingestion-and-io/ (2 files)
└── specs/ (13 files)
```
