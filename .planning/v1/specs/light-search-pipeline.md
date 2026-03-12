# Spec #8 — Light Search Pipeline

## Purpose

Defines the complete behavior of the algorithmic (no-LLM) search pipeline invoked by `memory neuron search`. This is the primary retrieval surface for the system. It produces a ranked list of neurons by fusing BM25 keyword matching, vector similarity, and spreading activation graph traversal, then applies tag filtering and temporal decay. All behavior is deterministic and offline.

---

## Requirements Traceability

| Requirement | Section |
|---|---|
| BM25 keyword matching | §4.1 Light Search |
| Vector similarity (semantic search) | §4.1 Light Search |
| Graph traversal via spreading activation | §4.1 Light Search, §11 Spreading Activation |
| Linear decay per hop, configurable rate | §11 Spreading Activation |
| Fan-out depth configurable per query, default 1 | §4.1 Light Search, §11 Spreading Activation |
| Tag filtering AND (`--tags`) and OR (`--tags-any`) | §4.1 Light Search |
| Temporal decay — recent neurons rank higher | §4.1 Light Search |
| Match + fan-out in output, with edge reasons | §4.3 Search Output |
| Pagination `--limit N --offset M` | §4.3 Search Output |
| `--explain` scoring breakdown | §4.3 Search Output |
| No synthesis, no summarization — raw data only | §4.3 Search Output, §13 Non-Requirements |
| Exit codes 0/1/2 | §7.4 Output Format |
| JSON default output, plain text alternative | §7.4 Output Format |
| Conflicting memories: most recent outranks by default | §10 Edge Cases |
| Circular references: visited set in spreading activation | §10 Edge Cases |
| Embedding unavailable: fallback to BM25-only | §10 Edge Cases |

---

## Dependencies

| Spec | What is needed |
|---|---|
| #3 Schema & Migrations | FTS5 virtual table (`neurons_fts`), vec0 virtual table (`vec_neurons`), edges table, index on `edges(source_id)`, index on `edges(target_id)` |
| #4 Tag & Attribute Registries | Tag ID resolution for `--tags` and `--tags-any` filtering; tag ID lookup by name |
| #5 Embedding Engine | Embed the search query with `search_query:` prefix; returns a 768-dim float vector |
| #6 Neuron CRUD & Storage | Hydrate neuron records from IDs (content, timestamp, project, tags, source, attributes) |
| #7 Edge Management | Retrieve neighbor edges for spreading activation traversal; edge weight and reason |

---

## CLI Interface

### Command

```
memory neuron search <query> [flags]
```

### Flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `--tags <t1,t2,...>` | string list | none | AND filter: neuron must have ALL listed tags |
| `--tags-any <t1,t2,...>` | string list | none | OR filter: neuron must have AT LEAST ONE listed tag |
| `--fan-out-depth N` | integer | 1 | Spreading activation hop depth (0 disables graph traversal) |
| `--limit N` | integer | 10 | Maximum number of result neurons to return |
| `--offset M` | integer | 0 | Skip first M results (for pagination) |
| `--explain` | boolean flag | false | Include per-neuron scoring breakdown in output |
| `--format json\|text` | string | config default | Output format |

