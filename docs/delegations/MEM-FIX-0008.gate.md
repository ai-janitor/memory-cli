# MEM-FIX-0008 — opus gate record

- **Gate:** independent opus verifier (adversarial; did not write the code)
- **Date:** 2026-07-09
- **Fix:** facet fast-path staged relaxation for multi-word phrases — `_rank_facet_candidates` Tier 1 (AND) → Tier 2 (OR) → Tier 3 (recency)
- **Commits:** 0d896af (fix + AC-1..6), 5d39e8e (changelog + result doc)
- **Spec:** `docs/delegations/MEM-FIX-0008.spec.md`
- **Baseline anchor:** 1859 (post-MEM-FIX-0007); known-flaky `test_consolidate_mixed_states` (unrelated, tolerate).

## Suite lines

- **Baseline (doer, ×5):** `1859 passed` (2 runs had the flaky `test_consolidate_mixed_states` fail; anchor 1859).
- **Post-suite (verifier, HEAD 5d39e8e):**
  - run 1: `1 failed, 1866 passed in 13.38s` — sole failure = tolerated flaky `test_consolidate_mixed_states`.
  - run 2 (rerun): `1867 passed in 13.07s` — 0 failures, flaky green. 1867 = 1859 + 8 new AC. Requirement `>= 1867` met.

## 6 checks

| # | check | verdict | evidence |
|---|---|---|---|
| 1 | RED→GREEN real; AC-1 genuine multi-word; AC-4 no get_model any tier | PASS | Independently reverted both src files to `0d896af^`, ran new test file → `2 failed, 6 passed`: AC-1 (`test_multiword_phrase_falls_back_to_or_join`) + AC-2 (recency) RED; the other 6 green by design (Tier1/empty-facet/empty-query paths untouched). AC-1 uses phrase `"verify on live path"` vs rows where no single row holds all 4 tokens (verify / path each in one row, `on`/`live` in none) → pre-fix AND=0, `assert ids` fails; post-fix OR returns `{verify_row, path_row}` (test_facet_fastpath_fallback.py:86-100). AC-4 = 3 sub-tests spying `get_model` on Tier1/2/3, all `assert_not_called()` (:147-180). No template/no-op tests. |
| 2 | POST-SUITE >= 1867, 0 extra failures | PASS | `1867 passed ... in 13.07s` on rerun; sole first-run failure was the tolerated flaky, green on rerun. |
| 3 | Mechanism: Tier2 OR-join + Tier3 recency; non-empty facet never 0 (REQ-1); match_type facet_or/facet_recency | PASS | `_rank_facet_candidates` (light_search_pipeline_orchestrator.py:401-448): Tier1 `_facet_bm25_match(_build_fts5_query)` → if empty, Tier2 `_facet_bm25_match(_build_fts5_query_or)` match_type `facet_or` → else Tier3 `_facet_recency_candidates` match_type `facet_recency`. Tier3 is unconditional floor for a non-empty query → non-empty facet never returns 0. |
| 4 | No-model-load on ALL tiers (0007 AC-2 not regressed) | PASS | Everything in the tiers is FTS5/SQL; AC-4 spy proves 0 get_model calls across all 3 tiers. Live repro RSS 30MB, 0.17s user single-core — no embed. |
| 5 | Fence: `_build_fts5_query` unchanged, `_build_fts5_query_or` added beside; facet resolution/semantic/heavy untouched; no new DB index; no test weakened/skipped | PASS | Diff of 0d896af: `_build_fts5_query` body unchanged, `_build_fts5_query_or` is a new function beside it (bm25_retrieval_fts5_match.py:166-190). Src diff touches only `_rank_facet_candidates` + 3 new private helpers. No `CREATE INDEX`, no migration, no `pytest.mark.skip`/`xfail` in diff. |
| 6 | DEPLOY re-verify: installed tool current, live repro non-zero/fast/no storm | PASS | Installed `memory` (`~/.local/bin/memory`, memory-cli 0.4.0) is an editable install resolving to `/Users/hung/projects/memory-cli/src/memory_cli`; `_build_fts5_query_or` present in the imported module → current. Live repro (droid cwd, local `.memory`, 85 type=lesson): `search "verify on live path" --type lesson --limit 5` → **5 results, match_type facet_or** (was 0 pre-fix), 0.22s real / 0.17s user / 30MB RSS, single-core (no 800% storm). `--tag lesson` → 7 facet_or (was 0). `--type lesson "verify"` → direct_match (Tier1). empty query → direct_match recency (AC-6). |

## Verdict

**ACCEPT.** All 6 checks green; post-suite 1867 passed (rerun), 0 failures beyond tolerated flaky. Independent RED reproduced (AC-1/AC-2 fail on pre-fix source). Live deployed tool: multi-word phrase 0 → non-zero via `facet_or`, sub-second, no CPU storm. Changelog row present at repo-root `CHANGELOG.md`.
