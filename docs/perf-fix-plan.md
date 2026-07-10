---
type: reference
title: Query-path performance fix plan (ordered)
description: Ordered implementation plan for the top-5 LIGHT-search bottlenecks from performance-analysis.md — quick wins, then architecture, then scale-later. Each item = change · acceptance test · risk · owner role.
tags: [performance, search, latency, plan, embedding, sqlite-vec, bottlenecks]
timestamp: 2026-07-10
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

- STATUS: **SHIPPED** (2026-07-10, commit `903c462` = R4 true read-only search; see
  `CHANGELOG.md` Unreleased/Added "True read-only search (R4)"). All sub-fixes incl.
  NEW-1 (v010 FTS trigger scoped to `UPDATE OF content`) + NEW-2 (extension probe
  swapped off CREATE/DROP): search path now does ZERO persistent writes. Reds:
  `tests/search/test_r4_true_read_only_search.py` (6/6). Do not re-propose.
- TIER: quick win
- change:
  - two writes committed on every search read.
  - `_record_latency` INSERT + `conn.commit()` — `light_search_pipeline_orchestrator.py:686` (INSERT), `:692` (commit); called at `:262`.
  - access_count bump UPDATE — `search_result_hydration_and_envelope.py:120` (no own commit; rides the `_record_latency` commit on shared conn).
  - fix: make search read-only by default. Gate access-count UPDATE behind a flag OR batch (accumulate, flush on exit / every N). Sample `_record_latency` 1-in-N or drop per-call `commit()` → one commit max, not per-query fsync. Consider a separate writer connection so reads stay read-only.
  - **NEW-1 add-on (MANDATORY — write-on-read is ~20× worse than "2 writes")**: `trg_neurons_fts_update` = `AFTER UPDATE ON neurons` UNCONDITIONAL, not `AFTER UPDATE OF content` — `db/migrations/v001_baseline_all_tables_indexes_triggers.py:293-307`. The access-count bump (`search_result_hydration_and_envelope.py:119-123`) fires it PER hydrated neuron → FTS5 delete+reinsert of full content, each with a `group_concat` subquery over `neuron_tags` (trigger body `:296-305`). Real cost per search ≈ ~20 FTS index rewrites + ~40 subqueries, NOT "2 small writes". Source: `perf-second-look-findings.md:15-19`.
  - fix add-on: restrict trigger to `UPDATE OF content` OR move `access_count` off the `neurons` table. Without this, batching the UPDATE STILL rewrites FTS on every flush (`perf-second-look-findings.md:19`).
  - NEW-1 acceptance test: one search → trace-count FTS5 delete/reinsert on `neurons_fts` = 0 (was ~20). After trigger scoped to `UPDATE OF content`, a bare `access_count` bump fires 0 FTS rewrites (assert via `set_trace_callback` op count). Golden-set: FTS content still updates when `content` changes.
  - NEW-1 risk: dropping `access_count` from `neurons` (option B) touches salience read path (`salience_scoring_access_metrics`) — needs its own migration + read-site update; regression = salience reads a stale/absent column. Scoping trigger to `UPDATE OF content` (option A) is safer — verify no other trigger consumer relied on the unconditional fire.
  - NEW-1 owner: architect (trigger/schema change — option B is a column move + migration; option A mechanical but schema-touching).
- acceptance test:
  - read-only search does ZERO writes: run one search, assert 0 INSERT into `search_latency` and 0 UPDATE on `neurons` (query-count via `sqlite3` trace / `set_trace_callback`, or row-count diff on both tables before/after).
  - **NEW-2 correction (the "zero writes" test FAILS on open, not search)**: `load_sqlite_vec` runs `CREATE VIRTUAL TABLE _vec_test ... vec0` + `DROP TABLE` on EVERY open — `db/extension_loader_sqlite_vec.py:80-83` (was carried `:78 unverified` — corrected). Called per store per invocation from `cli/noun_handlers/db_connection_from_global_flags.py:54,108`; `verify_fts5` does the same `_fts5_test` create/drop at `:111-115`. So "search does ZERO writes" FAILS on the extension probe even after the search-path fix — read-only concurrency impossible while every open mutates `sqlite_master`. Source: `perf-second-look-findings.md:21-25`.
  - NEW-2 fix: replace probe-DDL with non-mutating checks — `SELECT vec_version()` for vec0, `pragma_module_list` (or `SELECT ... FROM pragma_module_list`) for fts5. UPDATED acceptance criterion: a full CLI invocation (open + search) does ZERO writes — 0 rows into `sqlite_master` (no `_vec_test`/`_fts5_test` create/drop), 0 INSERT `search_latency`, 0 UPDATE `neurons`, 0 FTS rewrite.
  - NEW-2 risk: `vec_version()`/`pragma_module_list` prove the extension loaded but NOT that vec0 virtual tables construct correctly — thinner smoke test; keep the DDL probe available behind a `--verify-deep` diagnostic path, off the hot open.
  - NEW-2 owner: coder (mechanical probe swap).
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

