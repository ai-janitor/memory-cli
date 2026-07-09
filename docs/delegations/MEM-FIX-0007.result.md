# MEM-FIX-0007 — result

- commits: 647d47e (light/CLI fast-path + AC-1..7), 1c22b7c (result doc), + heavy INV-B fix (this commit)
- baseline: 1848 (×5 green, `test_consolidate_mixed_states` known-flaky)
- post-suite: 1859 passed, 0 failures (1848 + 9 AC + 2 heavy guard)
- red→green: verified via `git stash` — all 9 AC tests fail on old light/CLI src; both heavy guard tests fail on old heavy src; all green with fixes

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

## INV-B heavy regression — FOUND + FIXED (orchestrator ruling: fix in-scope)
- Root cause: `heavy_search_orchestrator.py` built `SearchOptions(tags=tag_filter or [])` without `semantic=True`. Since MEM-FIX-0007 fast-paths on truthy `options.tags`, a real tag-scoped heavy search would have silently degraded to no-embed BM25-only. Not caught by existing heavy suite (it mocks `light_search`).
- Fix: both heavy `SearchOptions` builders (light-search phase + expansion phase) now pass `semantic=True` → tag-scoped heavy sub-queries keep the full pipeline. CLI/light fast-path predicate UNCHANGED (`--type` AND `--tag` still fast-path there).
- Guard (tests/search/heavy/test_heavy_search_orchestrator.py, `TestHeavyStaysSemanticWithTagFilter`, 2 tests):
  - end-to-end: real DB + real light_search, tag_filter set → `get_model` IS called (not fast-path).
  - spy: every heavy light_search options object has `semantic=True`.
  - Both red on old heavy src (stash-verified), green with fix.
