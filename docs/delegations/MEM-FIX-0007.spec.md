# MEM-FIX-0007 — facet-scoped search fast-path (`--type`/`--tag` indexed pre-filter, skip embed)

- **Backlog:** minion bug #72 (`.work/backlog/bugs/index-neuron-search-single-query-pins-100-153-cpu`)
- **Date:** 2026-07-09
- **Mode:** FEATURE (additive fast-path) + REAL BUG (facet filter silently unwired)
- **Skill:** maintain-operate-orchestration (accept-test-first → baseline ×5 → doer → opus gate → changelog)
- **Status:** SPEC — frozen, PATH-CHECKED

---

## Verdict

Two defects, one fix.

- **BUG-1 — `--type`/`--tag` silently dropped.** `handle_search` (`neuron_noun_handler.py:414-431`) parses only `--limit`/`--threshold` → builds `SearchOptions(query, limit)`.
  - `SearchOptions` (`light_search_pipeline_orchestrator.py:61-74`) has no `type` field; `tags` never populated from CLI.
  - so `search "x" --type lesson` = full unfiltered semantic search; filter is a no-op.
- **BUG-2 — every facet query pays full embed.** Stage-1 (`_run_retrieval_stage:290-302`) embeds via llama-cpp (`nomic-embed-text-v1.5` GGUF) unconditionally, per process, no shared model.
  - fleet runs `--type lesson` gate lookups → 100-153% CPU/query → host load 600+.
  - incident: `../../../droid/docs/diagnostics/0048-lesson-protocol-load-storm.md` (Finding B, cross-repo).
- **FIX.** facet-scoped (`--type`/`--tag`) + no explicit `--semantic`:
  - resolve candidates via EXISTING attr/tag indexes; rank by BM25; skip embed + vector + activation.
  - result: storm queries become indexed sub-second zero-model lookups, and the filter actually works.

---

## 1. Schema facts (PATH-CHECKED, `db/migrations/v001_baseline_all_tables_indexes_triggers.py`)

- `neurons` columns: id, content, created_at, updated_at, project, source, embedding_updated_at, status. **No `type` column.**
- `type` is an attr: `neuron_attrs(neuron_id, attr_key_id, value)`, attr_keys.name="type", value e.g. "lesson" (set at add: `neuron_noun_handler.py:73` `attrs={"type":ntype}`).
- Indexes that make the pre-filter cheap (already exist — do NOT add):
  - `idx_neuron_attrs_attr_key_id` on `neuron_attrs(attr_key_id)` — type pre-filter.
  - `idx_neuron_tags_tag_id` on `neuron_tags(tag_id)` — tag pre-filter.
  - `neurons_fts` (FTS5, BM25) — in-subset ranking.

---

## 2. Repro (current wrong behavior = RED-1)

```bash
memory init
memory neuron add "lesson: verify on live path" --type lesson       # id=1
memory neuron add "lesson: dump facts in briefs" --type lesson       # id=2
memory neuron add "random build note about verbs" --type memory      # id=3
memory neuron search "verify" --type lesson --format json
```
- EXPECTED: only type=lesson rows (id 1, maybe 2).
- ACTUAL (bug): `--type lesson` ignored → ranks across all types incl. id=3; and Stage-1 embed runs (model load).

---

## 3. Blast radius (fence)

- **Touches:** `SearchOptions` (+`ntype: Optional[str]`, ensure `tags` wired); `light_search` (facet fast-path branch before Stage-1); `handle_search` (parse `--type`/`--tag`, populate options).
- **Consumers of `light_search`** (grep `light_search\b`): `handle_search` (CLI, `neuron_noun_handler.py:431`); `heavy_search_orchestrator.py:228,335` (builds its own `SearchOptions` WITHOUT type/tags → default path, unchanged).
- **Must-not-regress (INVARIANTS):**
  - INV-A: non-facet query (`search "x"` no `--type`/`--tag`) → unchanged full pipeline (embed+vector+activation+RRF).
  - INV-B: heavy search path unchanged.
  - INV-C: `--type` filter is CORRECT (returns only matching type) — this was broken, must now hold.
  - INV-D: existing green suite stays green (`post_count >= baseline_count + new_tests`).

---

## 4. Design

