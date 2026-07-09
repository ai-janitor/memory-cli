---
type: reference
title: Query-path performance analysis (LIGHT search)
description: Stage-by-stage cost map + ranked bottlenecks for `memory neuron search`, with benchmarked latency from the live store.
tags: [performance, search, latency, embedding, sqlite-vec, bottlenecks]
timestamp: 2026-07-09
---

# Query-path performance analysis — LIGHT search

Scope: the LIGHT pipeline (`memory neuron search`), the primary query path.
HEAVY (Haiku) tier noted where relevant. Store: `~/.memory/memory.db`, 769
neurons / 939 edges, 139 MB GGUF model.

Every latency claim tagged `(benchmarked)` or `(static analysis)`.

## Benchmark snapshot (benchmarked)

Live store, this session. Wall = `/usr/bin/time -p`; stage ms = recorded
`search_latency` table (last 20 full-pipeline runs).

- full search wall: ~0.52 s
- facet fast-path wall (`--tag hub`, no embed): **0.19 s**
- bare `--help` (interp + import only): 0.08 s
- recorded avg (last 20): **total 1984 ms · retrieval 1948 ms (98%) · scoring 33 ms · output 2.8 ms**
- recorded p50 total 268 ms · p95 **24916 ms** · p99 24916 ms (`memory meta health`)
- per-run retrieval_ms spread: 12 · 17 · 20 · 240 · 289 · 300 · 502 · 595 · 1044 · 2357 · 2558 · 3457 · **25885** ms

Read of the spread:
- retrieval = 98% of latency. scoring + output = rounding error at this corpus size.
- bimodal retrieval: ~12-25 ms (model file warm in OS page cache) vs 240 ms-25 s (cold load / memory pressure).
- the split IS the model-load cost. Warm = cheap, cold = catastrophic.
- scoring ~30 ms flat across runs despite 100-candidate cap + only 769 neurons — see BFS PRAGMA item.

## Query path map (stage-by-stage)

Entry: `neuron_noun_handler` → `light_search()`
(`src/memory_cli/search/light_search_pipeline_orchestrator.py:207`).

Per-invocation fixed cost (before pipeline):
- Python interp + import (incl. `llama_cpp`, `sqlite_vec`): ~80 ms `(benchmarked, --help)`
- `open_connection` — 4 PRAGMAs (`connection_setup_wal_fk_busy.py:52`) `(static: trivial)`
- `load_sqlite_vec` — `enable_load_extension` + `sqlite_vec.load` + **CREATE/DROP `_vec_test` vec0 DDL every open** (`extension_loader_sqlite_vec.py:78`) `(static: small, but a vec0 DDL per process)`

Facet fast-path — `--type`/`--tag` without `--semantic`
(`light_search_pipeline_orchestrator.py:238`, `_facet_fast_search:305`):
- indexed attr/tag resolve → BM25-in-subset (staged AND→OR→recency) → hydrate.
- **zero model load.** 0.19 s wall `(benchmarked)`. This is the fast lane; the full pipeline is not.

Full pipeline (no facet):

| Stage | Module:fn | What it costs |
|---|---|---|
| 1 Embed query | `_run_retrieval_stage:557` → `get_model` / `embed_single` | **model load (139 MB GGUF) + inference. Dominant.** `(benchmarked)` |
| 2 BM25 | `bm25_retrieval_fts5_match.retrieve_bm25:60` | 1 FTS5 MATCH, cap 100. Cheap. `(static)` |
| 3 Vector KNN | `vector_retrieval_two_step_knn:88` | `struct.pack` 768 floats + vec0 KNN (linear scan of all vectors) + existence IN-query. Cheap @769. `(static)` |
| 4 RRF | `rrf_fusion_rank_based_k60.fuse_rrf` | in-memory. Trivial. `(static)` |
| 5 Activation BFS | `spreading_activation_bfs_linear_decay.spread:98` | **2 edge queries + 1 `PRAGMA table_info` per visited node.** `(static)` |
| 5b Tag affinity | `tag_affinity_scoring_shared_tags.apply_tag_affinity:46` | multi-scan of `neuron_tags`, depth-2 pass. `(static)` |
| 6 Temporal | `temporal_decay_exponential_halflife:658` | 1 IN-query, math. `(static)` |
| 6b Salience | `salience_scoring_access_metrics:480` | 1 IN-query, math. `(static)` |
| 7 Tag filter | `tag_filter_post_activation.filter_by_tags` | only if `--tag`. `(static)` |
| 8 Final score | `final_score_combine_and_rank.compute_final_scores` | sort candidate set (≤ few hundred). `(static)` |
| 9 Paginate | orchestrator `:642` | slice. `(static)` |
| 10 Hydrate | `search_result_hydration_and_envelope.hydrate_results:47` | batch neuron + tag + edge-summary fetch, **+ UPDATE access_count (write on read)**. `(static)` |
| 11 Fuzzy fallback | orchestrator `:648` | only when results empty. `(static)` |
| — Record latency | `_record_latency:672` | **INSERT + `conn.commit()` every search (write on read).** `(static)` |

Stages 4-11 total ~33 ms scoring + 3 ms output `(benchmarked)`. All the money is stage 1.

## Bottleneck ranking

