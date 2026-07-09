---
type: plan
title: neuron search fix methodology — staged remediation, per-fix specs
description: Execution methodology for the fixes ranked in review 0001. Per-fix scope, files, acceptance criteria, verification, and the deploy gate that closes the fix-not-live class.
tags: [memory-cli, plan, performance, search, remediation]
timestamp: 2026-07-09
status: plan-frozen
related: [./0001-neuron-search-architecture-review.md, ../delegations/MEM-FIX-0007.spec.md]
---

# Search Fix Methodology

- Source: review `0001-neuron-search-architecture-review.md` (ranked table §TL;DR)
- Process: every code fix runs the **maintain-operate-orchestration** skill. Flow: acceptance-test-first → spec in `docs/delegations/MEM-FIX-000N.spec.md` → baseline ×5 → doer (hard cap 3 attempts) → opus gate → changelog → **deploy → live re-measure**
- Baseline rule (CLAUDE.md): `uv run pytest tests/` ×5, quiet box (`uptime` 1-min < ~20)
- Fences (all fixes): no new DB indexes without spec; semantic path (INV-A) + heavy path (INV-B) must stay green; no test weakened to pass

## FIX-1 — deploy MEM-FIX-0007 (no code, do FIRST)

- Do: `uv tool install --reinstall /Users/hung/projects/memory-cli`
- Verify (all three, live path):
  1. `grep -c facet_fast ~/.local/share/uv/tools/memory-cli/lib/python3.13/site-packages/memory_cli/search/light_search_pipeline_orchestrator.py` ≥ 1
  2. `time memory neuron search "verify on live path" --type lesson --limit 8 --format json` → wall < 1 s, user CPU < 1 s.
     Pre-deploy baseline: 43.16 s user / 812% / 5.4 s wall.
  3. non-facet `memory neuron search "verify"` still slow-ish (embeds) — proves semantic path intact, not hijacked
- Record measurements in backlog #72 Notes. Update incident 0048 open items.
- Rollback: `uv tool install memory-cli@<prior>` — but repo HEAD is gated green; none expected.

## FIX-2 — embed thread cap (MEM-FIX-0008 candidate)

- Problem: `model_loader_lazy_singleton.py:108-114` passes no `n_threads`/`n_threads_batch`; llama.cpp defaults to `cpu_count()` (=16) per process (`llama_cpp/llama.py:305-306`). N concurrent embeds = N×16 threads.
- Scope:
  - `config/config_schema_and_defaults.py` — add `embedding.n_threads` (int ≥1, default 4), `embedding.n_batch_threads` (int ≥1, default 4)
  - `model_loader_lazy_singleton.py` — pass both into `Llama(...)`
- Acceptance (new file `tests/embedding/test_thread_cap.py`):
  - AC-1: `Llama` constructor receives `n_threads=4, n_threads_batch=4` by default (spy/mock — no real model load in test)
  - AC-2: config override (e.g. 2) reaches the constructor
  - AC-3: existing embedding tests green (dims, prefix, normalize untouched)
- Live verify post-deploy: run one semantic search, `ps -o %cpu` on the proc → ≤ ~400% (4 threads), not 800%+
- Risk: slower single embed (~2-4× wall on inference stage). Accepted — fleet concurrency > single-query latency here. Config knob lets a solo user raise it.

## FIX-3 — per-query hard timeout + self-reap (#72 item 4a)

- Problem: searches observed wedged 22-31 h, holding slots. No bound anywhere in the CLI.
- Design: wall-clock watchdog at CLI entry (`__main__.py` / dispatcher), not inside the pipeline:
  - `signal.alarm(timeout)` on the main thread; handler raises → envelope `status=error, reason=timeout`, **exit code 3** (distinct from 2=error; empty≠failure rule)
  - default 120 s; `config search.timeout_s`; `--timeout` flag override; 0 = disabled
  - scope to search verbs first (search, gate discovery, heavy) — add/list/get don't wedge
- Acceptance:
  - AC-1: search stubbed to sleep > timeout → exits code 3 within timeout+2 s, error envelope on stderr
  - AC-2: normal search unaffected (no alarm residue — alarm cancelled on success)
  - AC-3: timeout=0 disables
- Caveat: `signal.alarm` is unix-only + main-thread-only — fine (CLI is unix, single-threaded Python; llama.cpp threads are C-level but the Python main thread regains control at the GIL boundary; if a C call never returns, escalate to a fork/kill watchdog — spec that only if AC-1 proves insufficient).
- Live verify: none practical on demand; rely on AC + absence of multi-hour procs over next fleet cycles.

## FIX-4 — embed query once across layered stores

