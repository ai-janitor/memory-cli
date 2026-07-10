---
adr: 0001
title: Resident embedding daemon (warm GGUF across CLI processes)
status: proposed
date: 2026-07-10
deciders: memory-cli-architect (design), memory-cli-lead (build order)
supersedes: diagnostics/0001-neuron-search-architecture-review.md §3 (daemon DEFER + trigger)
related: [../performance-analysis.md, ../perf-fix-plan.md, ../perf-boost-recommendations.md, ../diagnostics/0001-neuron-search-architecture-review.md]
---

# ADR 0001 — Resident embedding daemon

## Context

- Symptom (benchmarked 2026-07-09): embedding model reloaded per CLI process =
  98% of search latency. Module-level singleton
  (`embedding/model_loader_lazy_singleton.py:35-36`) caches WITHIN one process;
  each `memory neuron search` = new process = full 139 MB GGUF reload (`:108-114`).
  p50 ~264 ms; cold p95 **24916 ms**.
- Worse under fleet concurrency (incident: load storm, host load 495→677, 22
  concurrent search procs): N cold loads, each llama.cpp multithreaded
  (100-153% CPU, `n_threads=cpu_count`), wedged stragglers 22-31 h.
  Refs: `docs/diagnostics/0001` §1, backlog #72, perf-boost-rec R1.
- Standing ruling being SUPERSEDED: `diagnostics/0001` §3 DEFERRED a daemon
  pending a trigger ("semantic searches >10/min sustained OR p50 >2s after
  cheap steps"). Reasoning then: deploy facet fast-path first (done, MEM-FIX-0007),
  mmap keeps GGUF warm in page cache, thread cap bounds CPU, a daemon = a second
  system to operate.
- Why supersede NOW (lead ruling, task R1, 2026-07-10): even warm, per-process
  reload is the dominant cost at every QPS; the storm showed concurrency DoS via
  N parallel loads, not just per-call latency; the cheaper steps (thread cap,
  read-only search, embed-once) do not remove the reload itself. Recon
  (`perf-boost-recommendations.md` R1) elevates the daemon from defer to "THE
  win". Lead has ordered the build. This ADR records the decision + the design.

## Decision

One warm OS process holds the Llama embedding model; CLI `neuron search` /
`neuron add` / `batch reembed` send text over a unix socket, get the 768-d
vector back. Fallback = today's in-process load. **Daemon is EMBED-ONLY** (no
SQLite, no search, no DB) — `diagnostics/0001` §3 fence kept.

### Transport

- Unix domain socket: `~/.memory/run/embedd.sock`.
- UDS over TCP: no port allocation; filesystem perms = auth (socket 0600, dir
  0700, user-owned); localhost-only by construction.
- Server: Python stdlib `socketserver.ThreadingMixIn + UnixStreamServer`. Zero
  new deps (fastapi/uvicorn NOT pulled in — see Alternatives).

### Wire protocol — standard length-prefixed framing

NOT a novel protocol. Framing = the same shape as HTTP/2 frames / gRPC
length-prefix / Bernstein netstring: every message = 4-byte big-endian uint32
length N, then N-byte payload. Payload format by message type (JSON for
control, raw float32 blob for vector data — float32 LE = the exact format
`vector_retrieval_two_step_knn.py:154-155` already `struct.pack`s for vec0, so
zero conversion at the store path).

- Handshake (client → server, on connect): JSON
  `{"v":1,"model_path":P,"model_mtime":M,"dims":768}`. Server replies
  `{"ok":true,"model_path":P,"dims":768,"n_threads":T}` OR
  `{"ok":false,"err":"version_skew","got":...}`.
- Embed req: JSON `{"v":1,"op":"embed","texts":[...],"op_type":"query|index"}`
  (batch-capable from day 1 — `embed_batch` for reembed).
- Embed resp: 1 status byte (0=ok) + uint32 count + uint32 dims +
  `count*dims*4` bytes float32 LE. Error: status byte !=0 + length-prefixed
  JSON `{"err":...}`.

### Lifecycle

- **autostart-on-miss:** client connect → refused/no-socket → spawn daemon
  (`memory embed daemon --bg`, double-fork detach), poll socket ready ≤ ~3s,
  retry once. Still down → inproc fallback.
