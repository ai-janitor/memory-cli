---
type: reference
title: memory-cli Object Model
description: Account-for-object catalog of every first-class product object in memory-cli, with wiring status and dead/unused-object detection.
tags: [object-model, reference, architecture, dead-code, unused]
timestamp: 2026-07-09
---

# memory-cli Object Model

## Overview

- Graph memory CLI. Noun-verb grammar `memory <noun> <verb>`.
- Data model = 8 SQLite tables (neurons, edges, tags, neuron_tags, attr_keys, neuron_attrs, meta, neurons_fts) + runtime vec0 vector table.
- Runtime layers: config/store resolution -> DB connection + sqlite-vec ext + migration runner -> noun handlers dispatch verb -> domain package (neuron/edge/tag/search/embedding/...) -> output envelope.
- Nouns wired live: `neuron` `edge` `tag` `attr` `gate` `batch` `meta` `model` `manpage` + top-level `init`.
- Search = light pipeline (BM25 + vector KNN + spreading-activation, RRF-fused, temporal/salience/tag-affinity scored). Heavy (Haiku) pipeline built + tested but NOT wired.
- Two whole subsystems built + tested but unwired: `ingestion/` (conversation capture) and `search/heavy/` (Haiku expand/rerank). Most of `integrity/` (startup drift guard, DB health check) also unwired.
- Dead code: 4 off-by-one duplicate migration files + 1 duplicate edge janitor module, never imported, never tested.

---

## Object catalog

### Data model (SQLite schema — v001 baseline)
Path: `src/memory_cli/db/migrations/v001_baseline_all_tables_indexes_triggers.py`

| object | purpose | wiring | status |
|--------|---------|--------|--------|
| `neurons` table (:74) | content node = the memory card | written by neuron add/update/import/ingest; read by get/list/search | live |
| `edges` table (:131) | directed weighted link between neurons | edge noun, traversal, spreading-activation | live |
| `tags` + `neuron_tags` (:163,:179) | categorical labels, many-to-many | tag noun, auto-tag, tag-affinity scoring | live |
| `attr_keys` + `neuron_attrs` (:202,:221) | key-value metadata on neurons | attr noun, registries | live |
| `meta` table (:53) | schema_version, model info, fingerprint, manifesto, timestamps | migration runner, meta noun, integrity | live |
| `neurons_fts` fts5 virtual (:250) + 5 sync triggers | full-text index for BM25 | auto-synced by triggers; read by bm25 retrieval | live |
| vec0 vector table (runtime) | 768-d embedding store (sqlite-vec) | written by vector_storage_vec0_write; read by vector KNN | live |

### DB layer
Dir: `src/memory_cli/db/`

| object | purpose | wiring | status |
|--------|---------|--------|--------|
| `connection_setup_wal_fk_busy` | open conn, WAL, FK, busy timeout | db/__init__, gate store discovery | live |
| `extension_loader_sqlite_vec` | load sqlite-vec extension | db_connection_from_global_flags, init | live |
| `migration_runner_single_transaction` | run pending migrations atomically | connection setup path | live |
| `migrations/__init__` MIGRATION_REGISTRY | version->apply map (v001..v009) | migration runner | live |
| `migrations/v001..v009` (registered set) | schema DDL steps | registry | live |
| `schema_version_reader` (read_schema_version) | current schema version | init, meta, db_connection, integrity | live |
| `store_fingerprint_read_and_cache` | store identity fingerprint | meta, scoped handle, init | live |

### Config / stores
Dir: `src/memory_cli/config/`

| object | purpose | wiring | status |
|--------|---------|--------|--------|
| `config_loader_and_validator` | load+validate config | config/__init__, ingestion haiku | live |
| `config_path_resolution_ancestor_walk` | git-style ancestor walk for store | db_connection, gate, store discovery | live |
| `config_schema_and_defaults` | schema + default values | loader, init | live |
| `init_create_global_or_project_store` | scaffold new store | `init` command | live |
| `store_registry` (list_stores) | enumerate known stores | meta stores, gate | live |

