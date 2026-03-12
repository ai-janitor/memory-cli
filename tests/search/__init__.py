# =============================================================================
# Package: tests.search
# Purpose: Test suite for the search subsystem — spec #8 (light search) and
#   spec #9 (heavy search). Tests mirror the source module structure:
#   one test file per pipeline stage, plus end-to-end pipeline tests.
# Rationale: Each pipeline stage is independently testable with mock inputs.
#   End-to-end tests verify stage integration and fallback paths (BM25-only).
#   Test isolation ensures stage changes don't cascade false failures.
# Responsibility:
#   - test_light_search_pipeline.py — End-to-end pipeline tests
#   - test_bm25_retrieval.py — FTS5 MATCH scoring tests
#   - test_vector_retrieval.py — Two-step KNN tests
#   - test_rrf_fusion.py — RRF formula and merge tests
#   - test_spreading_activation.py — BFS, decay, cycle handling tests
#   - test_temporal_decay.py — Exponential decay formula tests
#   - test_tag_filter_post_activation.py — AND/OR tag filter tests
#   - test_final_score_ranking.py — Score combination and sort tests
#   - test_explain_breakdown.py — Explain output field tests
#   - test_search_result_hydration.py — Hydration and envelope tests
#   - heavy/ — Heavy search tests (spec #9)
# Organization: One test file per source module, pytest conventions.
# =============================================================================
