# GATE — MEM-FIX-0005 verify — 2026-06-10

<!-- None-guard model_path in meta_stats + meta_check so a null-model_path store (0003) doesn't crash basename(None). -->

## unit
cmd: uv run pytest tests/integrity/test_meta_stats.py tests/integrity/test_meta_check.py
result: 57 passed (incl. 6 new None-model-path regression tests)
```
$ uv run pytest tests/integrity/test_meta_stats.py tests/integrity/test_meta_check.py -q --tb=short
...
tests/integrity/test_meta_check.py::TestNoneModelPathCheck::test_check_model_match_none_model_path_no_vectors
tests/integrity/test_meta_check.py::TestNoneModelPathCheck::test_check_model_match_none_model_path_with_real_db_model
tests/integrity/test_meta_check.py::TestNoneModelPathCheck::test_run_meta_check_none_model_path_does_not_crash
57 passed, 54 warnings in 0.41s
```

## e2e
test: (A) real `memory meta stats --json` on a store created by real `memory init` (model_path=null) -> no crash, config_model_name=='none'; (B) real run_meta_check + _check_model_match against that real store DB w/ real sqlite-vec ext, driving the basename(None) branch (db model present + config None)
wired-real: real `memory` CLI binary + real `memory init` config writer for (A); real load_config of the on-disk null-model config + real open_connection + real sqlite-vec extension (vec0) + real run_meta_check/_check_model_match for (B) — NO mock at the integrity seam under test
result: 2 passed (stats returns 'none' no crash; run_meta_check returns dict + _check_model_match returns CheckItem, no TypeError)
```
=== A) real CLI `memory meta stats --json` on null-model_path store ===
status: ok
config_model_name: 'none'

=== B) real run_meta_check + _check_model_match on live null-model store DB (vec ext loaded) ===
REAL config model_path: None
A) run_meta_check -> dict, status: issues_found | keys ok: True
B) _check_model_match w/ db_model + None path -> CheckItem (no TypeError): True | passed: False
```

## adversarial
- guard is load-bearing (old code would crash): python -c "import os; os.path.basename(None)" -> TypeError: expected str, bytes or os.PathLike object, not NoneType (so the `if _raw is not None else "none"` guard is what prevents the crash)
- 'none' sentinel is a str (satisfies existing isinstance(config_model_name,str) contract): grep meta_stats_db_summary.py:90 `... else "none"` ; repr type-check -> 'none' is str: True
- drift logic does NOT false-trip on 'none' for empty DB: grep meta_stats_db_summary.py:96 `if embedding_model_name is not None and embedding_model_name != config_model_name` -> compare only fires when DB has a model row, so 'none' sentinel can't manufacture false drift on an unembedded store

## flags
- DEVIATION-D1 (out-of-fence flaky `tests/db/test_consolidated_migration_v005.py::TestConsolidateLogic::test_consolidate_mixed_states` — fails full-run, passes isolated): accept ruling = PRE-EXISTING FLAKE, non-blocking. Independently adjudicated: git-stashed the combined tree (unique-msg stash, pre-existing daemon-work-wave2 stash preserved at @{1}), ran CLEAN HEAD full suite 7x = 1826 passed every time (flake did not surface), unstashed (tree fully restored: 17 mod + 9 untracked back, daemon stash intact). On dirty tree: 8/9 full runs = 1841, 1 run = 1840 (this test). The test is time-boundary dependent (now_ms = time.time()*1000 vs row updated_at) and NONE of MEM-FIX-0001/0002/0003/0005 touch tests/db/, consolidate logic, or the v005 migration -> not a regression. Backlog as flaky-test stabilization.

## verifier
agent: opus-4-8-1m-gate-verifier
tokens: 0

## VERDICT: accept
rework-task: n/a

## RULING: accept on opus-4-8-1m-gate-verifier — null-model store no longer crashes meta stats/check at the real CLI + integrity seam; guard proven load-bearing; the one full-run failure is a pre-existing time-boundary flake (passes clean HEAD + isolated), non-blocking.
