# Changelog

All notable changes to memory-cli are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- **`memory neuron tree <id>`** — recursive multi-hop tree/lineage traversal verb (MEM-FEAT-0001 / backlog #64). Walks descendants (`--direction down`), ancestors (`--direction up`), or both from a root neuron, depth-bounded (`--depth`, default 10), optionally filtered by edge reason (`--type`), cycle-safe via visited set. New module `src/memory_cli/traversal/tree_recursive_lineage.py`; exported from `traversal/__init__.py`; registered in neuron noun handler.

### Fixed
- **Flaky column-existence caches keyed by `id(conn)`** (`edge/edge_list_by_neuron_direction.py`, `search/spreading_activation_bfs_linear_decay.py`). CPython reuses object ids after a connection is GC'd, so the module-level `id(conn)` cache could leak a stale schema flag onto a later same-id connection with a different schema — a non-deterministic cross-test failure (e.g. `test_edge_provenance`). Now query `PRAGMA table_info` each call (a fast local op); correctness over one PRAGMA. (Surfaced while adding `neuron tree`.)

### Known issues
- Test suite has residual pre-existing non-deterministic flakiness (e.g. time-based `test_consolidate_mixed_states`) unrelated to the above — see backlog. Baseline-green should be checked multi-run.
