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

import signal
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .bm25_retrieval_fts5_match import (
    retrieve_bm25, _build_fts5_query, _build_fts5_query_or, _normalize_bm25_score,
    FTS5_TABLE, BM25_CANDIDATE_CAP,
)
from .vector_retrieval_two_step_knn import retrieve_vectors
from .rrf_fusion_rank_based_k60 import fuse_rrf
from .spreading_activation_bfs_linear_decay import spread
from .temporal_decay_exponential_halflife import apply_temporal_decay
from .tag_affinity_scoring_shared_tags import apply_tag_affinity
from .salience_scoring_access_metrics import apply_salience_scoring
from .tag_filter_post_activation import filter_by_tags
from .final_score_combine_and_rank import compute_final_scores
from .explain_scoring_breakdown import build_explain_breakdowns
from .search_result_hydration_and_envelope import hydrate_results, build_envelope

# Embedding imports — done at module level so they can be mocked in tests.
# Will fail at import time only if the embedding package itself is broken,
# not if the model file is missing (that's caught at get_model() call time).
try:
    from memory_cli.embedding import get_model, embed_single, build_embedding_input
    from memory_cli.embedding import model_loader_lazy_singleton as _model_loader
    _EMBEDDING_AVAILABLE = True
except ImportError:
    _EMBEDDING_AVAILABLE = False
    get_model = None  # type: ignore
    embed_single = None  # type: ignore
    build_embedding_input = None  # type: ignore
    _model_loader = None  # type: ignore


# -----------------------------------------------------------------------------
# R3 — hard per-query wall-clock ceiling + stage-named self-reap
# Default 120s; CLI `--timeout <s>` raises/lowers it. SIGALRM interrupts a
# wedged stage (incl. time.sleep in tests / blocked model load) so no search
# PID outlives the ceiling.
# -----------------------------------------------------------------------------

DEFAULT_SEARCH_TIMEOUT_S = 120.0

# Thread-local-ish globals for the alarm handler (search is single-threaded CLI).
_deadline_stage: str = "init"
_deadline_timeout_s: float = DEFAULT_SEARCH_TIMEOUT_S


class SearchTimeoutError(Exception):
    """Raised when the per-query wall-clock ceiling is breached (R3)."""

    def __init__(self, stage: str, timeout_s: float):
        self.stage = stage
        self.timeout_s = timeout_s
        super().__init__(
            f"search timeout exceeded ({timeout_s:g}s) at stage {stage}"
        )


def _alarm_handler(signum, frame):  # noqa: ARG001
    raise SearchTimeoutError(_deadline_stage, _deadline_timeout_s)


def _set_stage(stage: str) -> None:
    """Record the pipeline stage currently executing (named in reap errors)."""
    global _deadline_stage
    _deadline_stage = stage


class _SearchDeadline:
    """Install a real-time ITIMER that raises SearchTimeoutError on breach."""

    def __init__(self, timeout_s: Optional[float]):
        # None → default; <=0 → disabled (not used by reds; defensive)
        if timeout_s is None:
            timeout_s = DEFAULT_SEARCH_TIMEOUT_S
        self.timeout_s = float(timeout_s)
        self._prev_handler = None
        self._armed = False

    def __enter__(self):
        global _deadline_timeout_s, _deadline_stage
        if self.timeout_s <= 0:
            return self
        _deadline_timeout_s = self.timeout_s
        _deadline_stage = "init"
        # SIGALRM only works on main thread (Unix CLI + pytest main).
        try:
            self._prev_handler = signal.signal(signal.SIGALRM, _alarm_handler)
            signal.setitimer(signal.ITIMER_REAL, self.timeout_s)
            self._armed = True
        except (ValueError, AttributeError, OSError):
            # Non-main thread / unsupported platform — best-effort no-op.
            self._armed = False
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._armed:
            try:
                signal.setitimer(signal.ITIMER_REAL, 0)
            except (ValueError, AttributeError, OSError):
                pass
            try:
                if self._prev_handler is not None:
                    signal.signal(signal.SIGALRM, self._prev_handler)
            except (ValueError, AttributeError, OSError):
                pass
        return False


# -----------------------------------------------------------------------------
# Search options — all CLI flags parsed into a structured object.
# -----------------------------------------------------------------------------

