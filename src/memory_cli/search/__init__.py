# =============================================================================
# Package: memory_cli.search
# Purpose: Search subsystem — algorithmic (light) and LLM-assisted (heavy)
#   search pipelines for the memory graph. The light pipeline (spec #8) handles
#   `memory neuron search` with a 10-stage scoring pipeline: BM25, vector KNN,
#   RRF fusion, spreading activation, temporal decay, tag filtering, and
#   result hydration.
# Rationale: Search is the primary read path for AI agents consuming the
#   memory graph. The pipeline is decomposed into single-responsibility stages
#   so each can be tested, tuned, and replaced independently. The light
#   pipeline is fully algorithmic (no LLM calls) for predictable latency and
#   cost. Heavy search (spec #9) adds LLM re-ranking and query expansion.
# Responsibility:
#   - light_search_pipeline_orchestrator.py — 10-stage pipeline coordinator
#   - bm25_retrieval_fts5_match.py — FTS5 MATCH, BM25 scoring, normalization
#   - vector_retrieval_two_step_knn.py — Two-step vec0 KNN (standalone, then hydrate)
#   - rrf_fusion_rank_based_k60.py — Reciprocal Rank Fusion with k=60
#   - spreading_activation_bfs_linear_decay.py — BFS spreading activation
#   - temporal_decay_exponential_halflife.py — Exponential temporal decay
#   - tag_filter_post_activation.py — Post-activation AND/OR tag filtering
#   - final_score_combine_and_rank.py — Score combination and ranking
#   - explain_scoring_breakdown.py — --explain score breakdown builder
#   - search_result_hydration_and_envelope.py — Result hydration and output envelope
#   - heavy/ — LLM-assisted search (spec #9, separate subpackage)
# Organization: One file per pipeline stage, orchestrator ties them together.
# =============================================================================

# --- Public API exports ---
# The main entry point for CLI commands is the pipeline orchestrator.

from .light_search_pipeline_orchestrator import light_search, SearchOptions, SearchResultEnvelope
