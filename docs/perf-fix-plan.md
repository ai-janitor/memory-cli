---
type: reference
title: Query-path performance fix plan (ordered)
description: Ordered implementation plan for the top-5 LIGHT-search bottlenecks from performance-analysis.md — quick wins, then architecture, then scale-later. Each item = change · acceptance test · risk · owner role.
tags: [performance, search, latency, plan, embedding, sqlite-vec, bottlenecks]
timestamp: 2026-07-09
---

# Query-path performance fix plan — ordered

> PLAN ONLY. No code changed in this task. Source of truth for the ranking +
> fix proposals: `docs/performance-analysis.md`. This doc = the ORDERED layer.
> All `path:line` verified against source unless flagged `(unverified)`.

## Overview

Sequence = commander-set, not raw impact-first. Rationale: land cheap
read-path hygiene FIRST (write-on-read, BFS probing) — low risk, ship now, no
new infra, unblocks reader concurrency. THEN the big architecture win (resident
embedding daemon — 98% of latency, but a new process + protocol + lifecycle).
THEN scale-later (vec0 ANN) — cheap at 769 neurons, deferred until N ≫ 1k.
Quick wins buy immediate reader-concurrency + de-noise the latency table so the
daemon's before/after is measured against a clean baseline.

## Ordered plan

### 1 — Write-on-read: access-count UPDATE + latency INSERT (QUICK WIN)

- TIER: quick win
- change:
  - two writes committed on every search read.
  - `_record_latency` INSERT + `conn.commit()` — `light_search_pipeline_orchestrator.py:686` (INSERT), `:692` (commit); called at `:262`.
  - access_count bump UPDATE — `search_result_hydration_and_envelope.py:120` (no own commit; rides the `_record_latency` commit on shared conn).
  - fix: make search read-only by default. Gate access-count UPDATE behind a flag OR batch (accumulate, flush on exit / every N). Sample `_record_latency` 1-in-N or drop per-call `commit()` → one commit max, not per-query fsync. Consider a separate writer connection so reads stay read-only.
- acceptance test:
  - read-only search does ZERO writes: run one search, assert 0 INSERT into `search_latency` and 0 UPDATE on `neurons` (query-count via `sqlite3` trace / `set_trace_callback`, or row-count diff on both tables before/after).
  - if sampled: N searches → ≤ ceil(N/sample) latency rows.
  - concurrency: 2+ parallel `memory neuron search` procs → no `database is locked` / no WAL-writer stall.
- risk:
  - correctness/data: access_count + last_accessed_at stop advancing every read → salience scoring (`salience_scoring_access_metrics`) drifts. Batching-on-exit can LOSE the last window if process is killed. Sampling latency undercounts the cold tail — the exact thing we watch.
  - latency: negligible upside per-call (~ms); real win is reader parallelism + smaller WAL.
- owner role: coder (mechanical — flag + batch/sample, no new subsystem).

### 2 — BFS schema probing + N+1 edge queries (QUICK WIN)

- TIER: quick win
- change:
  - `_has_confidence_column` runs `PRAGMA table_info(edges)` on EVERY `_get_neighbors` call — `spreading_activation_bfs_linear_decay.py:321` (PRAGMA), called from `:287` inside `_get_neighbors` `:265`. Comment `:313-319` deliberately un-caches it (id(conn) reuse hazard).
  - neighbors fetched one node at a time: 2 SELECTs per visited node — outgoing `:295`, incoming `:302`.
  - fix: resolve confidence-flag ONCE per pipeline — pass it into `spread()`/`_bfs_activate`/`_get_neighbors`, or cache per-connection keyed by schema-version (NOT id(conn)). Batch the frontier: one recursive CTE, or a single `source_id IN (...) OR target_id IN (...)` per BFS depth level instead of per node.
- acceptance test:
  - `PRAGMA table_info(edges)` executes ≤1 per `light_search()` call (trace callback count).
  - edge-query count for a fan-out over K frontier nodes = O(depth), not O(K) — assert query count constant as frontier grows (compare fan-out-depth 1 vs 2 vs 3).
  - result-set identity: fan-out neuron set + activation scores unchanged vs current impl (golden-set diff on a fixed seed query).
- risk:
  - correctness: batched frontier must preserve per-node BFS depth + max-activation-wins visited logic (`:245`) — a CTE that flattens hops can misassign `hop_distance`/activation. Confidence-flag cached wrong across a mid-process schema migration → stale column expr (the exact bug the comment guards).
  - latency: main payoff is fewer round-trips; grows with fan-out-depth + corpus.
- owner role: coder (mechanical, but CTE rewrite needs care — golden-set gate mandatory).

### 3 — Embedding model reloaded every CLI process (ARCHITECTURE)

