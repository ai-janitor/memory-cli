---
type: reference
title: memory-cli Dead Code & Unused Inventory — Action Catalog
description: Action layer over object-model.md's unused tally — what to DELETE, what to WIRE, what to DEFER, with per-unit evidence and risk.
tags: [dead-code, unused, cleanup, decision, reference, architecture]
timestamp: 2026-07-09
---

# Dead Code & Unused — Action Catalog

## Overview

- Action layer on top of `docs/object-model.md` (§Unused objects). Read that first — it holds the full object model + wiring status. This doc turns the inventory into decisions: DELETE / WIRE / DEFER per unit.
- Two buckets: **Class A** = fully dead (no product path, no test) → delete candidates. **Class B** = product-unused but tested (module exists + has tests, but no live CLI verb reaches it) → real judgement call each.
- Verified 2026-07-09 via grep (module + real function names) across `src/` + `tests/`, cross-checked against `MIGRATION_REGISTRY`, CLI verb maps, orchestrator import lists. Migration runner uses **explicit imports** (no glob/importlib/listdir — verified `grep glob\|listdir\|iterdir\|importlib src/memory_cli/db/` → empty), so unregistered files are genuinely unreachable.

---

## Class A — fully-dead delete candidates (5)

All 5 = duplicate/orphan files, zero live import, zero test. Delete-safe.

| file | evidence | risk |
|------|----------|------|
| `src/memory_cli/db/migrations/v004_add_edge_provenance.py` | NOT imported by `migrations/__init__.py` (registers TWIN `v005_add_edge_provenance` at :36). Only refs = own header comment + `egg-info/SOURCES.txt`. DDL identical to registered v005 twin (`ALTER TABLE edges ADD COLUMN provenance/confidence` — verified :41,:50 both files). | **none** — never imported; explicit registry, no glob loader. Registered chain 1–9 stays gap-free. |
| `src/memory_cli/db/migrations/v005_add_consolidated_column.py` | NOT imported (registry registers TWIN `v006_add_consolidated_column` at :37). Only refs = own header + SOURCES.txt. | none — off-by-one dup of registered v006. |
| `src/memory_cli/db/migrations/v006_add_edge_types_and_canonical_reason.py` | NOT imported (registry registers TWIN `v007_add_edge_types_and_canonical_reason` at :38). Only refs = own header + SOURCES.txt. Note: its header comment still reads `v006_...` inside the registered v007 file too (stale comment, cosmetic). | none — off-by-one dup of registered v007. |
| `src/memory_cli/db/migrations/v007_add_search_latency_table.py` | NOT imported (registry registers TWIN `v008_add_search_latency_table` at :39). Only refs = own header + SOURCES.txt. | none — off-by-one dup of registered v008. |
| `src/memory_cli/edge/edge_type_normalize_janitor.py` | Zero refs anywhere (`grep -rn edge_type_normalize_janitor src/` → own header line 2 + `egg-info/SOURCES.txt` only). NOT in `edge/__init__` (which imports the live `edge_normalize_janitor_pass`). No test. Dup of live janitor. | none — never imported. |

Signature: author renamed migration files with an off-by-one version bump, registered only the higher-numbered twin, left the stale lower twin on disk. Same pattern 4× + one dup edge janitor.

**Delete action:** `git rm` the 5 files. `egg-info/SOURCES.txt` is a build artifact — regenerates on next `pip install -e .`/build; do not hand-edit.

---

## Class B — decision table (product-unused but tested, ~20 units)

Verified: no CLI verb/flag refs any of these — `grep heavy|ingest|timeline|link_flag src/memory_cli/cli/` → empty (only doc-comment mentions of "timeline" in `traversal/__init__.py`).

