# Spec #9 — Heavy Search (Haiku-Assisted)

## Purpose

This spec covers the `--heavy` (alias `--deep`) flag on `memory neuron search`, which activates Haiku-assisted search. Heavy search operates in two phases on top of light search (#8): (1) Haiku re-ranks the light search result set for deeper semantic relevance, and (2) Haiku generates expanded query terms, which are fed back into light search for additional result coverage. The merged, re-ranked result set is returned as raw neuron data — Haiku never synthesizes or summarizes. The key distinction from light search is that an external LLM call is involved, requiring a valid Anthropic API key at runtime.

Heavy search is Tier 6 — it depends on #8 Light Search for its primary result pipeline and #2 Config for the Haiku API key environment variable name.

---

## Requirements Traceability

Addresses `REQUIREMENTS.md §4.2 Heavy Search` in full:

- Haiku re-ranks results for deeper relevance — §4.2 bullet 1
- Haiku generates query expansion (related search terms) — §4.2 bullet 2
- Returns raw data — no synthesis or summarization by the LLM — §4.2 bullet 3

Transitively inherits all §4.3 Search Output constraints (pagination, --explain, raw data only) from Spec #8.

---

## Dependencies

- **#8 Light Search Pipeline** — heavy search invokes light search as a subroutine, both for the initial result set and for re-running with expanded queries. All scoring, RRF fusion, spreading activation, and tag filtering come from Spec #8. Heavy search does not reimplement any of those.
- **#2 Config & Initialization** — provides `haiku.api_key_env_var`, the name of the environment variable holding the Anthropic API key. The key itself is resolved from the environment at call time, not from config.

---

## Behavior

### 9.1 — Trigger

Heavy search is activated by adding `--heavy` or `--deep` to the `memory neuron search` command. Both flags are aliases for the same behavior. No other command surfaces this flag in v1.

Example invocations:
```
memory neuron search "distributed consensus" --heavy
memory neuron search "project status" --deep --limit 20
memory neuron search "auth tokens" --heavy --tags security --explain
```

All existing `memory neuron search` flags remain valid alongside `--heavy`: `--limit`, `--offset`, `--tags`, `--tags-any`, `--fan-out-depth`, `--explain`, `--format`.

### 9.2 — API Key Resolution

Before any Haiku call, the CLI resolves the API key:

1. Read `haiku.api_key_env_var` from the loaded config (e.g., `"ANTHROPIC_API_KEY"`).
2. Look up that environment variable name in the current process environment.
3. If the variable is unset or empty, exit with code 2:
   `Haiku API key not found. Set the environment variable: <env_var_name>`
4. The resolved key value is used for all Haiku calls within this invocation. It is never logged, stored, or included in any output.

### 9.3 — Phase 1: Initial Light Search

Heavy search begins by running exactly the light search pipeline (#8) with the original query and all user-supplied flags (`--limit`, `--tags`, `--fan-out-depth`, etc.).

The result set from this phase is the **initial candidate set**. It is used as input to both Haiku sub-operations (re-ranking and query expansion).

The initial candidate set is fetched at an internally inflated limit to give Haiku meaningful re-ranking material (see §9.7 for the inflated limit behavior).

### 9.4 — Phase 2a: Haiku Re-Ranking

Haiku is called once with the original query and the full initial candidate set to re-rank for deeper semantic relevance.

**What is sent to Haiku:**
- The original search query (verbatim string)
- For each neuron in the initial candidate set: its neuron ID and its content text. Tags may be included as supporting context. Edge metadata is not included.
- A system instruction that Haiku must return only the neuron IDs in re-ranked order, without any synthesis, explanation, or summarization.

**What Haiku returns:**
- An ordered list of neuron IDs, ranked by relevance to the query from most to least relevant.
- Nothing else. No explanations. No summaries. No synthesized text.

**What the CLI does with the re-ranked list:**
- Replaces the original light-search rank order with Haiku's returned order.
- Neurons present in the initial candidate set but absent from Haiku's returned list are appended at the end in their original light-search order (defensive handling for Haiku omitting neurons).
- Neuron IDs in Haiku's returned list that are NOT in the initial candidate set are silently discarded (defensive handling for Haiku hallucinating IDs).

### 9.5 — Phase 2b: Haiku Query Expansion

Haiku is called a second time with the original query to generate related search terms.

**What is sent to Haiku:**
- The original search query (verbatim string).
- A system instruction that Haiku must return only a flat list of related search terms/phrases — no explanations, no other output.

**What Haiku returns:**
- A flat list of related search terms or short phrases. The CLI expects 3–8 terms. Terms may include synonyms, related concepts, or alternate phrasings relevant to the query.
- Nothing else.

**What the CLI does with the expanded terms:**
- For each expanded term, run an independent light search (#8) with that term as the query.
- All other search flags from the original invocation are preserved (`--tags`, `--tags-any`, `--fan-out-depth`, etc.). `--limit` is run at the inflated limit for expansion searches as well (see §9.7).
- The expanded-term result sets are collected.

### 9.6 — Merging Results

After Phase 2a and 2b are complete, the CLI merges results into a single final result set:

1. **Start with the re-ranked initial candidate set** (from §9.4) as the base ordering.
2. **Append neurons from expansion results** that are not already present in the base set, in the order they appear across expansion result sets (first-seen wins for deduplication).
3. **Apply final pagination**: apply `--limit` and `--offset` to the merged result set. The user-requested `--limit` applies here — the inflated limit used internally does not appear in the output.
4. **Return** the paginated, merged result set.

The result set returned to the caller contains: the matching neurons (same fields as light search output), plus any fan-out neurons with their edge reasons (same as light search). No Haiku-generated text appears anywhere in the output.

### 9.7 — Inflated Internal Limit

To give Haiku enough material to re-rank meaningfully, the internal limit used for the initial candidate set fetch and for expansion result sets is inflated relative to the user-requested `--limit`. The inflated limit is:

```
internal_limit = max(user_limit * 3, 30)
```

The `user_limit` is the value of `--limit` (defaulting to `search.default_limit` from config). The inflated limit is never exposed to the caller. The final output always respects the user's `--limit` and `--offset`.

### 9.8 — Haiku API Call Characteristics

- Haiku is called using the Anthropic Messages API.
- Model: `claude-haiku-4-5` (or whichever is current Haiku — the model identifier is fixed in the implementation, not configurable in v1).
- The two Haiku calls (re-ranking and query expansion) are logically independent. Whether they are issued sequentially or concurrently is an implementation decision not constrained by this spec.
- Each call has a short, focused system prompt. The prompts instruct Haiku to return only structured data (ordered ID list or term list), with no prose.
- No conversation history or multi-turn context is used — each Haiku call is a single-turn, stateless request.
- Temperature and other sampling parameters are not configurable in v1. The implementation may use defaults appropriate for deterministic/structured output.

### 9.9 — Output Format

Heavy search output follows the identical format as light search output (Spec #8, §4.3 Search Output):

- Default: JSON
- Text: human-readable (via `--format text`)
- Fields per result: neuron content, timestamp, project, tags, attributes, neuron ID
- Fan-out neurons included with edge reasons
- `--explain` flag: if provided, the scoring breakdown from the light search phase is preserved. No Haiku-specific scoring metadata is added to the explain output in v1.

There is no indication in the output that heavy search was used versus light search. The output schema is identical. The enrichment is invisible to the caller.

### 9.10 — Haiku Error Handling

All Haiku call failures are handled gracefully — heavy search must not crash the CLI.

**API key invalid or rejected (HTTP 401/403):**
Exit code 2: `Haiku authentication failed. Check the value of <env_var_name>.`

**Network error or timeout:**
Heavy search falls back to the light search result (initial candidate set, not re-ranked, no expansion). A warning is emitted on stderr: `Warning: Haiku call failed (<reason>). Returning light search results.`
Exit code: 0 (results were returned, just not heavy-enhanced).

**Haiku returns malformed or unexpected output (re-ranking phase):**
The re-ranking step is skipped. The initial light search order is preserved. Fall through to the expansion phase normally. Warning on stderr: `Warning: Haiku re-ranking returned unexpected output. Using original ranking.`

**Haiku returns malformed or unexpected output (expansion phase):**
The expansion step is skipped. The re-ranked initial candidate set is returned as-is. Warning on stderr: `Warning: Haiku query expansion returned unexpected output. Skipping expansion.`

**Haiku returns an empty re-ranked list:**
Treated as if Haiku returned all IDs in original order (no re-ranking effect). Warning on stderr.

**Haiku returns an empty expansion list:**
Expansion phase produces no additional results. The re-ranked initial set is returned. No warning needed — empty expansion is a valid (if unhelpful) response.

**Rate limiting (HTTP 429):**
Treated the same as a network error: fall back to light search results, warn on stderr.

---

## Constraints

- **No synthesis, no summarization.** Haiku is called as a ranking oracle and a term generator only. No Haiku-generated text appears in output under any circumstances.
- **Output schema is identical to light search.** The caller cannot detect from the output whether `--heavy` was used. This is intentional — callers should be able to swap `--heavy` in and out without changing downstream parsing.
- **API key is never logged.** The key resolved from the environment must not appear in any output, error message, debug trace, or `--explain` output.
- **Haiku is never used for coding, scaffolding, or code generation.** This is a runtime product feature only (REQUIREMENTS.md §12, CLAUDE.md).
- **No persistent state from heavy search.** Haiku re-ranking results and expanded terms are ephemeral to the invocation. Nothing is written to the DB.
- **All light search constraints are inherited.** Tag filtering, spreading activation, temporal decay, pagination, fan-out depth, and the `--explain` flag all behave identically to light search.
- **Heavy search does not change edge or neuron data.** It is a read-only operation.

---

## Edge Cases

### EC-1: `--heavy` used without the API key env var set
Detected at the start of the heavy search flow before any Haiku call. Exit code 2 with message identifying the missing env var name. No search results returned.

### EC-2: `--heavy` with `--limit 1`
Internal limit is `max(1*3, 30) = 30`. Haiku receives up to 30 candidates for re-ranking. Output returns the top 1 result after merging. Pagination works normally.

### EC-3: `--heavy` with `--offset` (pagination into heavy results)
The full merged set is computed, then `--offset` and `--limit` are applied. This means Haiku sees the full internal-limit candidate set regardless of offset. Pagination is applied at the end.

### EC-4: Initial light search returns zero results
If the original query matches nothing, the initial candidate set is empty. Haiku re-ranking is called with an empty set (or skipped — implementation may skip Haiku if there is nothing to re-rank). Query expansion still runs. If expansion terms find results, those are returned. If not, the final output is an empty result set. Exit code 1 (not found).

### EC-5: All expanded terms also return zero results
Final merged set is empty. Exit code 1.

### EC-6: `--heavy` combined with `--tags` or `--tags-any`
Tag filters are passed through to all light search calls — both the initial call and all expansion calls. Haiku does not override or expand the tag filter. Expansion terms are additional query strings, not additional tag constraints.

### EC-7: `--heavy` combined with `--explain`
The `--explain` flag produces scoring breakdowns from the light search phases. Re-ranking by Haiku occurs after scoring — the explain output reflects light-search scores, not Haiku's ranking judgment. The final output order reflects Haiku re-ranking, but the score values in `--explain` come from light search. This is a deliberate design choice: Haiku's ranking is opaque and not expressed as a numeric score.

### EC-8: Haiku returns duplicate neuron IDs in re-ranking response
First occurrence of each ID wins. Subsequent duplicates are discarded silently.

### EC-9: Haiku returns neuron IDs from expansion results mixed into re-ranking response
The re-ranking Haiku call receives only the initial candidate set IDs. Any IDs in Haiku's re-ranking response that are not in the initial candidate set are discarded (see §9.4 defensive handling). This applies even if those IDs legitimately exist in the DB — re-ranking is scoped to the initial candidate set.

### EC-10: `--heavy` and the embedding model is unavailable
Light search falls back to BM25-only (as specified in REQUIREMENTS.md §10 and Spec #8). Heavy search proceeds with the BM25-only light search results. The Haiku re-ranking and expansion calls still happen. No additional degradation beyond what light search already handles.

### EC-11: Query expansion generates terms that are duplicates of the original query
Expansion results for a duplicate term will heavily overlap with the initial candidate set. Deduplication in the merge step (§9.6) handles this correctly — duplicate neurons are not added twice. This is a correctness non-issue, just a minor efficiency concern.

### EC-12: Very large initial candidate set (e.g., internal limit of 300 from `--limit 100`)
Haiku receives up to 300 neuron content snippets in a single API call. Context window limits of the Haiku model apply. The spec does not define a maximum candidate set size for the re-ranking call — this is flagged as Finding F-2.

### EC-13: `--heavy` on an empty database
Initial light search returns nothing. Expansion queries also return nothing. Empty result set. Exit code 1.

### EC-14: Concurrent heavy searches from multiple agents
Each invocation is independent and stateless. No locking beyond what SQLite WAL mode provides for the read queries. Multiple concurrent heavy searches are safe.

---

## Findings

### Finding F-1: Model identifier is not configurable in v1
The spec fixes the Haiku model identifier in the implementation. The requirements do not specify a configurable Haiku model name in config. This is flagged: if the Haiku model is updated or replaced, a code change is required rather than a config change. Consider whether `haiku.model` should be a config key.

### Finding F-2: No maximum candidate set size defined for Haiku re-ranking call
The inflated internal limit formula (`max(limit * 3, 30)`) could produce large context payloads for high `--limit` values. At `--limit 200`, the re-ranking call would send 600 neuron summaries to Haiku. The Haiku context window can likely handle this, but there is no defined upper bound or truncation policy. Flagged for implementation decision: either cap the re-ranking candidate set at a reasonable maximum (e.g., 100) or document that very high limits are the user's responsibility.

### Finding F-3: Haiku call order (sequential vs. concurrent) is unspecified
The two Haiku calls (re-ranking and query expansion) are logically independent — re-ranking operates on the initial set, and expansion generates new queries. They could be issued concurrently to reduce latency. The spec leaves this to the implementation. Flagged as a performance consideration.

### Finding F-4: No streaming output defined
Light search returns results after the full pipeline completes. Heavy search adds two Haiku API calls on top, increasing latency. No streaming or progressive output is specified. The user may wait several seconds before seeing any results. Flagged as a UX consideration for future versions.

### Finding F-5: `--explain` does not expose Haiku re-ranking rationale
Haiku re-ranks silently — the re-ranking reason is not included in `--explain` output. The spec intentionally omits this (Haiku is instructed not to produce explanations). If the user wants to understand why results appear in their order, there is no mechanism for that in v1. Flagged as a potential UX gap.

### Finding F-6: Expansion terms language/locale behavior unspecified
If the query is in a non-English language, Haiku will likely generate expansion terms in the same language. The light search (BM25 + vector) should handle this correctly assuming the embedding model supports the language. No explicit locale handling is required, but this is flagged for completeness.

### Finding F-7: Haiku fallback to light search is silent by default (stderr warning only)
When Haiku fails and the system falls back to light search results, the caller receives a valid response with exit code 0. The warning goes to stderr. An AI agent calling the CLI via Bash may not observe stderr. Flagged: consider whether the JSON output should include a `"degraded": true` field or similar signal in the fallback case, so agents can detect that heavy search did not fully execute.