- TIER: architecture
- change:
  - "lazy singleton" is module-level (`model_loader_lazy_singleton.py:35-36`) → caches WITHIN one process only. Each `memory neuron search` is a fresh process → full 139 MB GGUF reload at `:108`. Retrieval = 98% of latency; p50 ~264 ms, cold p95 ~24.9 s. `(benchmarked)`
  - fix: resident embedding daemon / socket server holding the model warm across CLI calls. CLI sends query text → gets vector back. Alt / interim: `mmap`+`mlock` the GGUF, lean on OS page cache (warm runs already ~12-25 ms — prove, then pin). Fallback lane: short keyword queries skip embed → BM25-only path like facet fast-path does today.
- acceptance test:
  - warm floor: N searches in ONE process (REPL / test harness bypassing per-call spawn) → 2nd+ search reuses model, wall < 50 ms (target ~12-30 ms). Assert model constructed exactly once (`Llama(...)` call count = 1 across N embeds).
  - daemon: cold client `memory neuron search` after daemon warm → wall < 100 ms; kill daemon → graceful fallback (in-process load or clear error, not crash).
  - concurrency: 2 clients hit daemon → ONE resident 139 MB copy (RSS check), no double-load.
- risk:
  - correctness: daemon = new failure surface (stale socket, version skew between daemon model + client config, auth/permissions on the socket). Must degrade to in-process load, never hang.
  - data: none (read-only vector service).
  - latency/ops: daemon lifecycle (start/stop/reap, mem residency) is real ops surface; mlock can pin 139 MB RAM permanently.
- owner role: architect (daemon = new process + protocol + lifecycle + fallback contract). mlock/BM25-fallback interim sub-tasks can go to coder.

### 4 — Cold-load / contention tail (ARCHITECTURE, same root as #3)

- TIER: architecture
- change:
  - p95 24916 ms, one run 25885 ms retrieval. Same root as #3: model load competes for RAM/disk; a 2nd concurrent `memory` proc reloads 139 MB again. Refs: `model_loader_lazy_singleton.py:108` + `extension_loader_sqlite_vec.py:78` (vec0 DDL per open) `(line unverified — from analysis)`.
  - fix: the #3 daemon fixes both (one resident copy, no per-process reload, no double-load under concurrency). Until then: surface the `memory meta health` p95 warning to users.
- acceptance test:
  - with daemon up: p95 over 20 back-to-back cold-client searches < 500 ms (vs 24.9 s today). Measure via `search_latency` after quick-win #1 de-noises it.
  - 2 concurrent clients → combined RSS shows single model copy, no 25 s spike in either.
- risk:
  - same as #3. Additionally: if daemon OOMs / evicted, tail returns — need health probe + auto-restart.
- owner role: architect (folded into #3 daemon; not a separate build).

### 5 — vec0 KNN linear scan, no ANN (SCALE-LATER)

- TIER: scale-later
- change:
  - `vector_retrieval_two_step_knn.py` — `_query_vec0_standalone` at `:117`; two-step KNN path entry `:88`. sqlite-vec `vec0` has no ANN index → KNN scans all N vectors × 768 dims per query. Plus a 768-float `struct.pack` per query.
  - fix (defer until N ≫ 1k): metadata pre-filter (project/type) before KNN, or partitioned vec0 tables, or an ANN-capable vector store. Cache the packed query blob (already have it from embed).
- acceptance test:
  - synthetic 10k / 100k vector store → time stage-3 (vector KNN) alone; confirm it grows O(N) and crosses the ~500 ms line, justifying ANN.
  - after pre-filter: same top-K recall on a golden query set vs full scan (recall@K unchanged), with lower scan count.
- risk:
  - correctness: pre-filter / ANN trades exactness for speed → recall regression on top-K. Golden-set recall gate required before switching.
  - now: NONE shipped — cheap at 769 neurons (~ms). Premature ANN adds complexity for zero current gain.
- owner role: architect (storage/index choice at scale) — but NOT NOW. Track corpus growth; trigger when N ≫ 1k.

## Sequencing summary

| Order | Item | path:line | Tier | Owner role |
|---|---|---|---|---|
| 1 | Write-on-read: access_count UPDATE + latency INSERT/commit | orchestrator `:686`/`:692`; hydration `:120` | quick win | coder |
| 2 | BFS PRAGMA-per-node + N+1 edge queries | bfs `:321`/`:287`/`:295`/`:302` | quick win | coder |
| 3 | Embedding model reloaded per process | model_loader `:35`/`:108` | architecture | architect |
| 4 | Cold-load / contention tail (same root as #3) | model_loader `:108`; ext_loader `:78` (unverified) | architecture | architect (folds into #3) |
| 5 | vec0 KNN linear scan, no ANN | vector_knn `:117`/`:88` | scale-later | architect (deferred) |

## Notes

- Do #1 + #2 first partly to CLEAN the measurement surface: quiet the write path + de-noise `search_latency` BEFORE benchmarking the #3 daemon, so before/after is honest.
- #3 and #4 share one root — build ONE daemon, it closes both. Don't scope as two builds.
- #5 is a flagged time bomb, not a task. No work until corpus growth trips the trigger.
- Uncertainty flags: `extension_loader_sqlite_vec.py:78` line `(unverified)` — carried from analysis, not re-read this pass. All other `path:line` verified against source.