| unit | path | tested | action | rationale |
|------|------|--------|--------|-----------|
| ingestion package (9 mods: `ingest_orchestrator`, `consolidation_orchestrator`, `consolidation_extraction`, `haiku_extraction_entities_facts_rels`, `jsonl_parser_claude_code_sessions`, `message_assembler_transcript`, `session_dedup_guard_by_session_id`, `neuron_and_edge_creator_from_extraction`, `capture_context_star_topology_edges`) | `src/memory_cli/ingestion/` | yes | **WIRE** | Whole intended subsystem = conversation capture (Claude Code jsonl → Haiku extract → graph write). Named in CLAUDE.md as a runtime product feature. Missing only an `ingest` noun. Real feature, not scaffolding. `meta consolidate` uses its own inline SQL — does NOT reach these, so they are dark today. |
| heavy search package (5 mods: `heavy_search_orchestrator`, `haiku_query_expansion_terms`, `haiku_rerank_by_neuron_ids`, `heavy_search_merge_and_paginate`, `haiku_api_key_resolution`) | `src/memory_cli/search/heavy/` | yes | **WIRE** | Intended `neuron search --heavy` (Haiku expand+rerank over the live light pipeline). Complete + tested, missing only a flag/verb. Real planned feature; light pipeline already the fast path so this is additive. |
| `link_flag_atomic_neuron_plus_edge` (`link_flag_atomic_create`) | `src/memory_cli/edge/link_flag_atomic_neuron_plus_edge.py` | yes | **WIRE** | Atomic create-neuron-plus-edge in one txn — a natural `edge link` / `neuron link` verb. Exported by `edge/__init__`, tested, no verb calls it. Small surface, clear intent → wire, don't drop. |
| `meta_check_orphans_and_anomalies` (`run_meta_check`) | `src/memory_cli/integrity/meta_check_orphans_and_anomalies.py` | yes | **WIRE** | DB-health audit (orphans/anomalies). `meta health` today runs inline latency SQL, NOT this richer check. Wire into `meta health` or a `meta check` verb — health surface already exists, this is the intended body. |
| `first_vector_write_seed_metadata` (`seed_metadata_on_first_vector`) | `src/memory_cli/integrity/first_vector_write_seed_metadata.py` | yes | **WIRE** | Seeds model/dim meta on first vector write — a correctness primitive the drift guards depend on. Only ref = `integrity/__init__` export (:33), NOT called in `vector_storage_vec0_write`. Wire into the vector write path; without it the drift checks below have no baseline. |
| `startup_drift_check_model_and_dims` (`run_startup_drift_check`) | `src/memory_cli/integrity/startup_drift_check_model_and_dims.py` | yes | **DEFER** | Startup guard: model/dim drift on entrypoint dispatch. Real safety net but adds latency to every invocation + depends on first-vector seed (above) being wired first. Defer until seed lands + a perf budget is set. |
| `model_drift_stale_vector_marking` (`handle_model_drift`, `is_vector_dependent_operation`) | `src/memory_cli/integrity/model_drift_stale_vector_marking.py` | yes | **DEFER** | Marks vectors stale on model change. Only reachable via the startup guard → defer with it (same dependency chain). |
| `dimension_drift_hard_block` (`handle_dimension_drift`) | `src/memory_cli/integrity/dimension_drift_hard_block.py` | yes | **DEFER** | Hard-block on dim mismatch. Same startup-guard chain → defer together. |
| `timeline_walk_forward_backward` (`timeline_walk`) | `src/memory_cli/traversal/timeline_walk_forward_backward.py` | yes | **DEFER** | Chronological fwd/back walk from a reference neuron. Exported by `traversal/__init__` (:25), no `timeline` verb. Plausible-future nav feature but lower demand than ingest/heavy, and `neuron tree` + search-temporal-decay already cover most temporal need. Defer until a concrete use surfaces; drop if none by next cleanup. |

---

## Summary

- **Class A — fully dead: 5.** Confirmed dead:
  - `db/migrations/v004_add_edge_provenance.py`
  - `db/migrations/v005_add_consolidated_column.py`
  - `db/migrations/v006_add_edge_types_and_canonical_reason.py`
  - `db/migrations/v007_add_search_latency_table.py`
  - `edge/edge_type_normalize_janitor.py`
- **Class B — decision tally: 5 WIRE / 4 DEFER / 0 DELETE** (counting the ingestion + heavy packages as one unit each). Grouped mod count: WIRE reaches ~16 modules (9 ingest + 5 heavy + link_flag + meta_check + first-vector), DEFER reaches ~4 (3 integrity drift + timeline).

### Recommended first actions
1. **Delete Class A now** — 5 files, zero risk, `git rm`. Lowest-effort win; kills the off-by-one migration trap before someone edits the wrong twin.
2. **WIRE first-vector seed → vector write path** — small, unblocks the deferred drift guards later.
3. **WIRE `edge link` verb** for `link_flag_atomic_create` — smallest feature, immediate value.
4. **Spec the `ingest` noun + `search --heavy` flag** — the two real planned subsystems; largest value, needs design (verb surface, Haiku key handling). Route through maintain-operate-orchestration.

### Uncertainty flags
- Class B "unwired" assumes no runtime string/importlib dispatch — verified absent statically (`grep importlib src/memory_cli/db/` empty; CLI verb maps grepped). A dynamic loader elsewhere would be `(unverified)` but none found.
- `meta consolidate` inline-SQL path — **VERIFIED 2026-07-09 line-by-line** (`codebase trace_path` + read): `handle_consolidate` (`meta_noun_handler.py:300-356`) runs its own `SELECT`/`UPDATE` directly on `neurons` (:328-336), imports no `ingestion` mod; `consolidate_all` / `consolidate_neuron` (`ingestion/consolidation_orchestrator.py`) both show `callers:[]`. Two separate consolidation impls exist — live simple-timestamp one + dead Haiku-extract one. Ingestion pkg confirmed dark.
- Call-graph evidence: `ingest_session`, `heavy_search`, `timeline_walk`, `run_startup_drift_check` all `in_degree:0` / `callers:[]` (verified via `codebase trace_path` 2026-07-09). Refs outside tests = `__init__` exports only.
