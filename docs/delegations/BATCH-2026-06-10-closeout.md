# CLOSEOUT — MEM-FIX batch 2026-06-10

- ruling: accept ×4 (gates at MEM-FIX-*.gate.md)
- branch: docs/knowledge-architecture

## Commits
- `88b8b6a` MEM-FIX-0001 — --global config threading (backlog #67)
- `1183ced` MEM-FIX-0002 — meta.vector_unavailable_reason (backlog #68)
- `17a0553` MEM-FIX-0003 — central model resolution (backlog #66)
- `1295697` MEM-FIX-0005 — None-guard model_path in meta stats/check
- `6658159` release: v0.4.0 (CHANGELOG + pyproject)

## Split note
- 0001/0002 shared 3 files (orchestrator, neuron_noun_handler, test_light_search_pipeline)
- commit 1 = 0002 lines stripped, 0001-only tree; 37 tests passed at that point; finals restored for commit 2

## Version
- 0.3.7 → 0.4.0. Minor: new feature (0003) + additive meta field (0002) + neuron tree. No breaking.
- editable uv tool reinstalled → `memory --version` = 0.4.0

## Smoke (temp HOME, real init)
- `memory init --global` → model_path null store, no crash
- `memory neuron search "test" --json` → meta carries `vector_unavailable_reason` (FileNotFoundError, no model in temp HOME) — 0002 live via installed binary
- `memory meta stats --json` → status ok, config_model_name "none" — 0005 live
- `git status` clean except intentionally left: `docs/delegations/MEM-FIX-0004.spec.md` (unit not in batch), this closeout file
- stash@{0} daemon-work-wave2 intact

## Suite
- full suite ~1841 tests (dirty-tree gate runs; clean HEAD baseline 1826 ×7 green)
- known flake: `tests/db/test_consolidated_migration_v005.py::TestConsolidateLogic::test_consolidate_mixed_states` — time-boundary, fails ~1/9 full runs, passes isolated; PRE-EXISTING (gate D1)

## Backlog
- filed: `bugs/flaky-testconsolidatemixedstates-time-boundary` (type bug, priority low) — flaky-test stabilization
