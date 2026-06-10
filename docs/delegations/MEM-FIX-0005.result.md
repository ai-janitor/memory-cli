# MEM-FIX-0005 Result

## CHANGES

| File | Line | Change |
|------|------|--------|
| `src/memory_cli/integrity/meta_stats_db_summary.py` | 89 | None-guard before `os.path.basename`; display `"none"` when `model_path` is `None` |
| `src/memory_cli/integrity/meta_check_orphans_and_anomalies.py` | 180 | Same None-guard in `_check_model_match` |
| `tests/integrity/test_meta_stats.py` | appended | `TestNoneModelPath` — 3 regression tests |
| `tests/integrity/test_meta_check.py` | appended | `TestNoneModelPathCheck` — 3 regression tests |

## RED (fenced)

```
FAILED tests/integrity/test_meta_stats.py::TestNoneModelPath::test_none_model_path_does_not_crash
FAILED tests/integrity/test_meta_stats.py::TestNoneModelPath::test_none_model_path_config_model_name_is_string
FAILED tests/integrity/test_meta_stats.py::TestNoneModelPath::test_none_model_path_no_false_drift
FAILED tests/integrity/test_meta_check.py::TestNoneModelPathCheck::test_check_model_match_none_model_path_with_real_db_model
4 failed, 2 passed
```

## GREEN (fenced)

```
tests/integrity/test_meta_stats.py::TestNoneModelPath::test_none_model_path_does_not_crash PASSED
tests/integrity/test_meta_stats.py::TestNoneModelPath::test_none_model_path_config_model_name_is_string PASSED
tests/integrity/test_meta_stats.py::TestNoneModelPath::test_none_model_path_no_false_drift PASSED
tests/integrity/test_meta_check.py::TestNoneModelPathCheck::test_check_model_match_none_model_path_no_vectors PASSED
tests/integrity/test_meta_check.py::TestNoneModelPathCheck::test_check_model_match_none_model_path_with_real_db_model PASSED
tests/integrity/test_meta_check.py::TestNoneModelPathCheck::test_run_meta_check_none_model_path_does_not_crash PASSED
6 passed
```

## SUITE tail

```
1 failed, 1840 passed, 833 warnings in 15.68s
```

## ASSUMPTIONS [?]

- `"none"` chosen as display sentinel (not `None`, not `"central-default (...)"`) because: (1) `config_model_name` flows into drift comparison and the return dict — must be a `str` to satisfy existing type test `isinstance(stats["config_model_name"], str)`; (2) drift logic already guards `if embedding_model_name is not None` before comparing, so `"none"` as sentinel won't cause false drift on empty DB; (3) minimal — no path fabrication. [?] A richer "central-default (~/.memory/models/default.gguf)" marker was considered but rejected as over-engineering for a diagnostic display field.

## DEVIATIONS

**D1 — out-of-fence flaky failure: `tests/db/test_consolidated_migration_v005.py::TestConsolidateLogic::test_consolidate_mixed_states`**
Fails in full-suite run; passes in isolation. Contention artifact, not related to this fix. Not in fence (`tests/integrity/`). Zero integrity test failures.

## SKILL-FEEDBACK

None.
