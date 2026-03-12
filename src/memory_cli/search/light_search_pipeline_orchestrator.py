# =============================================================================
# Module: light_search_pipeline_orchestrator.py
# Purpose: Main 10-stage pipeline coordinator for `memory neuron search`.
#   Orchestrates BM25, vector, RRF fusion, spreading activation, temporal
#   decay, tag filtering, scoring, and hydration into a single search call.
# Rationale: A central orchestrator keeps stage ordering explicit and lets
#   callers invoke one function instead of wiring 10 stages manually. The
#   pipeline degrades gracefully: if embeddings are unavailable, it falls
#   back to BM25-only mode with a vector_unavailable flag.
# Responsibility:
#   - Accept query string and search options (limit, offset, tags, fan-out-depth, explain)
#   - Execute 10 stages in order, passing intermediate results between stages
#   - Handle BM25-only fallback when vector retrieval is unavailable
#   - Return structured result envelope with pagination metadata
#   - Set exit codes: 0=results found, 1=no results, 2=error
# Organization:
#   1. Imports
#   2. Data classes / TypedDicts for pipeline state and options
#   3. light_search() — main entry point
#   4. _run_retrieval_stage() — BM25 + vector retrieval (or BM25-only fallback)
#   5. _run_scoring_stage() — RRF + activation + temporal + final scoring
#   6. _run_output_stage() — filtering, pagination, hydration, envelope
# =============================================================================

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# -----------------------------------------------------------------------------
# Search options — all CLI flags parsed into a structured object.
# -----------------------------------------------------------------------------

@dataclass
class SearchOptions:
    """Configuration for a single search invocation.

    Populated from CLI flags: --limit, --offset, --tag, --tag-mode,
    --fan-out-depth, --explain.
    """
    query: str = ""
    limit: int = 20
    offset: int = 0
    tags: List[str] = field(default_factory=list)
    tag_mode: str = "AND"  # "AND" or "OR"
    fan_out_depth: int = 1  # default 1, max 3
    explain: bool = False


# -----------------------------------------------------------------------------
# Pipeline state — intermediate results passed between stages.
# -----------------------------------------------------------------------------

@dataclass
class PipelineState:
    """Mutable state bag threaded through the 10 pipeline stages.

    Each stage reads what it needs and writes its outputs here.
    """
    # Stage 1: Query embedding
    query_embedding: Optional[List[float]] = None
    vector_unavailable: bool = False

    # Stage 2: BM25 results — list of (neuron_id, raw_score, normalized_score)
    bm25_candidates: List[Dict[str, Any]] = field(default_factory=list)

    # Stage 3: Vector results — list of (neuron_id, distance)
    vector_candidates: List[Dict[str, Any]] = field(default_factory=list)

    # Stage 4: RRF fused candidates — list of (neuron_id, rrf_score)
    rrf_candidates: List[Dict[str, Any]] = field(default_factory=list)

    # Stage 5: Post-activation candidates with activation scores
    activated_candidates: List[Dict[str, Any]] = field(default_factory=list)

    # Stage 6: Temporal weights applied
    temporally_weighted: List[Dict[str, Any]] = field(default_factory=list)

    # Stage 7: Tag-filtered candidates
    tag_filtered: List[Dict[str, Any]] = field(default_factory=list)

    # Stage 8: Final scored and ranked candidates
    final_ranked: List[Dict[str, Any]] = field(default_factory=list)

    # Stage 9: Paginated slice
    paginated: List[Dict[str, Any]] = field(default_factory=list)

    # Stage 10: Hydrated output records
    results: List[Dict[str, Any]] = field(default_factory=list)


# -----------------------------------------------------------------------------
# Search result envelope — the structured output returned to the CLI.
# -----------------------------------------------------------------------------

@dataclass
class SearchResultEnvelope:
    """Final output envelope with results, pagination, and metadata.

    Returned by light_search() and serialized to JSON/table by the CLI.
    """
    results: List[Dict[str, Any]] = field(default_factory=list)
    total_before_pagination: int = 0
    limit: int = 20
    offset: int = 0
    vector_unavailable: bool = False
    exit_code: int = 0  # 0=found, 1=no results, 2=error