@dataclass
class SearchOptions:
    """Configuration for a single search invocation.

    Populated from CLI flags: --limit, --offset, --tag, --tag-mode, --type,
    --semantic, --fan-out-depth, --explain.

    ntype/tags (MEM-FIX-0007): when either is set and semantic is False,
    light_search() takes the facet fast-path — indexed attr/tag pre-filter,
    BM25-in-subset ranking, no embed/vector/activation. Pass semantic=True
    to opt a facet-scoped query back into the full pipeline.
    """
    query: str = ""
    limit: int = 20
    offset: int = 0
    tags: List[str] = field(default_factory=list)
    tag_mode: str = "AND"  # "AND" or "OR"
    fan_out_depth: int = 1  # default 1, max 3
    explain: bool = False
    ntype: Optional[str] = None
    semantic: bool = False
    # R3: wall-clock ceiling in seconds (CLI --timeout). None → DEFAULT_SEARCH_TIMEOUT_S.
    timeout_s: Optional[float] = None


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
    vector_unavailable_reason: Optional[str] = None

    # Stage 2: BM25 results — list of (neuron_id, raw_score, normalized_score)
    bm25_candidates: List[Dict[str, Any]] = field(default_factory=list)

    # Stage 3: Vector results — list of (neuron_id, distance)
    vector_candidates: List[Dict[str, Any]] = field(default_factory=list)

    # Stage 4: RRF fused candidates — list of (neuron_id, rrf_score)
    rrf_candidates: List[Dict[str, Any]] = field(default_factory=list)

    # Stage 5: Post-activation candidates with activation scores
    activated_candidates: List[Dict[str, Any]] = field(default_factory=list)

    # Stage 5b: Tag-affinity boosted candidates (after activation, before temporal)
    tag_affinity_boosted: List[Dict[str, Any]] = field(default_factory=list)

    # Stage 6: Temporal weights applied
    temporally_weighted: List[Dict[str, Any]] = field(default_factory=list)

    # Stage 6b: Salience-boosted candidates (after temporal, before tag filter)
    salience_boosted: List[Dict[str, Any]] = field(default_factory=list)

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
    vector_unavailable_reason: Optional[str] = None
    exit_code: int = 0  # 0=found, 1=no results, 2=error
    facet_fast: bool = False  # True when the facet fast-path served this result (MEM-FIX-0007)


