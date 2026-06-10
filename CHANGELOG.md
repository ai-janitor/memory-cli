# Changelog

All notable changes to memory-cli are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

## [0.4.0] — 2026-06-10

Minor bump (semver): new feature (central model resolution, MEM-FIX-0003) + additive API field (`meta.vector_unavailable_reason`, MEM-FIX-0002) + new `neuron tree` verb. No breaking changes to existing data or search behavior; `model download --local` removal is pre-1.0 cleanup of a flag superseded by central resolution.

### Added
- **`meta.vector_unavailable_reason`** — embedding outages now carry the exception class+message (e.g. `FileNotFoundError: Embedding model not found: ...`) in search meta instead of failing silent behind a bare `vector_unavailable: true`. `null` when vectors are available. (MEM-FIX-0002 / backlog #68)
- **Central model resolution** — explicit config `embedding.model_path` wins if the file exists; otherwise the loader falls back to the central `~/.memory/models/default.gguf`. Fresh local stores no longer silently degrade to BM25-only because their baked per-store model path is absent. (MEM-FIX-0003 / backlog #66)
- **`memory neuron tree <id>`** — recursive multi-hop tree/lineage traversal verb (MEM-FEAT-0001 / backlog #64). Walks descendants (`--direction down`), ancestors (`--direction up`), or both from a root neuron, depth-bounded (`--depth`, default 10), optionally filtered by edge reason (`--type`), cycle-safe via visited set. New module `src/memory_cli/traversal/tree_recursive_lineage.py`; exported from `traversal/__init__.py`; registered in neuron noun handler.

### Changed
- **`memory init` writes `embedding.model_path: null`** instead of baking a per-store `<store>/models/default.gguf` path; `model_path` is no longer a required config field. Resolution defers to the central model at load time. (MEM-FIX-0003)

### Removed
- **`memory model download --local` + auto-symlink to local store** — superseded by central model resolution; one central model serves all stores. (MEM-FIX-0003)

### Fixed
- **`--global` search from a project dir used the LOCAL store's config/model** — the retrieval stage called bare `load_config()` (ancestor walk) instead of the resolved store's config; config is now threaded from `get_layered_connections_with_config` through `light_search`. (MEM-FIX-0001 / backlog #67)
- **`meta stats` / `meta check` crash on `model_path: null`** — `os.path.basename(None)` TypeError on stores initialized post-central-resolution; None-guarded with a `"none"` display sentinel, drift compare only fires when the DB has a model row. (MEM-FIX-0005)
- **Flaky column-existence caches keyed by `id(conn)`** (`edge/edge_list_by_neuron_direction.py`, `search/spreading_activation_bfs_linear_decay.py`). CPython reuses object ids after a connection is GC'd, so the module-level `id(conn)` cache could leak a stale schema flag onto a later same-id connection with a different schema — a non-deterministic cross-test failure (e.g. `test_edge_provenance`). Now query `PRAGMA table_info` each call (a fast local op); correctness over one PRAGMA. (Surfaced while adding `neuron tree`.)

### Known issues
- Test suite has residual pre-existing non-deterministic flakiness (e.g. time-based `test_consolidate_mixed_states`) unrelated to the above — see backlog. Baseline-green should be checked multi-run.
