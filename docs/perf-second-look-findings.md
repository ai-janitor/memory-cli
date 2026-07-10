---
type: reference
title: Perf second-look — findings beyond the claimed top5
description: Independent verification of perf-fix-plan.md / performance-analysis.md against live source. New findings ranked, line refs corrected. Reviewer = yoda (recon). Docs-only, no code edits.
tags: [performance, search, review, second-look]
timestamp: 2026-07-09
---

# Perf second-look — findings beyond top5

Verdict on claimed top5: ranking directionally correct. #1/#2 (model load) = dominant, benchmarked, verified. No reorder needed. But #3 (write-on-read) is UNDERSCOPED — see NEW-1/NEW-2/NEW-4 — and the docs analyzed single-store only (NEW-3).

## New findings (ranked)

### NEW-1 — FTS5 update trigger amplifies write-on-read ~20×
- `trg_neurons_fts_update` = `AFTER UPDATE ON neurons`, UNCONDITIONAL — not `AFTER UPDATE OF content` — `db/migrations/v001_baseline_all_tables_indexes_triggers.py:293-307`.
- Access-count bump (`search_result_hydration_and_envelope.py:119-123`) fires it per hydrated neuron: FTS5 delete + reinsert of full content, EACH with a `group_concat` subquery over `neuron_tags` (trigger body :296-305).
- Per search: up to ~20 FTS index rewrites + 40 subqueries, not "2 small writes" as top5 #3 states.
- Fix add-on for plan #1: restrict trigger to `UPDATE OF content` (or move access_count off the neurons table). Without this, batching the UPDATE still rewrites FTS on every flush.

### NEW-2 — every CLI command WRITES to the DB via extension loader
- `load_sqlite_vec` runs `CREATE VIRTUAL TABLE _vec_test ... vec0` + `DROP TABLE` on every open — `db/extension_loader_sqlite_vec.py:80-83` (plan carried `:78 unverified` — actual :80-83).
- Called per store per invocation from `cli/noun_handlers/db_connection_from_global_flags.py:54,108`.
- `verify_fts5` does the same `_fts5_test` create/drop (:111-115) where `load_and_verify_extensions` is used.
- Consequence: plan #1 acceptance test "search does ZERO writes" FAILS on this even after the search-path fix. Read-only concurrency is impossible while every open mutates sqlite_master. Replace probe-DDL with `SELECT vec_version()` / `pragma_module_list` check.

### NEW-3 — multi-store layering doubles the whole pipeline; docs measured single-store
- `neuron search` runs FULL `light_search` per store — `cli/noun_handlers/neuron_noun_handler.py:435-441`: embed inference per store, `_record_latency` INSERT+commit per store, full-page hydration + access bumps + FTS trigger rewrites per store.
- Merge then truncates to `limit` (:452-458) → hydration + access-count writes spent on rows that are discarded.
- Live usage = LOCAL+GLOBAL layered (session-start ritual), so real wall ≈ 2× the single-store benchmark table. Query embedding could be computed once and reused across stores (model singleton is shared, inference is not).

### NEW-4 — facet path & older schemas: access bump never committed → silently rolled back
- `_facet_fast_search` returns at `light_search_pipeline_orchestrator.py:242→338-347` WITHOUT reaching `_record_latency` → hydration's UPDATE (:119) sits in an open implicit transaction; search verb never commits; close() rolls back.
- Same loss on full path if the `search_latency` INSERT fails (except swallowed :693-695, commit never reached).
- Effects: (a) salience access data silently lost on the facet fast lane; (b) open write txn holds the WAL writer slot until process exit — WORSE for concurrency than the committed write the docs flagged.
- Side effect: `search_latency` never records facet-path runs → the benchmark p50/p95 in performance-analysis.md exclude the fast lane entirely.

### NEW-5 — tag-affinity candidate-set explosion (co-suspect for the flat ~30ms scoring)
- `_discover_tag_neighbors` pulls EVERY neuron sharing ANY seed tag — `search/tag_affinity_scoring_shared_tags.py:284-288`; depth-2 repeats over hop1 tags (:370-374).
- One common seed tag (`hub`, `person`, `system-rule`) drags a large fraction of the corpus into candidates → inflates temporal + salience IN-queries, final sort, and an O(hop1×hop2) Python double loop (:401-413).
- Docs attribute flat ~30ms scoring to BFS PRAGMA alone — unproven; scoring_ms has no sub-timers. Add tag-affinity sub-timer to the measurement-gaps list; consider a per-tag row cap.

## Minor corrections / notes
- Seed count: BM25 cap 100 + vector cap 100 → RRF union ≤200 seeds, not "≤100" (analysis §BFS).
- Vector KNN entry: `retrieve_vectors` at `vector_retrieval_two_step_knn.py:44`; `:88` is the dim guard, not the "path entry".
- Archived neurons keep occupying vec0 KNN slots — filtered AFTER KNN (`vector_retrieval_two_step_knn.py:228-232`); k=100 slots wasted as archive grows.
- `search_latency` has no pruning → unbounded growth (small rows; note only).
- Fuzzy fallback loads ALL neurons + tags + attrs into Python and Levenshteins each (`fuzzy_fallback_levenshtein.py:38-47`) — zero-result path only, but full-table Python scan; scale-later flag alongside vec0.
- `except Exception` at orchestrator :269-279 hides pipeline errors as bare exit 2 (no message) — hygiene, not perf.
- All top5 path:line spot-checked: orchestrator :686/:692/:262 ✓, hydration :120 ✓, bfs :321/:287/:295/:302/:245 ✓, model_loader :35-36/:108 ✓.
