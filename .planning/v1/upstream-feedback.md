# Upstream Feedback — v1

## Source: Stage 3 Research

### R-1: Task instruction prefixes required for nomic-embed-text-v1.5
**Layer:** Requirements (§8 Embedding)
**Finding:** The embedding model requires text prefixes (`search_document:` for indexing, `search_query:` for searching) for quality embeddings. Current requirements say "content text + tags concatenated" but don't mention prefixes.
**Impact:** The CLI must transparently prepend the correct prefix based on operation type (write vs search). This is a WHAT requirement — the embedding input format must include task-appropriate prefixes.
**Status:** Resolved — added to REQUIREMENTS.md §8.

### R-2: Model size is 140 MiB (Q8_0), not ~260 MB
**Layer:** Requirements (§8 Embedding)
**Finding:** The Q8_0 quantization is 140 MiB with negligible quality loss (MSE 5.79e-06). The ~260 MB estimate was for F16/F32.
**Impact:** Informational. The recommended quantization is Q8_0 unless precision is critical.
**Status:** Informational.

### R-3: sqlite-vec two-step query pattern required
**Layer:** Design constraint
**Finding:** sqlite-vec virtual tables with JOINs cause indefinite hangs (known issue). Must query vec table alone, then JOIN results separately.
**Impact:** All vector search code must follow the two-step pattern. This is a design constraint, not a requirement.
**Status:** Noted for decomposition.

### R-4: macOS system Python incompatibility
**Layer:** Design constraint
**Finding:** macOS system SQLite doesn't support extension loading. sqlite-vec requires Homebrew Python or pysqlite3.
**Impact:** Installation docs / init command must verify Python environment. May need to document prerequisite.
**Status:** Noted for decomposition.

