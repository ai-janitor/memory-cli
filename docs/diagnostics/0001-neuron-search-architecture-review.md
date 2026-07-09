---
type: report
title: neuron search architecture review — load storm root, tool architecture, index strategy
description: Architecture review after the 2026-07-09 fleet load storm (load 600+). Verifies diagnosed root causes, finds the fix-not-deployed gap, rules on daemon/pipeline/ANN/caller-contract questions.
tags: [memory-cli, diagnostics, performance, search, architecture]
timestamp: 2026-07-09
status: review-complete
related: [../delegations/MEM-FIX-0007.spec.md, ../delegations/MEM-FIX-0007.result.md]
---

# Neuron Search Architecture Review

- Reviewer: fable-yoda (architect, dag-flow squad)
- Trigger: 2026-07-09 load storm — host load 495→607→677, 22 concurrent `memory neuron search` procs, wedged stragglers 22-31 h
- Cross-refs: minion backlog #72, `docs/delegations/MEM-FIX-0007.*`, droid incident `docs/diagnostics/0048-lesson-protocol-load-storm.md`
- Scope: analysis + recommendations only. No code changes.

## TL;DR — ranked by bang-for-buck

| # | action | cost | effect | status |
|---|--------|------|--------|--------|
| 1 | DEPLOY MEM-FIX-0007 (`uv tool install --reinstall .`) | zero code | kills the storm class of query | **NET-NEW — fix landed in repo, live binary STALE** |
| 2 | cap embed threads (`n_threads`/`n_threads_batch` in config → 2-4) | ~5 lines | one embed can no longer grab all 16 cores | net-new |
| 3 | hard per-query timeout + self-reap | small | no more 22-31 h wedged procs | #72 item 4, not started |
| 4 | embed query ONCE across layered stores | small | halves semantic-search embed cost | net-new |
| 5 | query/embedding cache | medium | bounds repeat identical queries (7 observed) | #72 item 4 |
| 6 | batch BFS neighbor query + hoist PRAGMA out of loop | small | removes N+1 in spreading activation | net-new |
| 7 | drop stopwatch write from read path (or fire-and-forget) | small | removes writer contention on concurrent search | net-new |
| 8 | embedding daemon | large | shared model across procs | #72 item 2 — DEFER, trigger below |
| 9 | ANN vector index | large | sub-linear KNN | #72 item 3 — DEFER, trigger below; strategy in §6 |

## 1. Verified facts (live path, measured 2026-07-09)

- Corpus: global store 766 neurons / 938 edges (6 MB); droid-local 218 / 198 (4 MB). TINY.
- Model: `~/.memory/models/default.gguf` = 139 MB nomic-embed-text-v1.5 Q8_0.
- Measured live: `memory neuron search "verify on live path" --type lesson --limit 8` → **43.16 s user CPU, 812% CPU, 5.4 s wall** on a quiet box (load ~13). Under fleet load it stretches to the observed 1-6 min.
- 812% = llama.cpp thread default. `llama_cpp/llama.py:305-306`: `n_threads = cpu_count()//2`, `n_threads_batch = cpu_count()` (=16 here). `model_loader_lazy_singleton.py:108-114` passes neither → every embed grabs the whole box.
- Layered fan-out: `handle_search` (`cli/noun_handlers/neuron_noun_handler.py:435-441`) loops stores, runs full `light_search` per store → query embedded TWICE per invocation (model load shared in-process; inference is not).
- Diagnosed causes 1-5 from the assignment brief: **all confirmed** in source. File:line below.

## 2. FINDING-0 (net-new, CRITICAL): fix landed, never deployed

- Repo HEAD `9d866cb` has MEM-FIX-0007 complete: facet fast-path (`light_search_pipeline_orchestrator.py:241` → `_facet_fast_search:282`), CLI wiring (`neuron_noun_handler.py:423-425`), 9 AC green, heavy INV-B guard.
- Installed tool = uv tool at `~/.local/share/uv/tools/memory-cli/` → `grep -c facet_fast .../light_search_pipeline_orchestrator.py` = **0**. Pre-fix code.
- So the fleet's exact storm query (`--type lesson --limit 8`) STILL cold-loads llama.cpp on every gate. The 43 s / 812% measurement above IS the stale binary.
- Fix: `uv tool install --reinstall /Users/hung/projects/memory-cli`. Then re-measure — facet queries should be sub-second, zero model load (AC-2 already proves it at test level).
- Process gap: maintain-operate skill's definition of done stops at commit+gate. Add a DEPLOY step: fix ≠ done until the installed binary is rebuilt and the symptom is re-measured on the live path. This exact class is the "verified fix requires live-path rerun" rule.