def light_search(conn: sqlite3.Connection, options: SearchOptions) -> SearchResultEnvelope:
    """Execute the full 10-stage light search pipeline.

    This is the main entry point for `memory neuron search <query>`.

    Logic flow:
    1. QUERY EMBEDDING — embed query with "search_query:" prefix.
       - Call embedding module with search prefix.
       - If embedding unavailable (model not loaded, error) → set
         state.vector_unavailable = True, continue with BM25-only.
    2. BM25 RETRIEVAL — FTS5 MATCH query.
       - Call bm25_retrieval_fts5_match.retrieve_bm25()
       - Raw scores are negative; normalize via |x|/(1+|x|).
       - Internal cap of 100 candidates.
    3. VECTOR RETRIEVAL — Two-step vec0 KNN.
       - Skip if vector_unavailable.
       - Call vector_retrieval_two_step_knn.retrieve_vectors()
       - NEVER JOIN vec0 with neurons. Two separate queries.
       - Internal cap of 100 candidates.
    4. RRF FUSION — Reciprocal Rank Fusion.
       - Call rrf_fusion_rank_based_k60.fuse_rrf()
       - score = sum(1/(60 + rank + 1)) per candidate across lists.
       - Union of candidates from both lists.
    5. SPREADING ACTIVATION — BFS from RRF seeds.
       - Call spreading_activation_bfs_linear_decay.spread()
       - Seeds get activation=1.0.
       - Linear decay: activation = max(0, 1 - (depth+1) * decay_rate).
       - Edge weight modulates: activation * edge_weight.
       - Bidirectional edge traversal. Visited set with max-score update.
       - Depth controlled by options.fan_out_depth (default 1, max 3).
    6. TEMPORAL DECAY — Exponential decay on final score.
       - Call temporal_decay_exponential_halflife.apply_temporal_decay()
       - weight = e^(-lambda * t), half-life 30 days.
       - Multiplicative on score.
    7. TAG FILTERING — Post-activation AND/OR filter.
       - Call tag_filter_post_activation.filter_by_tags()
       - Only applied if options.tags is non-empty.
       - Activation flows through filtered-out neurons (they stay in
         the activation graph but are removed from final output).
    8. FINAL SCORE — Combine and rank.
       - Call final_score_combine_and_rank.compute_final_scores()
       - direct_match → rrf_score * temporal_weight.
       - fan_out → activation_score * temporal_weight.
       - Sort descending by final_score.
    9. PAGINATION — Apply --limit/--offset after ranking.
       - Slice the ranked list: [offset:offset+limit].
    10. HYDRATION & OUTPUT — Build result envelope.
        - Call search_result_hydration_and_envelope.hydrate_results()
        - Neuron fields + match_type + hop_distance + edge_reason +
          score + score_breakdown (if --explain).
        - Build SearchResultEnvelope with pagination metadata.

    Exit codes:
    - 0: Results found.
    - 1: No results match the query.
    - 2: Error during pipeline execution.

    Error handling:
    - Embedding failure → BM25-only fallback, not a fatal error.
    - Database errors → exit code 2 with error detail in envelope.
    - Empty BM25 + empty vector → exit code 1, no results.

    Args:
        conn: SQLite connection with all required tables and extensions.
        options: SearchOptions with query, filters, and display flags.

    Returns:
        SearchResultEnvelope with results, pagination, and metadata.
    """
    # --- Initialize pipeline state ---
    # state = PipelineState()

    # --- Stage 1: Query Embedding ---
    # Try to embed the query with "search_query:" prefix.
    # On failure: set state.vector_unavailable = True, log warning.

    # --- Stage 2: BM25 Retrieval ---
    # state.bm25_candidates = bm25_retrieval.retrieve_bm25(conn, options.query)

    # --- Stage 3: Vector Retrieval ---
    # if not state.vector_unavailable:
    #     state.vector_candidates = vector_retrieval.retrieve_vectors(
    #         conn, state.query_embedding
    #     )
    # else:
    #     state.vector_candidates = []

    # --- Stage 4: RRF Fusion ---
    # state.rrf_candidates = rrf_fusion.fuse_rrf(
    #     state.bm25_candidates, state.vector_candidates
    # )

    # --- Stage 5: Spreading Activation ---
    # state.activated_candidates = spreading_activation.spread(
    #     conn, state.rrf_candidates, fan_out_depth=options.fan_out_depth
    # )

    # --- Stage 6: Temporal Decay ---
    # state.temporally_weighted = temporal_decay.apply_temporal_decay(
    #     conn, state.activated_candidates
    # )

    # --- Stage 7: Tag Filtering ---
    # if options.tags:
    #     state.tag_filtered = tag_filter.filter_by_tags(
    #         conn, state.temporally_weighted, options.tags, options.tag_mode
    #     )
    # else:
    #     state.tag_filtered = state.temporally_weighted

    # --- Stage 8: Final Score ---
    # state.final_ranked = final_score.compute_final_scores(state.tag_filtered)

    # --- Stage 9: Pagination ---
    # total = len(state.final_ranked)
    # state.paginated = state.final_ranked[options.offset:options.offset + options.limit]

    # --- Stage 10: Hydration & Output ---
    # if options.explain:
    #     explain_breakdown.build_explain_breakdowns(
    #         state.paginated, vector_unavailable=state.vector_unavailable
    #     )
    # state.results = hydration.hydrate_results(
    #     conn, state.paginated, explain=options.explain
    # )

    # --- Build envelope ---
    # envelope = SearchResultEnvelope(
    #     results=state.results,
    #     total_before_pagination=total,
    #     limit=options.limit,
    #     offset=options.offset,
    #     vector_unavailable=state.vector_unavailable,
    #     exit_code=0 if state.results else 1,
    # )
    # return envelope

    pass


