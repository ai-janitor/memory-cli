# MEM-FIX-0007 — result

- commit: 647d47e
- baseline: 1848 (×5 green, `test_consolidate_mixed_states` known-flaky)
- post-suite: 1857 passed, 0 failures (1848 + 9 new)
- red→green: verified via `git stash` on the two src files — all 9 new tests fail on old code, pass on new code

## AC map
- AC-1 (type filter correct) — green
- AC-2 (no model load, --type) — green, `get_model.assert_not_called()`
- AC-3 (tag facet AND/OR) — green, 2 tests
- AC-4 (type+tag intersection) — green
- AC-5 (INV-A: non-facet still embeds) — green, `get_model.assert_called()`
- AC-6 (empty query + type → recency, exit 0) — green
- AC-7 (--semantic opt-out → full pipeline) — green
- bonus: `handle_search` CLI wiring proof (BUG-1) — green

## Fence
- touched only: `SearchOptions` (+`ntype`, +`semantic`), `SearchResultEnvelope` (+`facet_fast`, additive default-False field), `light_search` top branch + new `_facet_fast_search`/`_resolve_type_candidates`/`_resolve_tag_candidates`/`_rank_facet_candidates` helpers, `handle_search` flag parsing.
- no new DB indexes added (reused `idx_neuron_attrs_attr_key_id`, `idx_neuron_tags_tag_id`).
- semantic path internals untouched.

## Deviation flagged (not fixed — out of fence)
- `heavy_search_orchestrator.py` builds its own `SearchOptions(tags=tag_filter or [])` without `semantic=True`. In production (not test — all heavy tests mock `light_search`), a real heavy-search call with a non-empty `tag_filter` would now hit the facet fast-path too, since `options.tags` is truthy and `semantic` defaults False. Spec's blast-radius note ("heavy_search_orchestrator … WITHOUT type/tags → default path, unchanged") undercounts this — `tags` IS passed. No test broke because `light_search` is mocked in the heavy suite. Flagging for a follow-up: either heavy_search should pass `semantic=True`, or the fast-path predicate should be type-only. Left as-is per blast fence (spec didn't authorize touching `heavy_search_orchestrator.py`).