- **single-instance:** pidfile `~/.memory/run/embedd.pid`. On spawn: pidfile
  exists + pid alive + handshake matches → reuse, do not double-spawn. Stale
  (pid dead / socket gone) → clean + respawn.
- **idle shutdown:** daemon tracks last-request ts; idle > `idle_timeout`
  (default 600s, configurable) → graceful exit, unlink socket+pidfile.
- **health probe:** `memory meta health` opens socket, runs handshake, reports
  up/down + model_path + dims + uptime + embed_count.

### Fallback contract — the MUST-never-hang invariant

Every daemon op is bounded: connect timeout (~2s) + embed timeout
(configurable, default ~30s). On ANY failure — no socket, refused, timeout,
version skew, error status, truncated read — fall back to today's
`get_model` + `embed_single`/`embed_batch` IN-PROCESS. Never hang, never crash
the CLI. Emit ONE stderr warning per process on fallback
(`embed daemon unavailable (REASON), using in-process load`).

### Model identity / version stamp (split-brain guard)

Daemon loads ONE model = the central-resolved path
(`~/.memory/models/default.gguf`, same resolution as
`model_loader_lazy_singleton.py:74-94`). Handshake exposes model_path +
mtime + dims. Client compares to its config-resolved model; MISMATCH = skew =
fall back. NEVER silently serve vectors from a different model than the client
expects (this is the silent-quality-rot class — wrong-model vectors look fine
but wreck vector search, cf. R5/#66).

### Thread cap (also storm mitigation)

Daemon sets `n_threads`/`n_threads_batch` from config (bounded, default 2-4),
NOT `cpu_count`. One daemon serializes/limits concurrent embeds instead of N
procs each grabbing 16 cores. (`diagnostics/0001` #2, folded into the daemon
since the daemon is now the single embed path.)

## Capability map (→ tester FIRST, then coder)

### Reuse seams — build ON these, do NOT reinvent

- `embedding/model_loader_lazy_singleton.py` — load logic REUSED verbatim
  inside the daemon (same path resolution :74-94, same Llama ctor :108-114 +
  the new thread-cap). No second loader (B.003).
- `embedding/embed_single_and_batch.py` — `embed_single`/`embed_batch` REUSED
  inside the daemon (same prefix via `task_prefix_search_document_query`, same
  `normalize=True`, same `validate_dimensions`). No second embed impl.
- Client seam (the ONE place the orchestrator switches): today
  `light_search_pipeline_orchestrator.py:540-541` calls
  `embed_single(model, embedding_input, "query")`. New
  `embedding_daemon_client.embed(texts, op_type, config)` plugs in there +
  in the batch-reembed path. Returns the same `list[float]`.

### Invariants

- INV-1: daemon process opens NO `.db`, runs NO SQL, imports NO `search/` /
  `cli/` / `db/` package. Embed-only (enforced by import boundary + test).
- INV-2: identical vectors in vs inproc — for same (model, text, op_type),
  daemon vector == inproc vector (deterministic; nomic embed is deterministic
  at fixed seed). Golden-vector parity test.
- INV-3: fallback is total — every daemon failure mode reaches inproc, CLI
  exit code unchanged vs today.
- INV-4: one resident model copy under concurrency (RSS check).

### Legal / illegal matrix (coder scope fence)

- LEGAL: hold Llama model; call `model.embed()`; read model_path+n_threads
  from config; write socket+pidfile under `~/.memory/run/`; read handshake.
- ILLEGAL: open any `.db`; run SQL; import `search/`,`cli/`,`db/`; write
  neurons/edges; spawn subprocesses (other than the autostart daemon itself);
  bind TCP; load >1 model.

### Acceptance criteria (tester writes reds from these — baseline-FAIL shape)

- AC1 (REVISED 2026-07-10, post-build): original "cold-client full-CLI wall
  <100 ms" was UNACHIEVABLE — Python interp + imports alone ~90 ms (cf.
  `performance-analysis.md` `--help` 0.08 s), full no-embed CLI ~190-230 ms,
  INDEPENDENT of the daemon. It bundled Python-startup floor with daemon perf.
  SPLIT into two measurable ACs:
  - **AC1a (GATE, daemon's contribution):** embed-only wall <100 ms = the
    `embedding_daemon_client.embed([text],"query",cfg)` round-trip (connect +
    handshake + send + inference + float32 receive), measured around the client
    call, NOT the full CLI. Measured ~16 ms warm (vs 240 ms-25 s cold-load).
    Gates the daemon's actual job.
  - **AC1b (INFORMATIONAL, not a gate):** full-CLI cold-client wall ≈ 300 ms,
    documenting the Python-startup + import floor that remains AFTER the daemon
    removes model-load. Not a daemon regression — it is a SEPARATE target
    (lazy/deferred `llama_cpp` import on the non-embed paths). Tracked as a
    follow-up, NOT R1 scope. A future lazy-import fix is what tightens AC1b.
- AC2: 2 concurrent clients → exactly ONE 139 MB RSS copy (`ps`/`pmap`).
  (baseline-FAIL: today 2×139 MB.)
- AC3: `kill -9` daemon mid-op → CLI returns result via inproc fallback, exit
  0, no hang, no traceback. (baseline-FAIL: must not hang.)
- AC4: p95 over 20 back-to-back cold-client searches <500 ms. (baseline-FAIL:
  today p95 ~24.9 s.)
- AC5 (skew): daemon holds model A, client expects model B (different
  path/mtime) → handshake flags skew → client falls back, NEVER returns
  A-vectors for a B-query. (baseline-FAIL: silent wrong-model vectors.)
- AC6 (idle): no requests for `idle_timeout` → daemon exits, socket+pidfile
  unlinked. (baseline-FAIL: leaked process/socket.)
- AC7 (embed-only): daemon process has ZERO open `.db` file handles
  (`lsof`/`/proc/<pid>/fd`). (baseline-FAIL: scope creep into search/DB.)
- AC8 (timeout): daemon embed exceeds timeout → fallback within timeout, no
  hang. (baseline-FAIL: hang.)
- AC9 (parity): daemon vector == inproc vector for a golden (model,text) set.
  (baseline-FAIL: drift.)

## Alternatives considered

- **Reuse `llama-cpp-python[server]` (OpenAI-compatible FastAPI/HTTP
  `/v1/embeddings`), client via `httpx`.** Proven, OpenAI-compatible, gives
  mmap/mlock/thread-cap for free. REJECTED because: (a) it does NOT remove the
  lifecycle work — autostart-on-miss, idle shutdown, health probe, version-skew
  handshake, inproc fallback all still have to be built around it either way;
  (b) pulls fastapi+uvicorn+sse-starlette as new heavy deps for a tool that
  today has ~3; (c) HTTP+JSON encodes a 768-float vector per query (~15 KB text
  vs 3 KB float32) — overhead ~ms, irrelevant vs 12-25 ms inference, but wider
  transport surface; (d) full-server endpoints (completions/chat) exposed
  though unused. Delta vs bespoke = transport only, and stdlib UDS transport is
  trivial. Revisit if a second model or a non-embed consumer appears.
- **`mmap`+`mlock` only, no daemon (the interim).** Cheaper, ships in a day,
  relies on OS page cache (warm runs already 12-25 ms). REJECTED as the
  permanent fix because it does nothing for the concurrency DoS (N procs still
  each init context + inference + contend for cores); the storm was a
  concurrency melt, not just cold latency. KEPT as the interim sub-task + as
  the daemon's own model-load setting (`use_mmap=True`, `use_mlock` config).
- **Move search into the daemon.** REJECTED (`diagnostics/0001` §3 fence).
  Embed-only keeps the daemon replaceable, minimizes skew blast radius, avoids
  a second SQLite opener contending the WAL writer slot.

## Consequences

- Positive: kills per-call model reload (98% of latency) AND the concurrency
  storm (one resident copy, bounded threads). p95 24.9 s → <500 ms target.
- Positive: thread-cap + single instance bound fleet embed CPU by construction.
- Negative: new failure surface — stale socket, version skew, socket perms,
  daemon lifecycle. ALL bounded by the fallback contract (every failure →
  inproc, never hang) + the skew handshake.
- Negative: `mlock` (optional) pins 139 MB RAM while daemon lives. Mitigated by
  idle shutdown (default 10 min) + mlock=opt-in.
- Operational: `memory embed daemon` new CLI surface (start/stop/status);
  `memory meta health` gains a daemon probe. Daemon state under
  `~/.memory/run/` (socket + pidfile) — add to any backup-exclude / store-clean
  logic.
- Follow-ups (separate tasks): R6 embed-once-across-stores (multiplies this
  win); R3 per-query timeout (bounds wedge while daemon builds); R4 read-only
  search (de-noises benchmarks).
- Measurement gate: split `search_latency.retrieval_ms` into embed-load vs
  embed-inference vs bm25 vs vector (currently lumped) so the daemon win is
  provable, not inferred from p95 alone.

## Seam rulings (post tester-reds, 2026-07-10 — names the ADR-left-unnamed)

Tester reds landed (commit 5f74202, 13 RED). 4 seam gaps ruled; tester
assumptions ADOPTED AS-IS (zero test edits). This section seals the names.

### R1 — config schema gains 4 daemon fields (coder adds)

`EmbeddingConfig` + `CONFIG_DEFAULTS["embedding"]` + `VALIDATION_RULES` +
`dict_to_config_schema` gain (ADR left these "configurable" but unnamed):

| dotted path | type | default | constraint | consumer |
|---|---|---|---|---|
| `embedding.daemon_embed_timeout_s` | float | 30.0 | min_exclusive 0 | CLIENT embed timeout (AC8) |
| `embedding.daemon_connect_timeout_s` | float | 2.0 | min_exclusive 0 | CLIENT connect timeout |
| `embedding.daemon_idle_timeout_s` | float | 600.0 | min_exclusive 0 | DAEMON idle shutdown (AC6) |
| `embedding.daemon_n_threads` | int | 4 | min 1 | DAEMON thread cap (n_threads + n_threads_batch, NOT cpu_count) |

Env-override channel (daemon process; single helper `_env_or_config(env, cfg_val)`,
order env > config > default): `MEMORY_EMBED_TIMEOUT_S`,
`MEMORY_EMBED_IDLE_TIMEOUT_S`, `MEMORY_EMBED_N_THREADS`. Config is canonical;
env is ops/test override. (Codebase has no prior env-override pattern; this
introduces it minimally for the 3 daemon tunables only.)

### R2 — AC8 embed-timeout key name

RULE: `config.embedding.daemon_embed_timeout_s` (tester's assumed name).
Match landed red's `hasattr(cfg.embedding, "daemon_embed_timeout_s")` guard
+ monkeypatch. Adopted. NO test change.

### R3 — AC6 idle-timeout override channel

RULE: env `MEMORY_EMBED_IDLE_TIMEOUT_S` overrides `embedding.daemon_idle_timeout_s`.
Matches landed red's `monkeypatch.setenv("MEMORY_EMBED_IDLE_TIMEOUT_S", "1")`.
Adopted. NO test change.

### R4 — daemon server module + embed API

RULE: `memory_cli.embedding.embedding_daemon_server` (FLAT module, parallel to
`embedding_daemon_client` — supersedes the ADR's earlier "daemon/ package"
wording; single module is enough now, package only if it grows).
Embed API: `embed_texts(texts: list[str], op_type: str) -> list[list[float]]`
(reuses `embed_batch` verbatim → AC9 parity holds by construction, INV-2).
Matches landed red's `srv.embed_texts([text], "query")[0]`. Adopted. NO test change.

### R5 — client return shape

RULE: `embedding_daemon_client.embed(texts, op_type, config) -> list[list[float]]`
ALWAYS batch shape (one vec per input text; `texts` always `list[str]`).
Single-query path: `client.embed([q], "query", cfg)[0]`.
Batch/reembed path: `client.embed(texts, "index", cfg)`.
Canonical = batch (consistent with `embed_batch`, unambiguous, matches the
integration test's `[[0.0]*768]` mock). The acceptance `_first_vec` helper
tolerates both but coder implements batch. NO test change.

### Net effect on tasks

- Tester (task-e806361d): assumptions correct, reds STAND AS-IS. No alignment.
- Coder (task-3b814039): ADD the 4 config fields (R1) + build to R2-R5 names.
  Module = `embedding_daemon_server`; client = `embedding_daemon_client`;
  both return `list[list[float]]`.

## Pipeline / next actions (architect seals, then hands off)

1. THIS ADR = sealed contract (protocol + lifecycle + fallback + ACs + seam rulings).
2. Tester reds LANDED (5f74202, 13 RED) — stand as-is.
3. Coder builds daemon + client against the capability map + seam rulings, in assigned files.
4. Reviewer gate: R17 + this ADR's AC matrix live-path proof.
5. Interim (parallel, 1-day): coder mmap-measure sub-task (informs mlock default).