def _run_retrieval_stage(
    conn: sqlite3.Connection,
    state: PipelineState,
    options: SearchOptions,
) -> None:
    """Execute stages 1-3: embedding, BM25 retrieval, vector retrieval.

    Logic flow:
    1. Embed query text with "search_query:" prefix.
       - On success: store embedding in state.query_embedding.
       - On failure: set state.vector_unavailable = True.
    2. Run BM25 retrieval against FTS5 index.
       - Store results in state.bm25_candidates.
    3. If embedding available, run vector retrieval.
       - Store results in state.vector_candidates.
       - If unavailable, leave as empty list.

    Mutates state in-place.

    Args:
        conn: SQLite connection.
        state: Pipeline state to populate.
        options: Search options with query text.
    """
    pass


def _run_scoring_stage(
    conn: sqlite3.Connection,
    state: PipelineState,
    options: SearchOptions,
) -> None:
    """Execute stages 4-8: RRF, activation, temporal, tag filter, final score.

    Logic flow:
    1. RRF fusion of BM25 + vector candidates.
    2. Spreading activation BFS from RRF seeds.
    3. Apply temporal decay weights.
    4. Apply tag filter (if tags specified).
    5. Compute final scores and sort descending.

    Mutates state in-place.

    Args:
        conn: SQLite connection (needed for activation edge traversal).
        state: Pipeline state with retrieval results.
        options: Search options with tags, fan-out-depth, etc.
    """
    pass


def _run_output_stage(
    conn: sqlite3.Connection,
    state: PipelineState,
    options: SearchOptions,
) -> SearchResultEnvelope:
    """Execute stages 9-10: pagination, hydration, envelope construction.

    Logic flow:
    1. Record total count before pagination.
    2. Slice final_ranked by offset:offset+limit.
    3. Hydrate sliced results (neuron fields, tags, match metadata).
    4. If --explain, attach score_breakdown to each result.
    5. Build and return SearchResultEnvelope.

    Args:
        conn: SQLite connection (needed for hydration queries).
        state: Pipeline state with final ranked results.
        options: Search options with limit, offset, explain.

    Returns:
        SearchResultEnvelope ready for CLI serialization.
    """
    pass