### R-5: Spreading activation — application-side, not SQL
**Layer:** Design decision (replaces flagged HOW item #3 from clean requirements)
**Finding:** Recursive CTEs cannot properly handle visited sets or score aggregation. Application-side BFS is simpler, correct, and performant (~30 lines of Python).
**Impact:** Confirms the HOW flag was correct. Implementation uses Python BFS, not SQL.
**Status:** Noted for decomposition.

### R-6: BM25 score normalization needed for --explain output
**Layer:** Design constraint
**Finding:** FTS5 bm25() returns negative scores. For the --explain debug mode, scores need normalization: `|x| / (1 + |x|)` → [0, 1).
**Impact:** Affects search output formatting when --explain is used.
**Status:** Noted for decomposition.

### R-7: Edge weight modulation in spreading activation
**Layer:** Design consideration
**Finding:** Research suggests edges with a weight column (default 1.0) allow activation to be modulated per-edge. Hub nodes can be capped with --max-neighbors.
**Impact:** Edge schema may want a weight column. Not in current requirements.
**Status:** Resolved — added to REQUIREMENTS.md §2.2. Edge weight in v1.

### R-9: Project-scoped memory stores (Source: Stage 6 Wave A reflect gate)
**Layer:** Requirements (§7.2 Init & Config)
**Finding:** User wants per-project memory stores in addition to global. Config resolution walks up from cwd looking for .memory/config.json, falls back to ~/.memory/config.json. Like .git/ discovery.
**Impact:** Config loading must implement ancestor-directory walk. `memory init` is a top-level command exception to noun-verb grammar.
**Status:** Resolved — added to REQUIREMENTS.md §7.2.
**Updated v0.3.0:** Init default flipped — `memory init` = local (.memory/ in cwd), `memory init --global` = global (~/.memory/). Layered PATH-style search added: queries hit local first, then global, merged results. `--project` flag removed, replaced by `--global`. Stores are no longer fully isolated on read — search merges both stores with local ranked first. Writes still target a single store (local preferred).

### R-10: `memory init` as grammar exception (Source: Stage 6 Wave A reflect gate)
**Layer:** Requirements (§7.1 Grammar, §7.2 Init & Config)
**Finding:** `memory init` is a top-level command, not noun-verb. This is an intentional exception like `git init`. The #1 CLI Dispatch spec proposed `memory meta init` but user prefers bare `memory init`.
**Status:** Resolved — added to REQUIREMENTS.md §7.2.

### R-8: Development constraint — Haiku never for coding
**Layer:** Process
**Finding:** User-directed constraint. Haiku is only for runtime product features (conversation ingestion, search re-ranking). All coding uses Sonnet or Opus.
**Status:** Captured in CLAUDE.md and REQUIREMENTS.md §12.

## Source: Stage 6 Specs — Bulk Reflect Gate (all waves)

### S-1: Tag/attr removal when in use (#4 F-1/F-2)
**Layer:** Spec gap
**Finding:** Requirements silent on what happens when removing a tag/attr that is actively referenced by neurons.
**Resolution:** Block removal, show ref count. Exit code 2 with message "Tag X is referenced by N neurons."
**Status:** Resolved v2.

### S-2: Neuron archive has no restore path (#6 F-1)
**Layer:** Spec gap
**Finding:** No `neuron restore` command defined.
**Resolution:** Add `memory neuron restore <id>` — changes status from archived back to active.
**Status:** Resolved v2.

### S-3: Temporal decay formula undefined (#8 F-1)
**Layer:** Spec gap
**Finding:** Requirements say "recent neurons rank higher" but no formula.
**Resolution:** Exponential decay: `e^(-λt)` where t = age in days, λ derived from configurable half-life. Add `search.temporal_half_life_days` to config (default: 30).
**Status:** Resolved v2.

### S-4: Tag filtering before vs after spreading activation (#8 F-2)
**Layer:** Spec ambiguity
**Finding:** Spec defaults to post-activation filtering.
**Resolution:** Confirmed post-activation. Activation flows through all neurons; tag filter applies to output only.
**Status:** Resolved v2.

### S-5: Edge traversal directionality (#7 F-2, #8 F-3)
**Layer:** Cross-spec
**Finding:** Edges are directed per spec #7. Spreading activation and goto need direction policy.
**Resolution:** Bidirectional for both spreading activation and goto. Query both source_id and target_id columns.
**Status:** Resolved v2.

### S-6: Capture context linking topology (#11 F-2)
**Layer:** Design decision
**Finding:** Full mesh O(n²) vs star O(n) for co-occurrence edges.
**Resolution:** Star topology. Create a session-context neuron per ingestion, link all extracted neurons to it at weight 0.5. Source type attribute distinguishes session neurons from fact neurons.
**Status:** Resolved v2.

### S-7: Session deduplication on re-ingest (#11 F-5)
**Layer:** Spec gap
**Finding:** No dedup guard. Re-ingesting creates duplicates.
**Resolution:** Guard via ingested_session_id attribute. If a session neuron with matching session_id exists, skip with warning. --force to re-ingest anyway.
**Status:** Resolved v2.

### S-8: Vector export default behavior (#12 F-1)
**Layer:** Spec decision
**Finding:** Vectors opt-in vs default include.
**Resolution:** Opt-in via --include-vectors. Default export omits vectors (they can be re-embedded on import).
**Status:** Resolved v2.

### S-9: Haiku model not configurable (#9 F-1, #11 F-1)
**Layer:** Config gap
**Finding:** No haiku.model config key.
**Resolution:** Add `haiku.model` to config schema. Default: "claude-haiku-4-5-20251001".
**Status:** Resolved v2.

### S-10: Heavy search degradation signal for AI callers (#9 F-7)
**Layer:** Spec gap
**Finding:** Haiku fallback only signals via stderr.
**Resolution:** Add `"warnings": []` array to the JSON output envelope (Spec #1). Populated with string messages when degradation occurs. Empty array when clean.
**Status:** Resolved v2.

## Source: v0.3.x shipped changes (2026-03-14)

### R-11: Tag-affinity scoring in search pipeline
**Layer:** Requirements (§4.1 Light Search)
**Finding:** Search results improve when neurons sharing tags with direct matches get a relevance boost. Tag-affinity scoring inserted as Stage 5b in the light search pipeline, running at depth=2 spreading activation.
**Impact:** New scoring stage between spreading activation and temporal decay. Boosts "birds of a feather" neurons that share tags with the direct hit set.
**Status:** Shipped v0.2.9.

### R-12: Layered PATH-style search (local + global merge)
**Layer:** Requirements (§7.2 Init & Config, §4.1 Light Search)
**Finding:** Users need both project-local and global memory accessible in a single search. Search now queries local store first, then global, merging results with local ranked higher. Init default flipped: `memory init` = local, `memory init --global` = global. `--project` flag removed.
**Impact:** Search pipeline runs per-store then merges. Writes target local if `.memory/` exists, global otherwise. Stores are no longer isolated on read.
**Status:** Shipped v0.3.0.

### R-13: Tag list KeyError fix + `--sort count` / `--limit`
**Layer:** Bug fix + feature (tag noun handler)
**Finding:** `memory tag list` crashed with `KeyError: 'tag'` (column name was `'name'`, not `'tag'`). Additionally, users needed tag list sorted by usage count and limited to top N.
**Impact:** Bug fix: column key corrected. Feature: `--sort count` (sort by usage count descending) and `--limit N` (top N tags) added to `tag list` verb.
**Status:** Shipped v0.3.2.

### R-14: `--global` flag on all handlers
**Layer:** Requirements (§7.1 Grammar, §7.2 Init & Config)
**Finding:** The `--global` flag was only wired to `memory init` initially. All noun handlers need it to force global-only operation (skip local store).
**Impact:** `--global` is now a global CLI flag processed by the dispatcher and respected by all verb handlers via `get_connection_and_config()`.
**Status:** Shipped v0.3.1.

### R-15: Lean default neuron response fields + `--verbose`
**Layer:** Requirements (§7.4 Output Format)
**Finding:** Full neuron schema in every response is noisy for AI agents. Default output now returns lean fields only: id, content, tags, created_at, source. Search results add score and match_type.
**Impact:** `--verbose` flag added to `neuron get`, `neuron list`, `neuron search`. Without it, output is lean. With it, full schema is returned (status, updated_at, project, attributes, embedding_updated_at).
**Status:** Shipped v0.3.x (task #18).

### R-16: Handle prefix auto-routing (GLOBAL-/LOCAL-/fingerprint:)
**Layer:** Requirements (§7.1 Grammar)
**Finding:** Neuron IDs encode store scope via prefixes (GLOBAL-42, LOCAL-42, a1b2c3d4:42). Commands should auto-route to the correct store without requiring `--global` when the handle already encodes the target.
**Impact:** `parse_handle()` extended to recognize all prefix formats. neuron get/update/archive/restore auto-route by prefix. No `--global` needed when handle is prefixed.
**Status:** Shipped v0.3.x (task #19).
