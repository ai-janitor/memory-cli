# MEM-FIX-0008 — facet fast-path returns 0 on multi-word phrases (empty-BM25 fallback missing)

- **Origin:** post-deploy verify of MEM-FIX-0007 (2026-07-09, fable-yoda architecture review follow-up)
- **Mode:** REAL BUG (silent empty on populated facet)
- **Skill:** maintain-operate-orchestration (acceptance-test-first → baseline ×5 → doer → gate → changelog → deploy → live re-measure)
- **Status:** SPEC — frozen, PATH-CHECKED

---

## Verdict

- Facet fast-path ranks candidates via FTS5 MATCH with **implicit AND across all tokens** (`_build_fts5_query`, `bm25_retrieval_fts5_match.py:159-163` — each token quoted, space-joined = AND).
- `_rank_facet_candidates` (`light_search_pipeline_orchestrator.py:396-435`): non-empty query + zero BM25 hits in subset → returns `[]`. **No fallback.**
- Result: `search "verify on live path" --type lesson` → 0, while the facet holds 76 lessons and `search "verify" --type lesson` → 5. Every multi-word gate phrase silently reads as "no lessons exist."
- Fleet gate lookups are phrases → post-0007 they get 0 lessons. This is the caller-visible regression that masked as a wrong-facet-key problem.

## Live repro (measured 2026-07-09, droid project cwd, 76 type=lesson in local store)

```bash
memory neuron search "" --type lesson --limit 3            # rows returned (recency path OK)
memory neuron search "verify" --type lesson --limit 8      # 5 results
memory neuron search "verify on live path" --type lesson   # 0 results  <- BUG
memory neuron search "verify on live path" --tag lesson    # 0 too — key-independent
```

## Design

`_rank_facet_candidates`, staged relaxation — cheapest sufficient tier wins:

1. Tier 1 (today): quoted-AND MATCH in subset. Non-empty → return (unchanged).
2. Tier 2 (new): empty → retry MATCH with **OR-joined** quoted tokens, same subset, same cap. Rank by BM25.
3. Tier 3 (new): still empty → **recency fallback** over the facet subset (reuse the existing empty-query branch, `light_search_pipeline_orchestrator.py:437-453`), capped at `min(limit, BM25_CANDIDATE_CAP)`.
4. Mark envelope: `match_type` = `"facet_or"` / `"facet_recency"` for tier 2/3 rows — caller can tell ranked-match from browse. `facet_fast` stays True.

Fence:
- Facet resolution (`_resolve_type_candidates`/`_resolve_tag_candidates`) untouched.
- Full semantic pipeline untouched (INV-A). Heavy untouched (INV-B).
- No model load introduced on any tier (AC-2 of 0007 must stay green).
- `_build_fts5_query` itself unchanged — OR-join built beside it, not by changing global BM25 semantics.

## Acceptance tests (RED now → GREEN) — `tests/search/test_facet_fastpath_fallback.py`

- AC-1: facet with rows, phrase where no row matches ALL tokens but some match ONE → results non-empty, exit 0 (fails today).
- AC-2: phrase matching zero tokens anywhere → recency-ranked facet rows, `match_type=facet_recency`, exit 0.
- AC-3: phrase with full AND match → identical results/order to today (tier 1 regression guard).
- AC-4: `get_model` never called on any tier (spy — 0007 AC-2 extension).
- AC-5: empty facet + any query → exit 1, empty (unchanged).
- AC-6: empty-query recency branch unchanged.

## Requirements ledger

- REQ-1: a non-empty facet NEVER yields 0 results for a non-empty query (relaxation to recency guarantees floor).
- REQ-2: tier metadata distinguishes and/or/recency matches.
- REQ-3: zero model load on all facet tiers.

## Doer brief

- Baseline ×5 first (CLAUDE.md flakiness rule; quiet box, 1-min load < ~20).
- Touch only `_rank_facet_candidates` + tests. HARD CAP: 3 failed attempts → stop, commit what landed, report blocker.
- Deliverable: red→green transcript, commit sha, `MEM-FIX-0008.result.md`, then DEPLOY (`uv tool install --reinstall .`) + live re-run of the repro block above with numbers.

## Gate

- AC transcript + stash-verified reds + INV-A/INV-B green + deploy evidence + live repro now returning rows.
- Changelog entry in `docs/CHANGELOG.md`.

## Context notes (facet-key ruling, recorded here to close the caller thread)

- Canonical lesson facet key = **`type=lesson`** (writer intent: droid `lesson sync` writes `--type lesson`, `crates/cli/src/commands/lesson/mod.rs:412`; reader: `semantic_lesson_slugs`, `crates/cli/src/commands/task/verbs/add.rs:326`).
- Global store's 9 hand-authored lessons had tag-only → backfilled `type=lesson` 2026-07-09 (verified: global-vantage `--type lesson` returns 9). No role-card/protocol doc contains a `--type lesson` string — no doc edits needed.
- Rejected: flipping callers to `--tag lesson` — would orphan 72/76 droid-local lessons (tagged: 4, typed: 76).