def light_search(
    conn: sqlite3.Connection,
    options: SearchOptions,
    config: Optional["MemoryConfig"] = None,
) -> SearchResultEnvelope:
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
       - Match quality is the dominant base; affinity/salience/temporal are
         bounded modifiers around 1.0 (MEM-FIX-0006 / backlog #71).
       - direct_match → (rrf_score/RRF_MAX) * temporal * affinity_mod * salience_mod.
       - fan_out → activation_score * temporal * affinity_mod * salience_mod.
       - tag_affinity → capped_affinity_base * temporal * salience_mod.
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
    state = PipelineState()
    t_start = time.perf_counter()

    try:
        with _SearchDeadline(options.timeout_s):
            # --- MEM-FIX-0007: facet-scoped fast-path ---
            # --type/--tag scoped queries (no --semantic opt-out) resolve via the
            # existing attr/tag indexes and skip embed + vector + activation
            # entirely — no llama.cpp model load. See _facet_fast_search().
            # R2: record latency via the SHARED _record_latency helper so any R4
            # sampling/batch gate applies to both full and facet lanes. Do not
            # open-code a second INSERT path. Stage buckets: retrieval/scoring=0
            # (no embed/vector/activation); wall clock sits in output_ms
            # (resolve+rank+hydrate). Zero Llama load (guarded by R2 reds).
            if (options.ntype or options.tags) and not options.semantic:
                _set_stage("facet")
                envelope = _facet_fast_search(conn, options)
                total_ms = (time.perf_counter() - t_start) * 1000
                _record_latency(
                    conn, total_ms, 0.0, 0.0, total_ms,
                    len(envelope.results),
                )
                return envelope

            # --- Stages 1-3: Retrieval (embedding, BM25, vector) ---
            t0 = time.perf_counter()
            _run_retrieval_stage(conn, state, options, config=config)
            retrieval_ms = (time.perf_counter() - t0) * 1000

            # --- Stages 4-8: Scoring (RRF, activation, temporal, tag filter, final) ---
            t0 = time.perf_counter()
            _run_scoring_stage(conn, state, options)
            scoring_ms = (time.perf_counter() - t0) * 1000

            # --- Stages 9-10: Output (pagination, hydration, envelope) ---
            t0 = time.perf_counter()
            _set_stage("output")
            envelope = _run_output_stage(conn, state, options)
            output_ms = (time.perf_counter() - t0) * 1000

            total_ms = (time.perf_counter() - t_start) * 1000

            # --- Record latency ---
            _record_latency(
                conn, total_ms, retrieval_ms, scoring_ms, output_ms,
                len(envelope.results),
            )

            return envelope

    except SearchTimeoutError:
        # R3: re-raise so the CLI handler can emit a structured error (exit != 0)
        # naming the stage. Do NOT swallow into a soft exit_code=2 envelope.
        raise
    except Exception:
        # Database or pipeline error → exit code 2
        return SearchResultEnvelope(
            results=[],
            total_before_pagination=0,
            limit=options.limit,
            offset=options.offset,
            vector_unavailable=state.vector_unavailable,
            vector_unavailable_reason=state.vector_unavailable_reason,
            exit_code=2,
        )


def _facet_fast_search(
    conn: sqlite3.Connection,
    options: SearchOptions,
) -> SearchResultEnvelope:
    """Facet-scoped fast path (MEM-FIX-0007) — indexed pre-filter, no embed.

    Resolves candidates via the existing attr/tag indexes
    (idx_neuron_attrs_attr_key_id, idx_neuron_tags_tag_id), ranks the
    candidate set by BM25-in-subset (or recency for an empty query), then
    hydrates directly. Zero calls to get_model()/embed_single() — this is
    the storm-fix for --type/--tag gate lookups (minion bug #72).

    Logic flow:
    1. Resolve type-matching neuron ids (if options.ntype).
    2. Resolve tag-matching neuron ids honoring tag_mode (if options.tags).
    3. Intersect when both facets are given.
    4. Rank via _rank_facet_candidates() — BM25-in-subset, or recency when
       the query is empty.
    5. Paginate, hydrate, envelope. vector_unavailable stays False — this is
       a deliberate skip, not a degraded/error path; facet_fast=True marks it.

    Args:
        conn: SQLite connection.
        options: SearchOptions with ntype and/or tags set.

    Returns:
        SearchResultEnvelope, facet_fast=True.
    """
    candidate_ids: Optional[set] = None

    if options.ntype:
        candidate_ids = _resolve_type_candidates(conn, options.ntype)

    if options.tags:
        tag_ids = _resolve_tag_candidates(conn, options.tags, options.tag_mode)
        candidate_ids = tag_ids if candidate_ids is None else (candidate_ids & tag_ids)

    candidate_ids = candidate_ids or set()

    if not candidate_ids:
        return SearchResultEnvelope(
            results=[],
            total_before_pagination=0,
            limit=options.limit,
            offset=options.offset,
            vector_unavailable=False,
            vector_unavailable_reason=None,
            exit_code=1,
            facet_fast=True,
        )

    ranked = _rank_facet_candidates(conn, candidate_ids, options.query)
    total = len(ranked)
    paginated = ranked[options.offset:options.offset + options.limit]
    results = hydrate_results(conn, paginated, explain=options.explain)

    return SearchResultEnvelope(
        results=results,
        total_before_pagination=total,
        limit=options.limit,
        offset=options.offset,
        vector_unavailable=False,
        vector_unavailable_reason=None,
        exit_code=0 if results else 1,
        facet_fast=True,
    )


def _resolve_type_candidates(conn: sqlite3.Connection, ntype: str) -> set:
    """Resolve neuron ids whose 'type' attr equals ntype (indexed lookup).

    Query: neuron_attrs JOIN attr_keys WHERE name='type' AND value=ntype.
    Uses idx_neuron_attrs_attr_key_id (existing index — do not add another).
    """
    rows = conn.execute(
        "SELECT na.neuron_id FROM neuron_attrs na "
        "JOIN attr_keys ak ON na.attr_key_id = ak.id "
        "WHERE ak.name = 'type' AND na.value = ?",
        (ntype,),
    ).fetchall()
    return {row[0] for row in rows}


def _resolve_tag_candidates(
    conn: sqlite3.Connection,
    tags: List[str],
    tag_mode: str,
) -> set:
    """Resolve neuron ids matching the given tags under AND/OR mode.

    Uses idx_neuron_tags_tag_id (existing index — do not add another).
    AND: neuron must have every requested tag. OR: at least one.
    """
    if not tags:
        return set()
    placeholders = ",".join("?" * len(tags))
    required = {t.lower() for t in tags}
    rows = conn.execute(
        f"SELECT nt.neuron_id, t.name FROM neuron_tags nt "
        f"JOIN tags t ON nt.tag_id = t.id WHERE t.name IN ({placeholders})",
        list(required),
    ).fetchall()
    per_neuron: Dict[int, set] = {}
    for neuron_id, tag_name in rows:
        per_neuron.setdefault(neuron_id, set()).add(tag_name.lower())

    mode = (tag_mode or "AND").upper()
    if mode not in ("AND", "OR"):
        mode = "AND"
    if mode == "AND":
        return {nid for nid, names in per_neuron.items() if required.issubset(names)}
    return set(per_neuron.keys())  # OR: presence in per_neuron already means >=1 match


def _rank_facet_candidates(
    conn: sqlite3.Connection,
    candidate_ids: set,
    query: str,
) -> List[Dict[str, Any]]:
    """Rank a facet candidate set via staged relaxation (MEM-FIX-0008).

    Non-empty query, cheapest sufficient tier wins:
      Tier 1: quoted-AND MATCH in subset (today's behavior, unchanged).
              Non-empty hits -> return, match_type="direct_match".
      Tier 2: AND yielded zero -> retry with OR-joined quoted tokens, same
              subset/cap, ranked by BM25. Non-empty -> match_type="facet_or".
              Fixes multi-word gate phrases where no single row contains
              every token (e.g. "verify on live path" against a facet where
              rows only ever contain one or two of those tokens).
      Tier 3: still zero (or the query had no matchable tokens) -> recency
              fallback over the facet subset, match_type="facet_recency".
              Guarantees a non-empty facet never yields 0 results for a
              non-empty query.

    Empty query: rank by created_at desc (AC-6 — facet browse with no
    text), match_type="direct_match", unchanged from pre-0008 behavior.

    Capped at BM25_CANDIDATE_CAP, matching the full-pipeline BM25 stage.
    Zero model loads on any tier (REQ-3) — everything here is FTS5/SQL.
    """
    ids = list(candidate_ids)
    placeholders = ",".join("?" * len(ids))
    stripped = (query or "").strip()

    if stripped:
        fts5_query = _build_fts5_query(stripped)
        if fts5_query:
            rows = _facet_bm25_match(conn, fts5_query, ids, placeholders)
            if rows:
                return _facet_bm25_rows_to_candidates(rows, "direct_match")

            or_query = _build_fts5_query_or(stripped)
            if or_query:
                or_rows = _facet_bm25_match(conn, or_query, ids, placeholders)
                if or_rows:
                    return _facet_bm25_rows_to_candidates(or_rows, "facet_or")

        # Tier 3: AND and OR both empty (or the query had no valid FTS5
        # tokens) — recency fallback over the facet subset (REQ-1 floor).
        return _facet_recency_candidates(conn, ids, placeholders, "facet_recency")

    # Empty query — rank the facet set by recency (unchanged, AC-6).
    return _facet_recency_candidates(conn, ids, placeholders, "direct_match")


def _facet_bm25_match(
    conn: sqlite3.Connection,
    fts5_query: str,
    ids: List[int],
    placeholders: str,
) -> List[Any]:
    """Run a single FTS5 MATCH constrained to the facet subset. Shared by
    Tier 1 (AND) and Tier 2 (OR) of _rank_facet_candidates()."""
    try:
        return conn.execute(
            f"SELECT rowid, bm25({FTS5_TABLE}) AS raw_score FROM {FTS5_TABLE} "
            f"WHERE {FTS5_TABLE} MATCH ? AND rowid IN ({placeholders}) "
            f"ORDER BY raw_score LIMIT ?",
            [fts5_query] + ids + [BM25_CANDIDATE_CAP],
        ).fetchall()
    except sqlite3.OperationalError:
        return []


def _facet_bm25_rows_to_candidates(rows: List[Any], match_type: str) -> List[Dict[str, Any]]:
    """Map FTS5 (rowid, raw_score) rows to candidate dicts."""
    return [
        {
            "neuron_id": row[0],
            "match_type": match_type,
            "final_score": _normalize_bm25_score(row[1]),
            "hop_distance": 0,
            "edge_reason": None,
        }
        for row in rows
    ]


def _facet_recency_candidates(
    conn: sqlite3.Connection,
    ids: List[int],
    placeholders: str,
    match_type: str,
) -> List[Dict[str, Any]]:
    """Rank a facet id set by created_at desc, capped at BM25_CANDIDATE_CAP.
    Shared by the empty-query branch (unchanged, AC-6) and the MEM-FIX-0008
    Tier 3 fallback for a non-empty query that matched no facet rows."""
    rows = conn.execute(
        f"SELECT id FROM neurons WHERE id IN ({placeholders}) "
        f"ORDER BY created_at DESC LIMIT ?",
        ids + [BM25_CANDIDATE_CAP],
    ).fetchall()
    n = len(rows)
    return [
        {
            "neuron_id": row[0],
            "match_type": match_type,
            "final_score": 1.0 - (rank / n) * 0.5,
            "hop_distance": 0,
            "edge_reason": None,
        }
        for rank, row in enumerate(rows)
    ]


def _run_retrieval_stage(
    conn: sqlite3.Connection,
    state: PipelineState,
    options: SearchOptions,
    config: Optional["MemoryConfig"] = None,
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
    # --- Stage 1: Try to get query embedding ---
    # R1 seam: production uses embedding_daemon_client.embed (batch shape).
    # R3 reds patch THIS module's get_model/embed_single — when get_model is
    # not the real loader (tests), take the inproc path so patches bind.
    # SearchTimeoutError must propagate (not swallowed into BM25-only).
    _set_stage("embed")
    try:
        if not _EMBEDDING_AVAILABLE or get_model is None:
            raise RuntimeError("Embedding package not available")
        if config is None:
            from memory_cli.config import load_config
            config = load_config()
        embedding_input = build_embedding_input(options.query, [])
        use_daemon = (
            _model_loader is not None
            and get_model is _model_loader.get_model
        )
        if use_daemon:
            from memory_cli.embedding.embedding_daemon_client import embed as daemon_embed
            vectors = daemon_embed([embedding_input], "query", config)
            state.query_embedding = vectors[0] if vectors else None
            if state.query_embedding is None:
                raise RuntimeError("daemon client returned empty embedding batch")
        else:
            # Test / patched path: module-level get_model + embed_single
            model = get_model(config)
            state.query_embedding = embed_single(model, embedding_input, "query")
    except SearchTimeoutError:
        raise
    except Exception as exc:
        # Embedding unavailable — BM25-only fallback
        state.vector_unavailable = True
        state.vector_unavailable_reason = f"{type(exc).__name__}: {exc}"

    # --- Stage 2: BM25 retrieval ---
    _set_stage("bm25")
    state.bm25_candidates = retrieve_bm25(conn, options.query)

    # --- Stage 3: Vector retrieval (only if embedding available) ---
    if not state.vector_unavailable and state.query_embedding is not None:
        _set_stage("vector")
        state.vector_candidates = retrieve_vectors(conn, state.query_embedding)
    else:
        state.vector_candidates = []


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
    # --- Stage 4: RRF fusion ---
    _set_stage("rrf")
    state.rrf_candidates = fuse_rrf(state.bm25_candidates, state.vector_candidates)

    # --- Stage 5: Spreading activation ---
    _set_stage("activation")
    state.activated_candidates = spread(
        conn, state.rrf_candidates, fan_out_depth=options.fan_out_depth
    )

    # --- Stage 5b: Tag-affinity scoring ---
    # After activation discovers graph-connected neurons, tag-affinity boosts
    # neurons sharing tags with seeds and discovers tag-only neighbors.
    state.tag_affinity_boosted = apply_tag_affinity(conn, state.activated_candidates)

    # --- Stage 6: Temporal decay ---
    state.temporally_weighted = apply_temporal_decay(conn, state.tag_affinity_boosted)

    # --- Stage 6b: Salience scoring (access metrics boost) ---
    # Boosts neurons that are frequently and/or recently accessed.
    # Zero-access neurons get neutral weight (1.0) — no penalty.
    state.salience_boosted = apply_salience_scoring(conn, state.temporally_weighted)

    # --- Stage 7: Tag filtering (only if tags specified) ---
    if options.tags:
        state.tag_filtered = filter_by_tags(
            conn, state.salience_boosted, options.tags, options.tag_mode
        )
    else:
        state.tag_filtered = state.salience_boosted

    # --- Stage 8: Final score computation and ranking ---
    state.final_ranked = compute_final_scores(state.tag_filtered)


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
    # --- Stage 9: Pagination ---
    total = len(state.final_ranked)
    state.paginated = state.final_ranked[options.offset:options.offset + options.limit]

    # --- Stage 10: Hydration & explain breakdown ---
    if options.explain:
        build_explain_breakdowns(
            state.paginated, vector_unavailable=state.vector_unavailable
        )

    state.results = hydrate_results(conn, state.paginated, explain=options.explain)

    # --- Stage 11: Fuzzy fallback — only if primary search returned nothing ---
    # This is a last-resort safety net. If BM25 + vector + RRF all returned
    # zero results, try fuzzy matching against content, tags, and attrs.
    # Zero impact on the happy path — only fires on the empty-results path.
    if not state.results:
        from memory_cli.search.fuzzy_fallback_levenshtein import fuzzy_search
        fuzzy_candidates = fuzzy_search(conn, options.query, limit=options.limit)
        if fuzzy_candidates:
            state.results = hydrate_results(conn, fuzzy_candidates, explain=False)
            # Preserve fuzzy metadata through hydration
            for result, candidate in zip(state.results, fuzzy_candidates):
                result["match_type"] = "fuzzy"
                result["fuzzy_score"] = candidate["fuzzy_score"]
                result["fuzzy_matched_field"] = candidate["fuzzy_matched_field"]
            total = len(fuzzy_candidates)

    return SearchResultEnvelope(
        results=state.results,
        total_before_pagination=total,
        limit=options.limit,
        offset=options.offset,
        vector_unavailable=state.vector_unavailable,
        vector_unavailable_reason=state.vector_unavailable_reason,
        exit_code=0 if state.results else 1,
    )


def _record_latency(
    conn: sqlite3.Connection,
    total_ms: float,
    retrieval_ms: float,
    scoring_ms: float,
    output_ms: float,
    result_count: int,
) -> None:
    """Persist a search latency record to the search_latency table.

    R4: never write on the *search* connection when the DB is file-backed —
    open a short-lived side connection so the read path stays read-only and
    does not take the WAL writer slot. For :memory: (unit tests, R2 latency
    reds) write on the same connection so row counts remain observable.

    Best-effort: silently ignores errors (table may not exist / read-only).
    """
    recorded_at = int(time.time() * 1000)
    params = (total_ms, retrieval_ms, scoring_ms, output_ms, result_count, recorded_at)
    sql = (
        "INSERT INTO search_latency "
        "(total_ms, retrieval_ms, scoring_ms, output_ms, result_count, recorded_at) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    )

    def _write(target: sqlite3.Connection) -> None:
        target.execute(sql, params)
        target.commit()

    try:
        # Resolve main DB file path (empty / :memory: → same-conn path).
        file_path = ""
        try:
            rows = conn.execute("PRAGMA database_list").fetchall()
            for r in rows:
                # (seq, name, file)
                if r[1] == "main":
                    file_path = r[2] or ""
                    break
        except Exception:
            file_path = ""

        if file_path and file_path != ":memory:":
            # Side-channel writer — keeps search conn free of INSERT/commit.
            writer = sqlite3.connect(file_path)
            try:
                _write(writer)
            finally:
                writer.close()
            return

        # :memory: / unresolvable path — same connection (test observability).
        _write(conn)
    except Exception:
        # Table missing, read-only conn, or side-channel failure — never break search
        pass

