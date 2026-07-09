# MEM-FIX-0007 — opus gate record

- **Gate:** independent opus verifier (adversarial; did not write the code)
- **Date:** 2026-07-09
- **Fix:** facet-scoped search fast-path — wire `--type`/`--tag`, skip embed; heavy stays semantic
- **Commits:** 647d47e (impl + AC-1..7), 9d866cb (INV-B heavy semantic=True + 2 guards)
- **Spec:** `docs/delegations/MEM-FIX-0007.spec.md`
- **Baseline anchor:** `docs/delegations/MEM-FIX-0007.baseline.md` — 1848 tests; known-flaky `test_consolidate_mixed_states` (unrelated, tolerate).

## Suite lines

- **Baseline (doer, ×5):** `1848 passed` (run 1: 1 flaky fail on `test_consolidate_mixed_states`, passed 4/5).
- **Post-suite (verifier, HEAD 9d866cb):** `1859 passed, 843 warnings in 38.26s` — 0 failures, flaky test passed this run. 1859 = 1848 + 9 AC + 2 heavy guard. Requirement `>= 1858` met.

## 6 checks

| # | check | verdict | evidence |
|---|---|---|---|
| 1 | RED→GREEN real, tests assert real behavior | PASS | 11 new tests present + green. AC-2 patches `get_model`, `assert_not_called()` (test_facet_fast_path.py:103-109). INV-A/AC-5 patches with FileNotFoundError side_effect, `assert_called()` (:173-177). AC-7 semantic=True `assert_called()` (:216-220). INV-B end-to-end `get_model.assert_called()` + spy `options.semantic is True` (heavy test). No template/no-op tests. Doer red→green stash-verified per result doc. |
| 2 | POST-SUITE >= 1858, 0 extra failures | PASS | `1859 passed ... in 38.26s`, single run, flaky test green. |
| 3 | AC-2 mechanism: `--type` search skips embed | PASS | light_search_pipeline_orchestrator.py — `if (options.ntype or options.tags) and not options.semantic: return _facet_fast_search(conn, options)` sits BEFORE `_run_retrieval_stage` (Stage-1 embed). `_facet_fast_search` never calls get_model/embed. |
| 4 | INV-A: non-facet still embeds | PASS | non-facet falls through the guard to the full pipeline; AC-5 proves get_model IS called. `envelope.facet_fast is False`. |
| 5 | INV-B: heavy tag_filter passes semantic=True (both sites) | PASS | heavy_search_orchestrator.py:227 (light-search phase) + :335 (expansion phase) both add `semantic=True`. Guard tests exercise it end-to-end (embed attempted) + spy (every options.semantic True). |
| 6 | Blast fence: no new index, no test weakened | PASS | `grep '^\+.*CREATE INDEX'` on both commits = empty. No `pytest.mark.skip`/`xfail` added (all "skip" hits are English in comments/docstrings). Touched only SearchOptions/envelope additive fields, top-of-light_search branch + new helpers, handle_search flag parse, 2 heavy builder lines. Semantic path internals unchanged. |

## Verdict

**ACCEPT.** All 6 checks green; post-suite 1859 passed, 0 failures. Changelog appended to repo-root `CHANGELOG.md` (canonical location — not `docs/`, avoiding fragmentation; MEM-FIX-0006 logged there too).