Tag filters are resolved by name to integer IDs using the tag registry (#4). Unrecognized tag names in filter flags produce a warning but do not abort — they match no neurons, effectively acting as an empty result filter.

---

## Behavior

### Overview of Pipeline Stages

The pipeline executes in this order:

1. Query embedding
2. BM25 retrieval
3. Vector retrieval (two-step)
4. RRF fusion
5. Spreading activation fan-out
6. Temporal decay application
7. Tag filtering
8. Final score combination and ranking
9. Pagination
10. Result hydration and output

Each stage is described exhaustively below.

---

### Stage 1 — Query Embedding

The search query string is embedded using the embedding engine (#5) with the `search_query:` task prefix prepended transparently. This produces a 768-dimensional float vector.

If the embedding engine is unavailable (model file missing, library error, or explicit configuration disabling it), the pipeline falls back to BM25-only mode. In fallback mode:
- Vector retrieval (Stage 3) is skipped entirely.
- RRF fusion (Stage 4) operates on BM25 results only.
- The `--explain` output notes that vector scoring was unavailable.
- No error is raised; the search proceeds with degraded ranking quality.

The query string as provided by the user is used as-is for BM25. The same query string (with `search_query:` prefix) is used for vector embedding. No normalization, stemming, or modification of the query string is performed by the pipeline itself — FTS5 handles its own tokenization via the porter unicode61 tokenizer defined in the schema.

---

### Stage 2 — BM25 Retrieval

A full-text search is executed against `neurons_fts` using the FTS5 `MATCH` operator with the raw query string.

The BM25 scoring weights from the schema definition are applied (content field is weighted more heavily than tags field — exact weights defined in #3 Schema).

Results are retrieved as `(neuron_id, raw_bm25_score)` pairs. Raw BM25 scores from FTS5 are negative (more negative = stronger match). They are normalized before use in `--explain` output using the formula `|x| / (1 + |x|)`, which maps the range to `[0, 1)`. The normalized score is displayed in `--explain` only; RRF fusion (Stage 4) uses rank position, not the raw or normalized score.

A retrieval cap is applied internally (e.g., top 100 BM25 candidates) to bound the candidate set fed into RRF. The exact cap is a constraint (see Constraints section).

If the query string produces no FTS5 matches, BM25 contributes no candidates. The pipeline continues with vector results only (if available).

---

### Stage 3 — Vector Retrieval (Two-Step Pattern)

Vector search uses the two-step pattern to avoid sqlite-vec JOIN hangs:

**Step 1:** Query `vec_neurons` alone — no JOIN to any other table. Retrieve `(neuron_id, distance)` pairs for the top-k nearest neighbors by cosine/L2 distance. The value of k is the same internal retrieval cap used for BM25.

**Step 2:** The neuron IDs from Step 1 are used to hydrate or further filter in a subsequent query against the main tables if needed.

The distance is NOT directly used as a ranking score. Vector results are ranked by ascending distance (lower = more similar), and this rank position is what feeds into RRF fusion.

If the query vector could not be produced (embedding unavailable — see Stage 1 fallback), this stage is entirely skipped.

---

### Stage 4 — RRF Fusion

Reciprocal Rank Fusion (RRF) combines the BM25 candidate list and the vector candidate list into a single ranked list.

**Formula:** For each neuron appearing in any list: `score = sum over lists of 1 / (k + rank + 1)` where `k = 60` and `rank` is 0-based position within the list.

Key properties:
- Rank-based only — raw BM25 scores and vector distances are not used in the formula.
- Neurons appearing in both lists receive contributions from both, naturally boosting overlap.
- Neurons appearing in only one list are still included.
- The union of all candidates from both lists forms the RRF-scored candidate set.

The output of RRF is a list of `(neuron_id, rrf_score)` pairs sorted by descending `rrf_score`. This is the "direct match" set — neurons that were hit by the query.

---

### Stage 5 — Spreading Activation Fan-Out

Spreading activation extends the result set by traversing the graph outward from the direct match set (RRF output neurons serve as seeds).

**Algorithm: Python BFS with linear decay**

- Seeds: all neuron IDs in the RRF result set, each initialized with activation score 1.0.
- A visited set prevents re-processing nodes but allows score updates: if a node is reached via a new path with higher activation, its score is updated to the maximum of the old and new scores (max-score combination).
- For each seed at depth `d`, neighbors are retrieved from the edges table.
- Activation at the next hop: `activation = max(0.0, 1.0 - (depth + 1) * decay_rate)` where `decay_rate` defaults to 0.25.
- Default linear decay values: hop 0 = 1.00 (seed), hop 1 = 0.75, hop 2 = 0.50, hop 3 = 0.25, hop 4 = 0.00 (natural cutoff).
- Edge weight modulation: activation passed to a neighbor is `activation * edge_weight`, where `edge_weight` comes from the edges table (default 1.0). This allows strong edges to carry more activation and weak edges to dampen it.
- BFS stops at depth = `--fan-out-depth` (default 1). At depth 0 (`--fan-out-depth 0`), no traversal occurs — only direct matches are returned.
- Circular references are handled correctly by the visited set — the algorithm terminates even in graphs with cycles.

**Fan-out neurons** are neurons reached by spreading activation that were NOT in the direct match set. They are tagged in the output with their hop distance and the reason of the edge that connected them to the nearest seed.

**Activation score** for fan-out neurons is determined by the spreading activation BFS result (max score across all paths reaching that neuron).

**Direct match neurons** retain their RRF score as their primary ranking signal; their activation score is 1.0 (they are seeds).

---

### Stage 6 — Temporal Decay

Temporal decay boosts neurons that were created more recently. It applies to ALL neurons in the candidate set (both direct matches and fan-out).

The temporal factor is derived from the neuron's `created_at` timestamp. More recent neurons receive a higher temporal weight. The exact formula is a constraint (see Constraints section) but must satisfy:
- Monotonically decreasing with age — newer is always >= older.
- Bounded to a multiplier range that does not overwhelm the primary relevance signal.
- Age is measured relative to the current query time.

Temporal decay is a multiplicative modifier on the final combined score, not an additive component.

---

### Stage 7 — Tag Filtering

Tag filtering is applied to the full candidate set (direct matches + fan-out neurons) after spreading activation and before final ranking.

**AND filter (`--tags`):** A neuron is retained only if it has ALL of the specified tags. A neuron missing any one of the required tags is removed from the result set.

**OR filter (`--tags-any`):** A neuron is retained if it has AT LEAST ONE of the specified tags. A neuron with none of the specified tags is removed.

Both filters can be specified simultaneously. In that case, a neuron must satisfy BOTH filters to be retained (AND-filter AND OR-filter).

Tag names in filter flags are resolved to integer IDs before comparison. If a tag name does not exist in the registry, it matches no neurons (not an error).

No complex boolean grouping (nested AND/OR) is supported in v1.

Filtering is applied AFTER spreading activation, not before. This means a fan-out neuron that fails the tag filter is removed from results even if it was activated via a valid path. (Finding: this could cause confusion when spreading activation fans out through neurons that get filtered away. Flagged as a finding below.)

---

### Stage 8 — Final Score Combination and Ranking

After tag filtering, the final score for each neuron is computed from its component scores.

**For direct match neurons (in RRF set):**
`final_score = rrf_score * temporal_weight`

**For fan-out neurons (spreading activation only):**
`final_score = activation_score * temporal_weight`

The full candidate set (direct matches + fan-out neurons) is sorted by descending `final_score`. Direct match neurons do not inherently outrank fan-out neurons — a highly activated recent fan-out neuron may outrank a weak, old direct match.

---

### Stage 9 — Pagination

After ranking, `--offset M` neurons are skipped and `--limit N` neurons are returned. Defaults: limit=10, offset=0.

The total count of neurons in the result set (before pagination) is included in the output envelope so callers can detect whether more results exist.

---

### Stage 10 — Result Hydration and Output

Each neuron in the paginated result set is hydrated from the neurons table (#6) to retrieve: neuron ID, content, timestamp, project, tags (names, not IDs), source, and attributes.

**Output structure (per neuron):**

- `id` — neuron ID
- `content` — the stored text
- `timestamp` — ISO 8601 creation timestamp
- `project` — project context at capture time
- `tags` — list of tag names
- `source` — source field if set
- `attributes` — key-value attribute map
- `match_type` — `"direct"` if from RRF, `"fan_out"` if from spreading activation
- `hop_distance` — 0 for direct matches, 1+ for fan-out neurons
- `edge_reason` — for fan-out neurons, the reason of the edge that activated this neuron (the edge connecting it back toward the nearest seed). Null for direct matches.
- `score` — final combined score
- (if `--explain`) `score_breakdown` — see below

**Output envelope:**

```json
{
  "query": "<original query string>",
  "total": <count before pagination>,
  "offset": <M>,
  "limit": <N>,
  "results": [ ... ]
}
```

**--explain score breakdown (per neuron):**

When `--explain` is passed, each result includes a `score_breakdown` object with:
- `bm25_raw` — raw FTS5 BM25 score (negative number), or null if not in BM25 candidates
- `bm25_normalized` — `|bm25_raw| / (1 + |bm25_raw|)`, or null
- `bm25_rank` — 0-based rank position in BM25 candidate list, or null
- `vector_distance` — raw distance from vec_neurons query, or null if not in vector candidates
- `vector_rank` — 0-based rank position in vector candidate list, or null
- `rrf_score` — fused RRF score, or null if neuron was not a direct match
- `activation_score` — spreading activation score (1.0 for direct matches, 0.0–1.0 for fan-out)
- `hop_distance` — integer hop distance from nearest seed
- `temporal_weight` — the temporal decay multiplier applied
- `final_score` — the final combined score

If vector search was unavailable (BM25-fallback mode), the `--explain` output includes a top-level `"vector_unavailable": true` field.

---

### Output Format

Default output is JSON. Plain text format is available via `--format text` or config default. In plain text mode, each result is printed as a human-readable summary (content, score, match type, tags). The `--explain` breakdown is omitted or presented in a compact readable form in text mode.

---

### Exit Codes

| Code | Meaning |
|---|---|
| 0 | Search completed, one or more results returned |
| 1 | Search completed, no results found |
| 2 | Error (invalid flags, DB error, unrecoverable failure) |

---

## Constraints

1. **BM25 retrieval cap:** An internal cap limits BM25 candidates fed into RRF. The cap must be large enough not to truncate meaningful results but small enough to keep RRF fast. Value is configurable in `config.json`; default is 100.

2. **Vector retrieval cap:** Same cap as BM25 (100 default). The `k` parameter in the sqlite-vec query is set to this value.

3. **Two-step vector query is mandatory.** The vec_neurons virtual table MUST NOT be queried with JOINs. Only a standalone `SELECT neuron_id, distance FROM vec_neurons WHERE embedding MATCH ? AND k = ?` is permitted in the vec table. Joining the results to other tables is done in a subsequent separate query.

4. **Spreading activation uses visited set, not naive BFS.** The algorithm must not revisit nodes in a way that creates infinite loops on cyclic graphs.

5. **Temporal decay formula:** Not fully specified in requirements. The formula must be monotonically decreasing with age and bounded. The specific formula (e.g., exponential, linear, half-life-based) is deferred to implementation with the constraint that it must be configurable in `config.json`.

6. **Fan-out depth ceiling:** `--fan-out-depth` maximum allowed value is 3. Beyond depth 3, activation decays to 0 with the default decay rate; allowing higher depths would produce results with zero activation that waste query time. If `--fan-out-depth` > 3 is passed, the pipeline either silently caps at 3 or warns the user. Behavior is a finding (see below).

7. **RRF k value is fixed at 60.** It is not user-configurable per-query.

8. **Tag filter applies post-activation.** Fan-out neurons reachable only through tag-filtered-out intermediate neurons are still returned if they themselves pass the filter. The visited set is unaffected by tag filtering — activation can flow through neurons that will ultimately be filtered out of the output.

9. **No query expansion in light search.** Query expansion (related terms, semantic variants) is exclusively a heavy search (#9) feature. The light pipeline uses the raw query string only.

10. **Edge traversal direction:** Spreading activation follows edges in both directions (both `source_id` and `target_id` are queried). Rationale: edges represent relationships, not directed dependencies; a neuron linked to another is related in both directions. Finding: requirements do not specify directionality — flagged below.

11. **Embedding dimension mismatch:** If the stored vectors were produced with a different model (dimension mismatch), vector search must be skipped and a warning emitted. This is validated at query time using DB metadata (#13).

---

## Edge Cases

| Scenario | Behavior |
|---|---|
| Query matches no BM25 or vector results | Returns empty results (exit code 1) |
| Query matches BM25 but not vector (partial results) | RRF runs on BM25-only list; vector_rank null in --explain |
| Query matches vector but not BM25 (partial results) | RRF runs on vector-only list; bm25_rank null in --explain |
| Embedding engine unavailable | Fallback to BM25-only; --explain shows vector_unavailable: true |
| All candidates filtered out by tag filter | Returns empty results (exit code 1) |
| `--fan-out-depth 0` | Spreading activation disabled; only direct RRF results returned |
| Fan-out reaches a neuron with zero remaining activation | That neuron is not added to the result set |
| Fan-out neuron would also appear as a direct match | Treated as direct match (higher priority); RRF score wins over activation score |
| Cyclic graph in spreading activation | Visited set terminates the BFS; no infinite loop |
| `--limit 0` | Returns empty results list but populates total count in envelope |
| `--offset >= total` | Returns empty results list but populates total count in envelope |
| Both `--tags` and `--tags-any` specified | Neuron must satisfy both filters simultaneously |
| Unrecognized tag name in filter | Warning emitted; tag matches nothing; may produce empty results |
| `--tags` or `--tags-any` with no value | Error (exit code 2) |
| Multiple paths to same fan-out neuron | Max-score combination: neuron gets highest activation score seen across all paths |
| Edge weight = 0 | Neighbor receives 0.0 activation; not added to result set if threshold check is applied |
| Vector dimensions mismatched (stale model) | Vector search skipped; warning emitted; BM25-only fallback |
| BM25 query string contains FTS5 special characters | FTS5 handles escaping; if query is malformed and FTS5 raises an error, pipeline falls back to empty BM25 results with a warning |

---

## Findings

**F-1: Temporal decay formula unspecified.**
Requirements state "recent neurons rank higher" but do not define the decay function (exponential, linear, half-life, etc.) or its parameters. The spec constrains it to be monotonically decreasing with age and configurable. The exact formula and its default parameters must be decided at scaffolding time.

**F-2: Tag filtering applied post-activation — possible confusion.**
If spreading activation fans out through neurons that are then tag-filtered away, callers may be confused about gaps in the result set (e.g., why did a connected neuron not appear?). An alternative design would pre-filter the candidate set before fan-out. This tradeoff is not addressed in requirements. Flagging for user decision: should tag filtering apply before or after spreading activation?

**F-3: Edge traversal directionality unspecified.**
Requirements describe edges as relationships between neurons but do not specify whether spreading activation follows only `source → target`, only `target → source`, or both directions. This spec defaults to bidirectional traversal. If the user intends edges to be directed (e.g., "A was used to create B" is one-directional), this needs clarification.

**F-4: `--fan-out-depth` ceiling behavior unspecified.**
Requirements cap fan-out at depth 4 (natural decay cutoff at default rate), but the spec must decide whether exceeding this cap is a silent clamp or a warning. No requirement covers this. Defaulting to warn + clamp.

**F-5: Fan-out neuron edge_reason — which edge?**
A fan-out neuron may be reached via multiple edges (if multiple seeds activated it). The spec says "the edge connecting it back toward the nearest seed." For max-score combination, the edge associated with the highest-activation path should be used. If two paths produce equal activation, the choice is arbitrary. This is an implementation detail but noted for correctness.

**F-6: Conflicting memories ranking.**
§10 states "most recent outranks by default." This is implemented via temporal decay, which boosts recent neurons. However, if two neurons have identical relevance scores and very similar timestamps, temporal decay may not produce a meaningful distinction. No tiebreaker is specified in requirements beyond recency. Flagging for awareness.

**F-7: Internal retrieval cap is configurable but has no documented name.**
The cap on BM25 and vector candidates fed into RRF affects result quality. It should be exposed in `config.json` under a named key (e.g., `search.retrieval_cap`). The exact key name is deferred to #2 Config spec.

**F-8: `--explain` in plain text mode.**
Requirements specify `--explain` for debug output but only describe JSON structure. Behavior of `--explain` when `--format text` is active is unspecified. This spec notes it as "compact readable form" but the exact format is deferred to implementation.