### Neuron domain
Dir: `src/memory_cli/neuron/`

| object | purpose | wiring | status |
|--------|---------|--------|--------|
| `neuron_add_with_autotags_and_embed` | create neuron + autotag + embed | neuron add | live |
| `neuron_get_by_id` | fetch one | neuron get | live |
| `neuron_list_filtered_paginated` | list with filters | neuron list | live |
| `neuron_update_content_tags_attrs` | mutate neuron | neuron update | live |
| `neuron_archive_and_restore` | soft archive/restore | neuron archive/restore, prune | live |
| `neuron_delete_hard` | hard delete | neuron delete | live |
| `neuron_prune_by_lru_age` | LRU/age pruning | neuron prune | live |
| `auto_tag_capture_timestamp_and_project` | inject captured_at + project tags | neuron add | live |
| `project_detection_git_or_cwd` | derive project id | auto-tag, add, link_flag | live |

### Edge domain
Dir: `src/memory_cli/edge/`

| object | purpose | wiring | status |
|--------|---------|--------|--------|
| `edge_add_with_reason_and_weight` | create edge | edge add | live |
| `edge_list_by_neuron_direction` | list edges | edge list | live |
| `edge_remove_by_source_target` | delete edge | edge remove | live |
| `edge_splice_atomic_insert_between` | insert node between A-B | edge splice | live |
| `edge_update_by_source_target` | mutate edge | edge update | live |
| `edge_normalize_janitor_pass` (edge_normalize) | normalize edge types | edge normalize | live |
| `link_flag_atomic_neuron_plus_edge` (link_flag_atomic_create) | atomic create neuron + link | edge/__init__ export only | **UNUSED (tested)** |
| `edge_type_normalize_janitor` | duplicate of janitor_pass | none | **DEAD** |

### Tag / attr registries
Dir: `src/memory_cli/registries/`

| object | purpose | wiring | status |
|--------|---------|--------|--------|
| `tag_registry_crud_normalize_autocreate` | tag CRUD + normalize | tag noun, tag-filter | live |
| `attr_registry_crud_normalize_autocreate` | attr CRUD + normalize | attr noun, link_flag | live |
| `registry_lookup_by_name_or_id` | resolve name/id | registries/__init__ | live |
| `tag_filter_and_or_primitives` | AND/OR tag filter expr | tag list, search filter | live |

### Embedding
Dir: `src/memory_cli/embedding/`

| object | purpose | wiring | status |
|--------|---------|--------|--------|
| `model_loader_lazy_singleton` (get_model) | lazy llama-cpp model | add, batch, model noun | live |
| `embed_single_and_batch` | produce vectors | add, reembed | live |
| `embedding_input_content_plus_tags` | build embed input text | add, reembed | live |
| `task_prefix_search_document_query` | search/document task prefixes | embed path | live |
| `dimension_enforcement_768` | enforce 768-d | embed, vector write | live |
| `vector_storage_vec0_write` | write vec0 row | reembed, dim-enforce, integrity seed | live |
| `stale_and_blank_vector_detection` | find blank/stale vectors | batch reembed | live |
| `batch_reembed_blank_and_stale` (batch_reembed) | bulk re-embed | batch reembed | live |

### Search — light pipeline
Dir: `src/memory_cli/search/` (orchestrated by `light_search_pipeline_orchestrator`, wired to `neuron search`)