## 3. Question (a) — per-process CLI model load vs resident daemon

Verdict: **per-process stays, daemon deferred.** Reasoning:

- After #1 (deploy) the storm class (typed gate lookups) never touches the model. Remaining embed cost falls only on true semantic queries.
- llama.cpp mmaps the GGUF — after first load the 139 MB is warm in page cache; the CPU burn is context init + inference, not disk. Thread cap (#2) bounds that to a few cores.
- A daemon buys: one model instance, batched embeds, warm context. It costs: socket lifecycle, liveness/restart, version skew between CLI and daemon, packaging, security surface. That is a second system to operate — wrong trade while semantic QPS is near zero.
- Cheap middle steps first, in order: (1) thread cap; (2) embed-once-across-stores (`handle_search` computes the query vector once, passes it down — the vector is store-independent, same model + 768 dims everywhere); (3) embedding cache keyed by (model_hash, query_text) — a tiny sqlite/file cache; the observed storm had 7 identical concurrent queries.
- DAEMON TRIGGER: semantic (non-facet) searches exceed ~10/min sustained fleet-wide, OR p50 semantic wall time still >2 s after items 1-5. Then: unix-socket embed server, spawn-on-demand, idle-exit, CLI falls back to in-proc when socket absent. Embed-only — do NOT move search logic into the daemon.

## 4. Question (b) — one 10-stage pipeline vs split entry paths

Verdict: **two contracts, one verb — formalize the tiering MEM-FIX-0007 started.**

- `light_search` (`light_search_pipeline_orchestrator.py:156`) now has an implicit tier system: facet fast-path (`:241`) vs full pipeline. Keep the single `neuron search` verb; make the tiers explicit + documented:
  - T0 LOOKUP: `--type`/`--tag` scoped, no `--semantic` → indexed pre-filter + BM25-in-subset. No model. (landed)
  - T1 KEYWORD: full pipeline minus embed — today only reachable as the vector_unavailable fallback. Consider `--keyword` flag to opt in cheaply.
  - T2 RECALL: full hybrid (embed + vector + RRF + activation). The default for bare-text queries — correct conventional behavior for a semantic memory tool; do NOT make keyword the default.
- Do not physically split the orchestrator. The fast-path branch at the top is the right shape; a second parallel pipeline would drift (this repo already caught a dead drifted twin pattern elsewhere).
- Heavy search: keep building its sub-queries with `semantic=True` (`heavy_search_orchestrator.py`, INV-B fix in `9d866cb`) — heavy is by definition T2.

## 5. Question (d) — caller contract for typed lookups

- Gate "review lessons" lookups are BOUNDED TYPED FETCHES, not recall. Contract for fleet callers, in priority order:
  1. `memory neuron list --type lesson` (`neuron_list_filtered_paginated.py`) — pure indexed list, no ranking, no model. Right verb when no query text matters.
  2. `memory neuron search "<phrase>" --type lesson` — T0 fast-path once deployed. Right verb when ranking within the facet matters.
  3. `--semantic` — explicit opt-in only.
- Caller-side: cache one lesson set per role per session, not per-gate re-query. Droid-side item (incident 0048 rec #1) — tracked there, out of this repo's scope, but the CLI contract above is what makes it cheap.
- Document this in the CLI manpage/help for `search` ("typed lookup? use list or --type; bare search = semantic = expensive"). Agents follow the help text.

## 6. Question (c) — vector index strategy (vec0 brute-force ceiling → ANN)

Current: `neurons_vec` vec0 table, brute-force cosine over every row per query (`vector_retrieval_two_step_knn.py:117-183`). FTS5 side indexed; vector side linear.

Ceiling math. 768-dim float32 = 3 KB/vector:

| corpus | scan size | brute-force est. | verdict |
|--------|-----------|------------------|---------|
| 766 (today) | 2.3 MB | ~1 ms | non-issue |
| 10 k | 30 MB | ~10-30 ms | fine |
| 100 k | 300 MB | ~0.1-0.5 s | pain begins |
| 1 M | 3 GB | seconds + memory pressure | ANN mandatory |

Staged plan — cheapest lever first, each stage buys ~an order of magnitude:

1. NOW — nothing. Embed cost dominates by 3-4 orders of magnitude at 766 rows. Any ANN work today is premature optimization.
2. ~10 k rows — shrink vectors before indexing them:
   - Matryoshka truncation: nomic-embed-text-v1.5 is MRL-trained — truncate 768→256 dims (+re-normalize) at ~1-2% recall loss. 3× smaller, 3× faster scans. Schema change (vec0 column dim) + one re-embed-free migration (truncate stored vectors).
   - sqlite-vec quantization: vec0 supports `bit` (binary) and int8 columns. Binary = 32× smaller, hamming distance, then re-rank top-4×K with the float vectors already stored. Both stay INSIDE sqlite-vec — no new dependency.
   - Partition keys: vec0 `PARTITION KEY` column (e.g. project/status) turns full scans into per-partition scans if lookups are usually scoped.
3. ~50-100 k rows OR measured vector-stage p50 >100 ms — ANN sidecar. Pick order:
   - `usearch` — single-file, SQLite-friendly, python binding, HNSW, supports i8/b1 quantization. Best fit for a zero-daemon CLI.
   - `hnswlib` — mature, simple, but index rebuild story is manual.
   - `faiss` — overkill below millions; heavy dependency; skip.
   - Sidecar pattern: HNSW index file next to the .db, rebuilt incrementally on `neuron add`/re-embed, brute-force vec0 kept as the correctness fallback + rebuild source. Never a second source of truth.
4. Decision instrument already exists: `search_latency` table (`light_search_pipeline_orchestrator.py:621`) records retrieval_ms per query. Add corpus row count to `meta stats` review; re-check thresholds when either trips.

Flag for #72 item 3: reframe from "add ANN" to the staged plan above. Stage 2 (truncate + quantize inside sqlite-vec) likely defers ANN by years — corpus is 766 rows after months of use.

## 7. Question (e) — other structural bottlenecks found

- Spreading activation N+1 (`spreading_activation_bfs_linear_decay.py:238`): 2 SQL queries + 1 `PRAGMA table_info` (`:321`) **per visited node** per search. Fix: one batched frontier query per depth (`WHERE source_id IN (...) OR target_id IN (...)`), hoist the confidence-column check to once per `spread()` call (per-connection, not per-node — the id-reuse caveat in the docstring only forbids cross-connection module caching).
- Latency stopwatch writes on the read path (`_record_latency`, `light_search_pipeline_orchestrator.py:621-644`): INSERT+COMMIT per search. WAL = single writer; 22 concurrent searches contend on it (5 s busy_timeout, `connection_setup_wal_fk_busy.py:85`). Candidate for the wedge mechanism behind the 22-31 h stragglers (unproven — hypothesis; the reap timeout in #3 makes the question moot). Fix: sample it, buffer it, or accept lost records with a 0-timeout write.
- Fuzzy fallback (`fuzzy_fallback_levenshtein.py`, fired from orchestrator `:599`): zero-result queries trigger a full-corpus Python Levenshtein scan over content+tags+attrs. Fine at 766 rows; unbounded growth path. Cap candidate set (e.g. FTS5 prefix/trigram pre-cut) before ~10 k rows.
- Per-invocation migration probe (`db_connection_from_global_flags.py:110-112`): schema-version read per store per command. Cheap (1 SELECT) — no action.
- Layered double-embed: §3 item (2). One embed, N store queries.

## 8. What existing work already covers vs net-new

| item | covered by | net-new from this review |
|------|-----------|--------------------------|
| facet fast-path | MEM-FIX-0007 (landed) | deploy gap (§2), deploy step in skill |
| shared model/daemon | #72 item 2 | defer verdict + trigger + embed-only fence (§3) |
| ANN | #72 item 3 | staged shrink-first plan, thresholds, usearch pick (§6) |
| cache + timeout/reap | #72 item 4 | embedding-cache framing; wedge hypothesis (§7) |
| thread cap | — | net-new (§1, rank 2) |
| embed-once across stores | — | net-new (§3) |
| BFS N+1, latency-write contention, fuzzy scan | — | net-new (§7) |
| caller contract (list vs search vs --semantic) | droid incident 0048 rec 1 (caller side) | CLI-side contract + help-text change (§5) |

## 9. Recommended execution order

1. `uv tool install --reinstall .` + re-measure the storm query (expect <1 s, ~0% model CPU). Update #72 with the measurement.
2. File + fix: thread cap config knob (5 lines: config schema + pass-through in `model_loader_lazy_singleton.py:108`).
3. File + fix: per-query hard timeout/reap (#72 item 4 front half).
4. File: embed-once-across-stores; embedding cache.
5. Backlog (low): BFS batch query, latency-write sampling, fuzzy cap.
6. Amend #72 item 3 with §6 staged plan; set the two trigger metrics.
7. Daemon: leave parked with §3 trigger written into #72 item 2.
