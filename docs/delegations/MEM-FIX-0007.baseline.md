# MEM-FIX-0007 — baseline suite (regression-fence anchor)

- **Date:** 2026-07-09
- **Cmd:** `uv run pytest tests/ -q` ×5 (multi-run per CLAUDE.md latent-flakiness rule)
- **Anchor count:** 1848 tests.

| run | result | load |
|---:|---|---:|
| 1 | 1 failed, 1847 passed | 7.06 |
| 2 | 1848 passed | 17.49 |
| 3 | 1848 passed | 22.52 |
| 4 | 1848 passed | 35.71 |
| 5 | 1848 passed | 29.52 |

- **Known-flaky (pre-existing, NOT this change):** `tests/db/test_consolidated_migration_v005.py::TestConsolidateLogic::test_consolidate_mixed_states` — failed 1/5, passed 4/5. Unrelated to search. Walk-past: ACCEPT + track as flaky-test backlog item.
- **Post-change requirement:** `post_count >= 1848 + 7` (AC-1..7) = **>= 1855**, flaky test tolerated (pass on rerun), no NEW failures.