| object | purpose | wiring | status |
|--------|---------|--------|--------|
| `light_search_pipeline_orchestrator` | run full light pipeline | neuron search handler | live |
| `bm25_retrieval_fts5_match` | FTS5 keyword retrieval | orchestrator | live |
| `vector_retrieval_two_step_knn` | vec0 KNN retrieval | orchestrator | live |
| `spreading_activation_bfs_linear_decay` | graph BFS activation | orchestrator | live |
| `rrf_fusion_rank_based_k60` | reciprocal-rank fusion | orchestrator | live |
| `temporal_decay_exponential_halflife` | recency decay factor | orchestrator | live |
| `salience_scoring_access_metrics` | access-based salience | orchestrator | live |
| `tag_affinity_scoring_shared_tags` | shared-tag boost | orchestrator | live |
| `tag_filter_post_activation` | post-filter by tags | orchestrator | live |
| `final_score_combine_and_rank` | combine + rank | orchestrator | live |
| `explain_scoring_breakdown` | per-result score explain | orchestrator, final score | live |
| `search_result_hydration_and_envelope` | hydrate + envelope | orchestrator | live |
| `fuzzy_fallback_levenshtein` | fuzzy fallback on empty | orchestrator (fallback) | live |

### Search — heavy pipeline
Dir: `src/memory_cli/search/heavy/` — Haiku-backed expand/rerank

| object | purpose | wiring | status |
|--------|---------|--------|--------|
| `heavy_search_orchestrator` | run heavy pipeline | heavy/__init__ only; NO CLI verb/flag | **UNUSED (tested)** |
| `haiku_query_expansion_terms` | LLM query expansion | orchestrator (unwired) | **UNUSED (tested)** |
| `haiku_rerank_by_neuron_ids` | LLM rerank | orchestrator (unwired) | **UNUSED (tested)** |
| `heavy_search_merge_and_paginate` | merge + paginate | orchestrator (unwired) | **UNUSED (tested)** |
| `haiku_api_key_resolution` | resolve Anthropic key | heavy path (unwired) | **UNUSED (tested)** |

### Traversal
Dir: `src/memory_cli/traversal/`

| object | purpose | wiring | status |
|--------|---------|--------|--------|
| `tree_recursive_lineage` | multi-hop lineage tree | neuron tree | live |
| `goto_follow_edges_single_hop` (goto_follow_edges) | single-hop edge follow | used by tree (no own CLI verb) | live (indirect) |
| `timeline_walk_forward_backward` (timeline_walk) | temporal fwd/back walk | traversal/__init__ export only; NO CLI verb | **UNUSED (tested)** |

### Gate (topology entry points)
Dir: `src/memory_cli/gate/`

| object | purpose | wiring | status |
|--------|---------|--------|--------|
| `gate_compute_densest_node` | pick densest node = gate | gate show/register, store discovery | live |
| `gate_neighborhood_discovery` | neighborhood around gate | gate show | live |
| `gate_register_deregister` | cross-store gate register | gate register/deregister | live |
| `store_discovery_all_local_gates` | walk stores, collect gates | gate show | live |

### Integrity
Dir: `src/memory_cli/integrity/`

| object | purpose | wiring | status |
|--------|---------|--------|--------|
| `meta_stats_db_summary` (gather_meta_stats) | DB counts/summary | meta info | live |
| `meta_check_orphans_and_anomalies` (run_meta_check) | orphan/anomaly audit | none (meta health does inline latency SQL, not this) | **UNUSED (tested)** |
| `startup_drift_check_model_and_dims` (run_startup_drift_check) | model/dim drift guard | NOT called by entrypoint dispatch | **UNUSED (tested)** |
| `model_drift_stale_vector_marking` (handle_model_drift, is_vector_dependent_operation) | mark stale on model change | unwired | **UNUSED (tested)** |
| `dimension_drift_hard_block` (handle_dimension_drift) | hard-block on dim mismatch | unwired | **UNUSED (tested)** |
| `first_vector_write_seed_metadata` (seed_metadata_on_first_vector) | seed model/dim meta on first vector | NOT called in vector write path | **UNUSED (tested)** |

### Export / import
Dir: `src/memory_cli/export_import/`

| object | purpose | wiring | status |
|--------|---------|--------|--------|
| `export_neurons_tags_edges_to_json` (export_neurons) | dump graph to JSON | batch export | live |
| `export_envelope_format_v1` | export envelope schema | export path | live |
| `import_validate_structure_refs_dims` | validate import payload | import path | live |
| `import_write_transactional` (import_neurons) | transactional import | batch import | live |
| `conflict_handler_skip_overwrite_error` | import conflict policy | import write | live |
| `graph_document_loader_yaml_with_ref_resolution` | YAML graph-doc loader | batch load | live |