**Entry (`light_search`, before Stage-1 embed):**
```
if (options.ntype or options.tags) and not options.semantic:
    return _facet_fast_search(conn, options)   # NO embed, NO vector, NO activation
# else: existing full pipeline (unchanged)
```

**`_facet_fast_search`:**
1. Resolve candidate neuron_ids by facet, index-backed:
   - type: join `neuron_attrs`→`attr_keys` where name='type' AND value=options.ntype.
   - tags: `neuron_tags`→`tags` where name IN options.tags (respect tag_mode AND/OR).
   - both present → intersect.
2. Rank the candidate set by BM25. Cap 100.
   - simplest: `retrieve_bm25(conn, query)` then restrict to candidate ids.
   - preferred: constrain the FTS5 MATCH to candidate ids.
   - empty `query` → rank by recency (created_at desc).
3. Hydrate + envelope via existing `hydrate_results`/`build_envelope`. `vector_unavailable` stays False (not an error path — it's a deliberate skip; add `facet_fast=True` metadata instead).
4. Preserve exit codes (0 found / 1 none / 2 error).

**`SearchOptions`:** add `ntype: Optional[str] = None`; add `semantic: bool = False` (opt back into full pipeline for facet queries when caller wants semantic).

**`handle_search`:** `ntype, rest = extract_flag(rest, "--type")`; `tag, rest = extract_flag(rest, "--tag")`; `semantic, rest = extract_bool_flag(rest, "--semantic")`; pass into `SearchOptions`. (Mirror the `neuron list` handler which already parses `--type`/`--tag`, `neuron_noun_handler.py:202-221`.)

---

## 5. Acceptance tests (RED now → GREEN after) — new file `tests/search/test_facet_fast_path.py`

- **AC-1 (RED-1, correctness):** seed lessons + non-lesson; `search --type lesson` returns ONLY type=lesson ids. (fails today — filter ignored.)
- **AC-2 (RED-2, no model load):** patch/spy `memory_cli.embedding.get_model`; assert it is **NOT called** for a `--type`-scoped search. (fails today — Stage-1 always embeds.)
- **AC-3 (tag facet):** `search --tag <t>` returns only tagged rows; AND/OR mode honored.
- **AC-4 (both):** `--type X --tag Y` = intersection.
- **AC-5 (INV-A guard, must stay green):** non-facet `search "x"` STILL calls `get_model` (or hits vector path) — proves fast-path did not hijack the semantic path.
- **AC-6 (INV-C):** empty query + `--type lesson` → returns lessons by recency, exit 0.
- **AC-7 (opt-out):** `search "x" --type lesson --semantic` → full pipeline (get_model called).

---

## 6. Requirements ledger (append-only)

- REQ-1: facet-scoped search resolves candidates via attr/tag index, not full-corpus embed.
- REQ-2: `--type`/`--tag`/`--semantic` parsed in `handle_search` and threaded to `SearchOptions`.
- REQ-3: facet fast-path skips embed+vector+activation; semantic path unchanged (INV-A).
- REQ-4: warm facet search sub-second on current corpus; zero llama.cpp load (AC-2).

---

## 7. Doer brief (Sonnet)

- Read this spec + skill `~/.skills/maintain-operate-orchestration/` (your category). Turn AC-1..7 red→green.
- **Baseline FIRST, multi-run:** `uv run pytest tests/` ×5 — record counts.
  - latent flakiness per CLAUDE.md → single green ≠ baseline.
  - quiet box only: droid fleet makes load bursty; wait for a trough (`uptime` < ~20) before baselining.
- Do NOT weaken/skip any existing test to pass. Do NOT add a new index (they exist). Do NOT touch the semantic path except the top-of-`light_search` branch.
- HARD CAP: 3 failed attempts at a mechanism → STOP, commit what landed, report blocker. No uncapped retry loops.
- Deliverable: red→green transcript (baseline + post, `post >= baseline + new`), commit sha, `MEM-FIX-0007.result.md`.

---

## 8. Gate (opus verifier) + changelog

- baseline-suite transcript (green, ×5) + post-suite (green, `post_count >= baseline_count + 7`).
- AC-2 proof: `get_model` not called on `--type` search (spy transcript).
- INV-A proof: non-facet search still embeds (AC-5).
- Then append `docs/CHANGELOG.md`: facet filter was silently unwired + storm perf; fixed via indexed pre-filter fast-path; tests AC-1..7; gate-record ref.
