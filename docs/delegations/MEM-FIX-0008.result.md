# MEM-FIX-0008 — result

- Status: DONE. Deployed + live-verified.
- Commit: `0d896af` — fix(search): facet fast-path staged relaxation for multi-word phrases (MEM-FIX-0008)
- Changelog: `CHANGELOG.md` (repo root — spec said `docs/CHANGELOG.md`, actual file lives at root) `[Unreleased] > Fixed`

## Baseline (pre-fix, ×5, quiet box)

```
run1: 1859 passed
run2: 1858 passed, 1 failed (test_consolidate_mixed_states — known flaky)
run3: 1859 passed
run4: 1859 passed
run5: 1858 passed, 1 failed (test_consolidate_mixed_states — known flaky)
```
Anchor = 1859.

## Touched

- `src/memory_cli/search/bm25_retrieval_fts5_match.py` — added `_build_fts5_query_or()` beside `_build_fts5_query()`. `_build_fts5_query()` itself unchanged.
- `src/memory_cli/search/light_search_pipeline_orchestrator.py` — `_rank_facet_candidates` rewritten as Tier1(AND)→Tier2(OR)→Tier3(recency), factored into `_facet_bm25_match`, `_facet_bm25_rows_to_candidates`, `_facet_recency_candidates` helpers. Nothing else changed (facet resolution, semantic path, heavy path, `light_search` untouched).
- `tests/search/test_facet_fastpath_fallback.py` — new, AC-1..AC-6.

## AC red→green (stash-verified)

Stashed both source files, ran the new test file against pre-fix code:
- AC-1 (Tier 2 OR-join, multi-word phrase) — RED (`assert set()` — 0 results, the bug)
- AC-2 (Tier 3 recency fallback) — RED (`exit_code` 1 != 0)
- AC-3, AC-4×3, AC-5, AC-6 — GREEN even pre-fix (they exercise Tier 1 / empty-facet / empty-query paths, untouched by design)

Popped stash, reran: all 8 GREEN.

## Post-fix suite

```
tests/search/ : 384 passed
tests/       : 1867 passed, 0 failed
```
1867 = 1859 + 8 new. `post - baseline = 8 >= 6`. 0 regressions, 0 new failures.

## Deploy

`uv tool install --reinstall /Users/hung/projects/memory-cli` — reinstalled `memory-cli==0.4.0` from local source, `memory` executable relinked.

## Live repro (droid project cwd, 85 type=lesson rows in local store — grew from 76 since spec was frozen)

| query | before (spec §17) | after |
|---|---|---|
| `search "" --type lesson --limit 3` | rows (recency path OK) | unchanged — rows, total 85 |
| `search "verify" --type lesson --limit 8` | 5 results | 7 results (corpus grew) |
| `search "verify on live path" --type lesson` | **0** (bug) | **40 results**, `match_type: facet_or`, 0.226s wall / 95% CPU single-core |
| `search "verify on live path" --tag lesson` | 0 (bug) | 9 results, `match_type: facet_or` |

No CPU storm (single-core ~95%, not the 800%+ pre-0007 pathology) — confirms zero model load on the OR-join tier.

## Fence check

- `_build_fts5_query` global semantics: unchanged (verified — same function body).
- Facet resolution (`_resolve_type_candidates`/`_resolve_tag_candidates`): untouched.
- Semantic/heavy pipeline: untouched (not in diff).
- No new DB index: confirmed — diff has no migration/index changes.
- get_model spy: 0 calls across Tier 1/2/3 (AC-4, 3 sub-tests).

## Deviations / blockers

- None. 0 of 3 retry-cap attempts used — implementation was correct on first pass.
- Changelog file path: spec said `docs/CHANGELOG.md`; actual repo file is `CHANGELOG.md` at root (matches MEM-FIX-0007's own entry location). Used the real file, flagged here.