- STATUS: **SHIPPED** (2026-07-10, commit `8803a8c` = R1 daemon, ADR 0001; see
  `CHANGELOG.md` Unreleased/Added "Resident embedding daemon (R1 / ADR 0001)").
  Warm-GGUF daemon over unix socket warms the embed (~16ms) across CLI processes;
  inproc fallback. NOTE: full-CLI wall stays host-bound (Python spawn ~90ms + search
  ~230ms) — the daemon removes the model RELOAD, not process startup. Do not re-propose.
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

- STATUS: **SHIPPED** (2026-07-10, commit `8803a8c` = R1 daemon, folds into #3).
  One resident model copy = no per-process reload + no double-load under concurrency.
  See `CHANGELOG.md` R1 entry. Do not re-propose.
- TIER: architecture
- change:
  - p95 24916 ms, one run 25885 ms retrieval. Same root as #3: model load competes for RAM/disk; a 2nd concurrent `memory` proc reloads 139 MB again. Refs: `model_loader_lazy_singleton.py:108` + `extension_loader_sqlite_vec.py:80-83` (vec0 `_vec_test` create/drop per open — CORRECTED from `:78 unverified`, per `perf-second-look-findings.md:22`).
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

## Second-look amendments (NEW-3..NEW-5)

> Added from `perf-second-look-findings.md`. Do NOT reorder top5 (reviewer confirmed
> ranking directionally correct — `perf-second-look-findings.md:11`). These are
> scope expansions + co-suspects, not new rankings.

### NEW-3 — multi-store layering ~2× the whole pipeline (docs measured single-store)

- source: `perf-second-look-findings.md:27-30`
- change:
  - `neuron search` runs FULL `light_search` PER store — `cli/noun_handlers/neuron_noun_handler.py:435-441`: embed inference per store + `_record_latency` INSERT/commit per store + full-page hydration + access bumps + FTS trigger rewrites per store.
  - merge then truncates to `limit` (`:452-458`) → hydration + access-count writes SPENT on rows that get discarded.
  - live usage = LOCAL+GLOBAL layered (session-start ritual) → real wall ≈ 2× the single-store benchmark table.
  - fix: compute query embedding ONCE, reuse across stores (model singleton is shared; inference is not).
- acceptance test: 2-store (LOCAL+GLOBAL) search → `Llama` embed call count = 1 (was 2); assert per-store hydration/access-bump runs only on rows that survive the merge-truncate (no writes on discarded rows). Wall for 2-store ≤ 1.1× single-store (was ~2×).
- risk: shared embedding across stores is safe (same model/config), but if store configs ever diverge (different embed model per store) the shared vector is wrong — assert store embed-config identity before reuse, else fall back to per-store embed.
- owner role: coder (mechanical — hoist embed above the per-store loop; guard on config identity).

### NEW-4 — facet fast-lane: access bump never committed → silently rolled back

- STATUS: **SHIPPED** — measurement half via R2 (commit `00633bd`, facet lane records
  `search_latency`); read-only half via R4 (commit `903c462`, "True read-only search"):
  access_count opt-in default-off + latency side-channel writer → facet lane does ZERO
  writes, no uncommitted-txn rollback, WAL writer slot free. Both cite `CHANGELOG.md`.
  Do not re-propose.
- source: `perf-second-look-findings.md:32-36`
- change:
  - `_facet_fast_search` returns at `light_search_pipeline_orchestrator.py:242→338-347` BEFORE reaching `_record_latency` → hydration's UPDATE (`:119`) sits in an open implicit txn; search verb never commits; `close()` ROLLS BACK.
  - effects: (a) salience access data SILENTLY LOST on the facet fast lane; (b) open write txn holds the WAL writer slot until process exit — WORSE for concurrency than the committed write.
  - side effect: `search_latency` never records facet-path runs → benchmark p50/p95 in `performance-analysis.md` EXCLUDE the fast lane entirely.
  - fix: after the read-only refactor (item #1) the facet lane should do zero writes too (consistent). If access data is wanted, route it through the same batched/flagged writer — never leave an uncommitted UPDATE in an open txn.
- acceptance test: facet fast-lane search → 0 uncommitted write txn at `close()` (assert no rollback of pending changes; WAL writer slot free immediately after return). After item #1 fix: facet lane does ZERO writes, symmetric with main lane. Benchmark: facet runs now appear in `search_latency` (or, if search is fully read-only, are timed by an out-of-band probe) — no lane silently excluded from p50/p95.
- risk: making facet lane emit latency rows re-introduces a write on the fast path — must ride the SAME sampling/batch gate as item #1, not a raw per-call commit. Removing the access bump entirely = salience never sees facet-lane hits (acceptable if main lane also stops bumping; inconsistent if not).
- owner role: architect (transaction-boundary + measurement-coverage decision; couples to item #1's read-only contract).

### NEW-5 — tag-affinity candidate-set explosion (co-suspect for flat ~30ms scoring)

- source: `perf-second-look-findings.md:38-41`
- change:
  - `_discover_tag_neighbors` pulls EVERY neuron sharing ANY seed tag — `search/tag_affinity_scoring_shared_tags.py:284-288`; depth-2 repeats over hop1 tags (`:370-374`); O(hop1×hop2) Python double loop (`:401-413`).
  - one common seed tag (`hub`, `person`, `system-rule`) drags a large fraction of the corpus into candidates → inflates temporal + salience IN-queries, final sort, and the double loop.
  - docs attribute flat ~30ms scoring to BFS PRAGMA alone — UNPROVEN; `scoring_ms` has no sub-timers.
  - fix: add a tag-affinity SUB-TIMER (isolate its share of scoring_ms) + a per-tag row cap so one hub tag can't pull the whole corpus.
- acceptance test: seed a query with a high-frequency tag (`hub`) → tag-affinity sub-timer reported separately in `scoring_ms` breakdown; candidate count from `_discover_tag_neighbors` ≤ per-tag cap (was ~corpus fraction). Golden-set: top-K result identity preserved when cap ≥ current candidate count (cap only bites on pathological tags).
- risk: a per-tag row cap trades recall for speed — a capped common tag may drop a relevant neighbor; set cap high enough that normal tags are unaffected, gate on golden-set recall@K before shipping the cap. Sub-timer alone = zero risk (measurement only) — land it FIRST to prove the suspect before capping.
- owner role: architect (candidate-set/recall tradeoff + measurement design); sub-timer instrumentation sub-task = coder.

## Minor corrections

Folded from `perf-second-look-findings.md:43-49`. Notes/flags, not tasks.

- Seed count: BM25 cap 100 + vector cap 100 → RRF union ≤200 seeds, NOT "≤100" (`perf-second-look-findings.md:44`).
- Vector KNN entry: `retrieve_vectors` at `vector_retrieval_two_step_knn.py:44` — item #5's `:88` is the DIM GUARD, not the path entry (`perf-second-look-findings.md:45`). (Item #5 body left intact to preserve structure; treat `:44` as the corrected entry.)
- Archived neurons keep occupying vec0 KNN slots — filtered AFTER KNN (`vector_retrieval_two_step_knn.py:228-232`); k=100 slots wasted as archive grows (`perf-second-look-findings.md:46`). Scale-later flag alongside vec0 (item #5).
- `search_latency` has no pruning → unbounded growth (small rows; note only) (`perf-second-look-findings.md:47`).
- Fuzzy fallback loads ALL neurons + tags + attrs into Python + Levenshtein each — `fuzzy_fallback_levenshtein.py:38-47` — zero-result path ONLY, but full-table Python scan; scale-later flag alongside vec0 (`perf-second-look-findings.md:48`).
- (hygiene, not perf) `except Exception` at orchestrator `:269-279` hides pipeline errors as bare exit 2, no message (`perf-second-look-findings.md:49`).

## Sequencing summary

| Order | Item | path:line | Tier | Owner role | Status |
|---|---|---|---|---|---|
| 1 | Write-on-read: access_count UPDATE + latency INSERT/commit | orchestrator `:686`/`:692`; hydration `:120` | quick win | coder | ✅ SHIPPED `903c462` (R4) |
| 2 | BFS PRAGMA-per-node + N+1 edge queries | bfs `:321`/`:287`/`:295`/`:302` | quick win | coder | ⬜ pending |
| 3 | Embedding model reloaded per process | model_loader `:35`/`:108` | architecture | architect | ✅ SHIPPED `8803a8c` (R1) |
| 4 | Cold-load / contention tail (same root as #3) | model_loader `:108`; ext_loader `:80-83` (corrected) | architecture | architect (folds into #3) | ✅ SHIPPED `8803a8c` (R1) |
| 5 | vec0 KNN linear scan, no ANN | vector_knn `:117`/`:88` | scale-later | architect (deferred) | ⬜ deferred (see 10-known-gaps D1) |

## Notes

- Do #1 + #2 first partly to CLEAN the measurement surface: quiet the write path + de-noise `search_latency` BEFORE benchmarking the #3 daemon, so before/after is honest.
- #3 and #4 share one root — build ONE daemon, it closes both. Don't scope as two builds.
- #5 is a flagged time bomb, not a task. No work until corpus growth trips the trigger.
- Uncertainty flags: RESOLVED — `extension_loader_sqlite_vec.py:78 (unverified)` corrected to `:80-83` (verified in second look, `perf-second-look-findings.md:22`). All top5 `path:line` spot-checked green (`perf-second-look-findings.md:50`).
- Second-look additions: NEW-1 (FTS trigger amplifies write-on-read ~20×) + NEW-2 (probe-DDL breaks "zero writes") folded into item #1; NEW-3/4/5 + Minor corrections in the "Second-look amendments" section. Top5 order unchanged per reviewer (`perf-second-look-findings.md:11`).
