# =============================================================================
# Package: tests.search.heavy
# Purpose: Test suite for Haiku-assisted heavy/deep search — spec #9.
# Rationale: Each heavy search component has its own test module to keep
#   tests focused and independently runnable. Tests cover the orchestrator,
#   API key resolution, re-ranking, query expansion, and merge/pagination.
#   All Haiku API calls are mocked — no live API calls in tests.
# Responsibility:
#   - test_heavy_search_orchestrator.py — End-to-end flow, fallback on failure
#   - test_haiku_api_key.py — Key resolution, missing env var, empty value
#   - test_haiku_rerank.py — Rerank prompt, parse, unknown IDs, duplicates
#   - test_haiku_query_expansion.py — Expansion prompt, parse, malformed
#   - test_heavy_search_merge.py — Merge logic, dedup, pagination
# Organization: One test file per source module, pytest conventions.
# =============================================================================