- Problem: `handle_search` (`neuron_noun_handler.py:435-441`) runs `light_search` per store; each call embeds the same query. LOCAL+GLOBAL = 2 inferences.
- Design:
  - `SearchOptions` += `query_embedding: Optional[List[float]] = None` (additive, default None)
  - `_run_retrieval_stage` (`light_search_pipeline_orchestrator.py:481-494`): if `options.query_embedding` set → use it, skip `get_model`/`embed_single`
  - `handle_search`: before the store loop, embed once (semantic path only — facet fast-path needs no vector); pass into every store's options; on embed failure pass None (per-store BM25 fallback unchanged)
- Acceptance:
  - AC-1: two-store layered search → `embed_single` called exactly once (spy)
  - AC-2: single-store behavior unchanged
  - AC-3: pre-computed embedding produces identical results to in-pipeline embed (same query, same store)
  - AC-4: facet fast-path still calls no embed at all
- Fence: dimension check stays in `retrieve_vectors` (`vector_retrieval_two_step_knn.py:91`) — guards a bad caller-supplied vector.

## FIX-5 — embedding cache (#72 item 4b)

- Design: cache EMBEDDINGS, not result sets. Embeddings are deterministic per (model, text) — no TTL/invalidation problem; result caches go stale on every write.
  - key: `sha256(model_fingerprint + prefixed_text)`; value: 768-float blob
  - store: `embedding_cache` table in the GLOBAL store db (WAL already on); LRU cap ~5k rows
  - hook: inside `embed_single` wrapper on the query path only (`op_type="query"`) — index-time texts rarely repeat
  - invalidation: model_fingerprint in the key = self-invalidating on model swap (integrity module already tracks model drift)
- Acceptance: AC-1 second identical query hits cache (no `model.embed` call, spy); AC-2 different text misses; AC-3 model-fingerprint change misses; AC-4 cache write failure degrades silently to compute.
- Payoff evidence: storm showed 7 identical concurrent queries; fleet gate phrases are a small fixed set.
- Order note: after FIX-1..3. Combined with FIX-2, residual embed cost may already be acceptable — re-measure before building.

## FIX-6 — spreading-activation batching (low)

- Problem: `_get_neighbors` per BFS node = 2 SELECTs (`spreading_activation_bfs_linear_decay.py:295-306`) + `PRAGMA table_info` (`:321`). Visited set × 3 round-trips.
- Design: per-depth frontier query — `WHERE source_id IN (...) OR target_id IN (...)` once per BFS level; hoist confidence-column check to once per `spread()` call (per-call is safe — the docstring's id-reuse caveat only forbids cross-connection module-level caching).
- Acceptance: identical activation output on a fixture graph (golden test, order-insensitive compare); query count per search ≤ depth+1 (trace via `sqlite3.Connection.set_trace_callback`).

## FIX-7 — latency-record write sampling (low)

- Problem: `_record_latency` (`light_search_pipeline_orchestrator.py:621-644`) = INSERT+COMMIT per search on the read path; WAL single-writer; 22 concurrent readers contend (candidate wedge mechanism — hypothesis).
- Design: sample 1-in-10 (deterministic on query hash, not RNG) + `PRAGMA busy_timeout=0` for this write only — never wait on stats.
- Acceptance: AC-1 sampled-out search does zero writes; AC-2 write-locked db → search still returns results, no stall.

## Deploy gate (process fix — closes the FINDING-0 class)

- Amend `~/.skills/maintain-operate-orchestration/` definition of done: after changelog → **(8) deploy** `uv tool install --reinstall .` → **(9) live re-measure** the original symptom, record numbers in the result doc.
- Rule: a fix without a live-path re-measure is "delivered, outcome unknown" — not FIXED.
- Also mirror into memory-cli `CLAUDE.md` maintenance-mode block (one line).

## Execution order + dependencies

| step | fix | depends on | gate evidence |
|------|-----|-----------|---------------|
| 1 | FIX-1 deploy | — | 3 live measurements (§FIX-1) |
| 2 | deploy-gate skill amend | — | skill diff + CLAUDE.md line |
| 3 | FIX-2 thread cap | — | AC + live %cpu |
| 4 | FIX-3 timeout | — | AC transcript |
| 5 | FIX-4 embed-once | — | AC spy transcript |
| 6 | re-measure fleet load under gate churn | 1-5 deployed | load-avg + proc-count vs incident 0048 numbers |
| 7 | FIX-5 cache | step 6 says still needed | AC + hit-rate sample |
| 8 | FIX-6/7 | idle capacity | golden/AC |
| — | daemon, ANN | triggers in review 0001 §3/§6 | — |

- Steps 3-5 are disjoint files → can run as parallel doer streams after step 1.
- Each code fix = own MEM-FIX-000N spec; this doc is the mother plan, specs stay per-change.
