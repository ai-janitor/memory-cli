---
type: reference
title: Query/search perf — detailed boost recommendations (ranked)
description: Where the big wins are, merged from perf-fix-plan.md, perf-second-look-findings.md, and backlog (#72 #66 #67 #35). Each item = what/why/how/acceptance/effort. Author = yoda (recon), for grok-commander.
tags: [performance, search, latency, recommendations, backlog]
timestamp: 2026-07-10
---

# Perf boost recommendations — ranked by payoff

Inputs: `docs/perf-fix-plan.md`, `docs/performance-analysis.md`,
`docs/perf-second-look-findings.md`, backlog #72 (critical CPU storm),
#66 (central model), #67 (--global config), #35 (tag-affinity, shipped).

## R1 — Resident embedding daemon (THE win)

- STATUS: **SHIPPED** (2026-07-10, commit `8803a8c`, ADR 0001; see `CHANGELOG.md`
  → Unreleased/Added "Resident embedding daemon (R1 / ADR 0001)"). Warm GGUF over
  unix socket + inproc fallback; `memory embed daemon --bg|--stop`; health probe.
  Reds: `tests/embedding/test_r1_daemon_acceptance.py` +
  `tests/search/test_r1_daemon_fallback_integration.py`. NOTE: full-CLI wall stays
  host-bound (~90ms Python start + ~230ms) — daemon warms the EMBED (~16ms), not the
  process spawn. Do not re-propose.
- WHAT: one warm process holding the 139 MB GGUF; CLI sends query text over
  socket/IPC, gets 768-dim vector back. Fallback = in-process load (today's
  behavior), never hang.
- WHY: model reload per CLI process = 98% of latency (benchmarked). Cold p95
  ~24.9 s. Fleet concurrency = N cold loads, each llama.cpp multithreaded
  (100-153% CPU each) → the observed load-600 host melt (#72, diagnostics
  0048 Finding B). One daemon kills BOTH the per-call tail and the storm.
- HOW:
  - unix socket under `~/.memory/run/embedd.sock`; protocol = length-prefixed
    text in, float32 blob out; version-stamped handshake (model path + dims)
    to catch daemon/client skew.
  - autostart-on-miss + idle shutdown (e.g. 10 min); health probe in
    `memory meta health`.
  - interim (1-day version): `mmap` the GGUF and measure — warm runs are
    already 12-25 ms via OS page cache; `mlock` optional pin.
- ACCEPTANCE: cold client search with daemon warm < 100 ms wall; 2 concurrent
  clients → single 139 MB RSS copy; daemon kill → graceful in-process
  fallback; p95 over 20 back-to-back cold-client searches < 500 ms.
- EFFORT: architect, new process + lifecycle. Refs: plan #3/#4,
  `embedding/model_loader_lazy_singleton.py:35-36,108`.

## R2 — Route fleet callers onto the shipped facet fast path (free, today)

- STATUS: **SHIPPED** (2026-07-10, commit `00633bd`; see `CHANGELOG.md` →
  Unreleased/Added "Facet fast-path records `search_latency` (R2)"). Facet path
  records via shared `_record_latency` (R4 sampling rides same gate); #72 status
  note + fleet lint in `docs/diagnostics/0001-neuron-search-architecture-review.md`.
  Reds: `tests/search/test_r2_facet_fastpath_perf_acceptance.py`. Do not re-propose.
- WHAT: no CLI code change — `_facet_fast_search` (MEM-FIX-0007/0008) already
  skips embed + vector + activation for `--type`/`--tag` queries without
  `--semantic`. 0.19 s wall, zero llama.cpp.
- WHY: #72's storm queries were exactly `--type lesson --limit 8` gate
  lookups. The primary fix in #72's notes is ALREADY LANDED
  (`search/light_search_pipeline_orchestrator.py:242,282`); the backlog item
  predates it and reads stale.
- HOW:
  - caller-side: audit fleet gate protocols (droid "review lessons" hot path)
    — ensure they call `--type lesson` WITHOUT `--semantic` so they hit the
    fast lane; add a lint/doc line to the gate protocol.
  - CLI-side polish: facet path currently invisible to `search_latency`
    (returns before `_record_latency`, orchestrator :338-347) — add recording
    so the win is measurable.
  - update #72 with a status note: fix-1 shipped, remaining scope = daemon +
    timeout.
- ACCEPTANCE: gate-lookup command < 300 ms wall from fleet host; zero
  `Llama(...)` constructions during it (trace).
- EFFORT: ops/docs + 5-line CLI patch.

## R3 — Hard per-query timeout + self-reap

- STATUS: **SHIPPED** (2026-07-10, commit `4069ed85`; see `CHANGELOG.md` →
  Unreleased/Added "Hard per-query search timeout + self-reap (R3)"). SIGALRM
  ceiling (default 120 s, CLI `--timeout <s>`) around `light_search`; breach
  raises `SearchTimeoutError` naming the stage; CLI exits ≠ 0. Reds:
  `tests/search/test_r3_hard_timeout_self_reap.py` (7/7). Do not re-propose.
- WHAT: wall-clock ceiling on the whole search (default e.g. 120 s, flag to
  raise); on breach: kill llama.cpp work, emit structured error, exit ≠ 0.
- WHY: observed wedged searches 22 h-31 h (#72, PIDs 20441/18334/11578).
  Under fleet concurrency, wedges never drain → pile-up is the DoS mechanism
  even more than per-query cost. Bounds worst case; no per-query speedup.
- HOW: `signal.alarm`/watchdog thread around `light_search` + model load;
  reap message includes stage reached (embed/bm25/vector/activation) so
  wedge location is diagnosable.
- ACCEPTANCE: induced hang (SIGSTOP the daemon / slow disk) → process exits
  at ceiling with clear error; no search PID older than ceiling on host.
- EFFORT: coder, small. Ref: #72 fix-4.

## R4 — True read-only search (write-on-read cluster, plan #1 + second-look)

- STATUS: **SHIPPED** (2026-07-10, commit `903c462`; see `CHANGELOG.md` →
  Unreleased/Added "True read-only search (R4)"). All 4 sub-fixes landed: v010 FTS
  trigger scoped to `UPDATE OF content`; access_count opt-in (default off); latency
  INSERT via side-channel writer; extension probe swapped to `vec_version()`/
  `pragma_module_list` (no CREATE/DROP). Search path = ZERO persistent writes →
  RO connections + concurrent fleet reads. Reds:
  `tests/search/test_r4_true_read_only_search.py` (6/6). Do not re-propose.
- WHAT: search must do ZERO writes. Four sub-fixes, do together:
  1. restrict FTS trigger: `trg_neurons_fts_update` → `AFTER UPDATE OF
     content ON neurons` (today it's unconditional — every access bump
     rewrites the FTS entry + 2 group_concat subqueries per hydrated neuron,
     ~20×/search; `db/migrations/v001_baseline_all_tables_indexes_triggers.py:293-307`).
     Requires a follow-up migration (v010) since triggers ship in v001.
  2. gate the access-count UPDATE (`search_result_hydration_and_envelope.py:119-123`)
     behind a flag or batch/flush; note facet path currently leaves it
     UNCOMMITTED → rolled back on close + holds WAL writer slot till exit
     (second-look NEW-4) — fixing read-only-by-default erases that bug too.
  3. sample `_record_latency` or use a separate writer connection; one commit
     max (`light_search_pipeline_orchestrator.py:686-692`).
  4. replace extension-probe DDL: `_vec_test`/`_fts5_test` CREATE+DROP run on
     EVERY open, every store — a real write txn before any query
     (`db/extension_loader_sqlite_vec.py:80-83,111-115`). Probe with
     `SELECT vec_version()` / `pragma_module_list` instead. Without this,
     plan #1's "zero writes" acceptance can never pass.
- WHY: unlocks reader concurrency for the fleet (WAL single-writer slot),
  shrinks WAL churn, de-noises benchmarks. Small per-call, big under load.
- ACCEPTANCE: trace callback on one search = 0 INSERT/UPDATE/DDL; 4+ parallel
  searches, no `database is locked`, no writer stall.
- EFFORT: coder + one migration. Refs: plan #1, second-look NEW-1/2/4.

## R5 — Model resolution correctness (#66 + #67)

- STATUS: **SHIPPED** (2026-07-10, commit `98aa96a`, gate=done; see `CHANGELOG.md`
  → Unreleased/Added "Config required on search embed path (R5 / #66 #67 close)").
  Bare `load_config()` fallback killed; `config=None` raises explicit ValueError
  (no silent wrong-store dead vector); central `~/.memory/models/default.gguf`
  guards retained. Reds: `tests/search/test_r5_model_resolution.py` (3/3). Do not re-propose.

- WHAT: central `~/.memory/models/default.gguf` resolution (shipped in
  loader, `model_loader_lazy_singleton.py:74-94`) + kill remaining bare
  `load_config()` fallback in `_run_retrieval_stage`
  (`light_search_pipeline_orchestrator.py:536-538` — live path now threads
  config via `get_layered_connections_with_config`, fallback remains for
  direct callers).
- WHY: not a latency win — a QUALITY win. Wrong-store model path made vector
  search silently dead (BM25-only) for 3 months in the emails store. Silent
  degradation wastes every other perf investment.
- ACCEPTANCE: `--global` search from any cwd → `vector_unavailable: false`;
  fresh local store with no model dir → vector works via central default.
- EFFORT: coder, small; mostly closing #66/#67 with regression tests.

## R6 — Multi-store efficiency (second-look NEW-3, do with R1)

- STATUS: **SHIPPED** (2026-07-10, commit `c05aaa0`; see `CHANGELOG.md` →
  Unreleased/Added "Multi-store embed-once + merge-before-hydrate (R6 / NEW-3)").
  Embed-once per `(model_path,dims)` identity + merge-before-hydrate in
  `handle_search`; config-identity guard keeps per-store embed when models differ.
  Reds: `tests/search/test_r6_multistore_embed_once.py` (3/3). Do not re-propose.
- WHAT: layered LOCAL+GLOBAL search runs the FULL pipeline per store
  (`cli/noun_handlers/neuron_noun_handler.py:435-441`): embed inference per
  store, latency commit per store, full-page hydration per store, then merge
  truncates and throws hydrated rows away (:452-458).
- HOW: embed the query ONCE per invocation and reuse across stores; merge
  candidate lists BEFORE hydration; hydrate only the final page.
- WHY: live usage is 2-store (session ritual) → today's real wall ≈ 2× the
  single-store benchmark. Cheap coder win, multiplies with R1.
- ACCEPTANCE: 2-store search = 1 embed call (trace), hydration rows ==
  final page size.

## Defer (corpus-growth triggered, do NOT build now)

- ANN vector index — vec0 KNN is O(N) brute force but ~ms at 769 neurons
  (plan #5). Trigger at N ≫ 1k.
- tag-affinity row caps — one common seed tag drags most of corpus into
  candidates (`tag_affinity_scoring_shared_tags.py:284-288`); co-suspect for
  the flat ~30 ms scoring. Add a sub-timer first, cap only if it shows up.
- fuzzy fallback full-table Python Levenshtein scan — zero-result path only.
- `search_latency` pruning — unbounded but tiny rows.

## Sequencing

| Order | Item | Type | Owner | Status |
|---|---|---|---|---|
| 1 | R2 fleet→facet path + #72 status note | ops/docs | today | ✅ SHIPPED `00633bd` |
| 2 | R3 timeout/self-reap | quick win | coder | ✅ SHIPPED `4069ed85` |
| 3 | R4 read-only search (4 sub-fixes) | quick win | coder | ✅ SHIPPED `903c462` |
| 4 | R1 embedding daemon | architecture | architect | ✅ SHIPPED `8803a8c` |
| 5 | R6 multi-store single-embed | small | coder (with R1) | ✅ SHIPPED `c05aaa0` |
| 6 | R5 close #66/#67 | correctness | coder | ✅ SHIPPED `98aa96a` |

One-liner: R1 + R2 kill both the 25 s tail and the concurrency DoS;
R3/R4 make the fleet safe while R1 is built; the rest is hygiene or later.