### Ingestion (conversation capture)
Dir: `src/memory_cli/ingestion/` — whole subsystem; NO CLI noun/verb wires it (`meta consolidate` runs its own inline SQL, does not call these)

| object | purpose | wiring | status |
|--------|---------|--------|--------|
| `ingest_orchestrator` | drive conversation ingest | none (no CLI) | **UNUSED (tested)** |
| `consolidation_orchestrator` | drive consolidation | none | **UNUSED (tested)** |
| `consolidation_extraction` | extract consolidations | orchestrator (unwired) | **UNUSED (tested)** |
| `haiku_extraction_entities_facts_rels` | Haiku entity/fact/rel extract | orchestrator (unwired) | **UNUSED (tested)** |
| `jsonl_parser_claude_code_sessions` | parse CC session jsonl | orchestrator (unwired) | **UNUSED (tested)** |
| `message_assembler_transcript` | assemble transcript | orchestrator (unwired) | **UNUSED (tested)** |
| `session_dedup_guard_by_session_id` | dedup by session id | orchestrator (unwired) | **UNUSED (tested)** |
| `neuron_and_edge_creator_from_extraction` | write extracted graph | orchestrator (unwired) | **UNUSED (tested)** |
| `capture_context_star_topology_edges` | star-topology edges | orchestrator (unwired) | **UNUSED (tested)** |

### CLI layer
Dir: `src/memory_cli/cli/`

| object | purpose | wiring | status |
|--------|---------|--------|--------|
| `entrypoint_and_argv_dispatch` (main, register_noun) | argv parse + noun dispatch registry | console script `memory` | live |
| `init_command_top_level_exception` | `init` command + top exception | entrypoint | live |
| `global_flags_format_config_db` | parse --format/--config/--db/--global | entrypoint | live |
| `output_envelope_json_and_text` (Result) | JSON/text output envelope | every handler | live |
| `scoped_handle_format_and_parse` | store-scope resolution | neuron/other handlers | live |
| `help_system_three_levels` | 3-level help | entrypoint | live |
| `exit_codes_0_1_2` | exit code constants | entrypoint | live |
| `db_connection_from_global_flags` | conn+config from flags | all handlers | live |
| `arg_parse_extract_positional_and_flags` | positional/flag split | handlers | live |
| noun_handlers: `neuron` `edge` `tag` `attr` `gate` `batch` `meta` `model` `manpage` | register nouns + verbs | self-register on import | live |

CLI surface (live verbs):
- `neuron`: add get list update archive restore search prune delete tree
- `edge`: add list remove splice update normalize
- `tag`: add list remove audit
- `attr`: add list remove
- `gate`: show register deregister
- `batch`: export import load reembed
- `meta`: info stats manifesto fingerprint stores consolidate health
- `model`: download
- `manpage`: overview how-to architecture people search graph-docs stores recipes front-door tag-conventions
- top-level: `init`

---

## Unused objects

`class a` = fully dead (no product path + no test). `class b` = product-unused but test-referenced. `class c` = live (not listed here).