| # | Bottleneck | path:line | Why slow | Est. impact | Fix |
|---|---|---|---|---|---|
| 1 | **Embedding model reloaded every CLI process** | `model_loader_lazy_singleton.py:52` (singleton is module-level → dies with process) | 139 MB GGUF loaded fresh on every `memory neuron search`. "Lazy singleton" caches within one process only; each CLI call is a new process → full reload. Retrieval = 98% of latency, p50 264 ms, cold tail to 25 s. `(benchmarked)` | **Massive.** Removes ~200 ms-25 s from every semantic search | Persistent embedding daemon / socket server holding the model warm; CLI sends query text, gets vector back. Or `mmap`+`mlock` the GGUF and rely on OS page cache (warm runs already show ~12-25 ms — prove it, then pin it). Fallback: skip embedding for short keyword queries (BM25 is enough), route them to a no-embed path like facet does. |
| 2 | **Cold-load / contention tail** | same as #1 + `extension_loader_sqlite_vec.py:78` | p95 24916 ms, one run 25885 ms retrieval. Model load competes for RAM/disk; second concurrent `memory` process reloads 139 MB again. `(benchmarked)` | **Massive tail.** p95 50× over 500 ms threshold | Same daemon as #1 (one resident copy, no per-process reload, no double-load under concurrency). Until then, `memory meta health` already flags it — surface the warning to users. |
| 3 | **Write-on-read: access-count UPDATE + latency INSERT, each committed** | `hydrate_results` UPDATE `search_result_hydration_and_envelope.py` (access_count bump); `_record_latency:686` INSERT + `conn.commit()` | Every read does 2 writes + a WAL commit. Blocks the single-writer slot, defeats read-only concurrency, grows WAL, adds fsync. `(static analysis)` | Small per-call (~ms) but scales badly under concurrent search + poisons reader parallelism | Make search read-only by default: gate access-tracking behind a flag or batch it (accumulate, flush on exit / every N). Sample latency recording (1-in-N) or write to a separate connection. One commit max, not per-query fsync. |
| 4 | **BFS emits `PRAGMA table_info(edges)` + 2 edge queries per visited node** | `spreading_activation_bfs_linear_decay.py:_get_neighbors` + `_has_confidence_column` | `_has_confidence_column` runs a PRAGMA on **every** `_get_neighbors` call (deliberately un-cached per comment), and neighbors are fetched one node at a time (2 SELECTs each). Fan-out over ≤100 seeds → hundreds of PRAGMA + query round-trips. Explains flat ~30 ms scoring at only 769 neurons. `(static analysis)` | Medium; grows with fan-out-depth and corpus | Resolve the confidence-column flag **once per pipeline** (pass it in, or cache per-connection with a schema-version key — not per `id(conn)`). Batch neighbor discovery: one recursive CTE or a single `source_id IN (...) OR target_id IN (...)` per BFS frontier instead of per node. |
| 5 | **vec0 KNN is a linear scan; query embedding re-`struct.pack`ed each call** | `vector_retrieval_two_step_knn.py:_query_vec0_standalone` | sqlite-vec `vec0` has no ANN index — KNN scans all N vectors × 768 dims per query. Fine @769 (~ms), but O(N) — at 100k neurons this becomes the new stage-1. Plus a 768-float `struct.pack` in Python per query. `(static analysis)` | Low now, structural at scale | Track corpus growth. When N large: metadata pre-filter (project/type) before KNN, or partitioned vec0 tables, or an ANN-capable vector store. Cache the packed query blob (already have it from embed). Low priority until N ≫ 1k. |

## Top 5 summary

1. **Model reloaded per process** — the whole ballgame. 98% of latency, cold tail 25 s. Warm a resident model (daemon / mlock). `(benchmarked)`
2. **Cold-load tail under memory pressure / concurrency** — p95 25 s. Same root as #1; daemon fixes both. `(benchmarked)`
3. **Write-on-read (access_count + latency, committed every search)** — defeats reader concurrency, per-query fsync. Batch / sample / make read-only. `(static)`
4. **BFS PRAGMA-per-node + N+1 edge queries** — flat ~30 ms scoring at tiny corpus; scales with fan-out. Cache schema flag once, batch the frontier. `(static)`
5. **vec0 linear-scan KNN** — cheap now, O(N) time bomb. Pre-filter / ANN when corpus grows. `(static)`

## Quick wins vs structural changes

Quick wins (low risk, ship now):
- cache `_has_confidence_column` once per `light_search()` call (#4, partial).
- sample `_record_latency` (1-in-N) or drop the per-call `commit()` (#3, partial).
- gate access-count UPDATE behind a flag; default read-only search (#3).
- keyword/short queries → skip embed, BM25-only path (partial #1, no new infra).

Structural (bigger, higher payoff):
- **embedding daemon** holding the GGUF warm across CLI calls (#1 + #2). Biggest single win.
- batch BFS neighbor fetch via recursive CTE (#4).
- ANN / partitioned vectors when N ≫ 1k (#5).

## Measurement gaps (what to benchmark to confirm)

- Split retrieval_ms into **embed-load vs embed-inference vs bm25 vs vector** — current table lumps all into `retrieval_ms`. Add sub-timers to confirm model load (not inference/KNN) is the driver. Strongly implied by warm-vs-cold bimodality but not directly isolated. `(static inference)`
- Measure warm-model floor: run N searches in ONE process (e.g. a REPL / test harness bypassing per-call spawn) to see the true post-load per-query cost. Expect ~12-30 ms.
- Quantify #3: search throughput with vs without the access-count UPDATE + latency commit, under 2+ concurrent `memory` processes (WAL writer contention).
- Quantify #4: scoring_ms vs `--fan-out-depth` 1/2/3 and vs corpus size — confirm PRAGMA/N+1 growth curve.
- vec0 KNN scaling: synthetic 10k / 100k vector stores, time stage 3 alone.
- HEAVY tier: Haiku expansion + rerank add 2 network round-trips on the critical path (`search/heavy/`) — not measured here; benchmark separately, they will dwarf everything if on by default.