| object | path | evidence | class | recommendation |
|--------|------|----------|-------|----------------|
| `v004_add_edge_provenance` | src/memory_cli/db/migrations/v004_add_edge_provenance.py | NOT in MIGRATION_REGISTRY (registry uses v005_add_edge_provenance); only ref = SOURCES.txt build artifact | a | delete — off-by-one dup of the registered v005 |
| `v005_add_consolidated_column` | src/memory_cli/db/migrations/v005_add_consolidated_column.py | NOT registered (registry uses v006_add_consolidated_column); only SOURCES.txt | a | delete — dup |
| `v006_add_edge_types_and_canonical_reason` | src/memory_cli/db/migrations/v006_add_edge_types_and_canonical_reason.py | NOT registered (registry uses v007_...); only SOURCES.txt + v007 header comment | a | delete — dup |
| `v007_add_search_latency_table` | src/memory_cli/db/migrations/v007_add_search_latency_table.py | NOT registered (registry uses v008_...); only SOURCES.txt | a | delete — dup |
| `edge_type_normalize_janitor` | src/memory_cli/edge/edge_type_normalize_janitor.py | zero refs anywhere (grep `--include=*.py`); NOT in edge/__init__ (which imports edge_normalize_janitor_pass), NO test | a | delete — dup of edge_normalize_janitor_pass |
| `link_flag_atomic_neuron_plus_edge` | src/memory_cli/edge/link_flag_atomic_neuron_plus_edge.py | exported by edge/__init__ but no CLI verb calls link_flag_atomic_create; has test | b | wire an `edge link`/`neuron link` verb, or drop |
| `timeline_walk_forward_backward` | src/memory_cli/traversal/timeline_walk_forward_backward.py | only traversal/__init__ export; no `timeline` CLI verb; has test | b | add `neuron timeline` verb or drop |
| `search/heavy/*` (5 modules) | src/memory_cli/search/heavy/ | heavy_search_orchestrator has no caller outside heavy/__init__; no CLI flag/verb; all tested | b | wire `neuron search --heavy` or defer |
| `ingestion/*` (9 modules) | src/memory_cli/ingestion/ | no consumer outside ingestion/; no CLI noun; meta consolidate does inline SQL, not these; all tested | b | add `ingest` noun or defer (planned conversation-capture feature) |
| `meta_check_orphans_and_anomalies` | src/memory_cli/integrity/meta_check_orphans_and_anomalies.py | run_meta_check has no caller; `meta health` does inline latency SQL instead; tested | b | wire into `meta health` (or a `meta check`) |
| `startup_drift_check_model_and_dims` | src/memory_cli/integrity/startup_drift_check_model_and_dims.py | run_startup_drift_check not called by entrypoint dispatch; tested | b | wire into dispatch startup guard or drop |
| `model_drift_stale_vector_marking` | src/memory_cli/integrity/model_drift_stale_vector_marking.py | handle_model_drift / is_vector_dependent_operation no caller; tested | b | wire into startup guard or drop |
| `dimension_drift_hard_block` | src/memory_cli/integrity/dimension_drift_hard_block.py | handle_dimension_drift no caller; tested | b | wire into startup guard or drop |
| `first_vector_write_seed_metadata` | src/memory_cli/integrity/first_vector_write_seed_metadata.py | seed_metadata_on_first_vector not called in vector write path; tested | b | wire into vector_storage_vec0_write or drop |

Notes / uncertainty:
- `goto_follow_edges_single_hop` = LIVE indirectly (tree_recursive_lineage:28,68,108 imports+calls goto_follow_edges); no own CLI verb — not unused.
- The 4 dead migrations + dead edge janitor share a signature: an author renamed files with an off-by-one version bump (v00N and v00N+1) and only registered/imported one. The stale twin was never removed.
- class b determinations assume the entrypoint dispatch does not lazily import these by string — grep found no such dynamic import, but a runtime importlib call could exist `(unverified)`. Direct static refs are absent.
- Detection method: grep static refs (module + real function names) across src/tests, cross-checked against MIGRATION_REGISTRY, register_noun verb maps, and orchestrator import lists. codebase graph orphan query returned empty (property mismatch) so grep+read was the primary method.

---

## Summary tally

- Total objects catalogued: ~95 (7 schema + 76 product modules across 14 domains + CLI layer + verb surface).
- Live: ~76 modules.
- **Fully dead (class a): 5** — 4 duplicate migrations + 1 duplicate edge janitor.
- **Product-unused but tested (class b): ~20 modules** — link_flag (1), timeline (1), search/heavy (5), ingestion (9), integrity guard/check (5). Two of these are whole planned subsystems (ingestion, heavy search).
- Live CLI nouns: 9 + `init`.
