# =============================================================================
# Module: test_heavy_search_orchestrator.py
# Purpose: Test the end-to-end heavy search flow including inflated limit
#   calculation, light search delegation, Haiku phase orchestration,
#   graceful fallback on Haiku failure, and empty initial results shortcut.
# Rationale: The orchestrator is the integration point — testing it verifies
#   that all phases are called in the right order with the right data, and
#   that failure in any Haiku phase degrades gracefully to light search
#   results rather than crashing.
# Responsibility:
#   - Test inflated limit calculation (multiplier vs floor)
#   - Test full pipeline with mocked light search and Haiku calls
#   - Test fallback when Haiku rerank fails (network/timeout/malformed)
#   - Test fallback when Haiku expansion fails
#   - Test fallback when both Haiku phases fail (pure light search fallback)
#   - Test empty initial results short-circuits (no Haiku calls made)
#   - Test API key resolution failure causes sys.exit(2)
#   - Test auth error (401/403) causes sys.exit(2)
#   - Test result envelope matches light search schema
# Organization:
#   1. Imports and fixtures
#   2. Inflated limit tests
#   3. Full pipeline tests (happy path)
#   4. Haiku failure fallback tests
#   5. Empty results shortcut tests
#   6. Auth/key error tests
# =============================================================================

from __future__ import annotations

import pytest
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from memory_cli.search.heavy.heavy_search_orchestrator import (
    DEFAULT_HAIKU_MODEL,
    INFLATED_LIMIT_FLOOR,
    INFLATED_LIMIT_MULTIPLIER,
    _inflate_limit,
    heavy_search,
)
from memory_cli.search.heavy.haiku_api_key_resolution import HaikuApiKeyError
from memory_cli.search.heavy.haiku_rerank_by_neuron_ids import (
    HaikuAuthError,
    HaikuMalformedResponse,
    HaikuNetworkError,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def mock_config():
    """ConfigSchema-like object with haiku section configured.

    haiku.api_key_env_var = "ANTHROPIC_API_KEY"
    haiku.model = "claude-haiku-4-5-20251001"
    """
    config = MagicMock()
    config.haiku.api_key_env_var = "ANTHROPIC_API_KEY"
    config.haiku.model = "claude-haiku-4-5-20251001"
    return config


@pytest.fixture
def mock_conn():
    """Mock SQLite connection (not used directly — light search is mocked)."""
    return MagicMock()


def _make_light_results(n: int = 5):
    """Create a mock SearchResultEnvelope with n results."""
    @dataclass
    class MockEnvelope:
        results: List[Dict[str, Any]] = field(default_factory=list)
        total_before_pagination: int = 0
        limit: int = 10
        offset: int = 0
        vector_unavailable: bool = False
        exit_code: int = 0

    items = [{"id": i + 1, "content": f"content-{i}", "score": 0.9 - i * 0.1} for i in range(n)]
    return MockEnvelope(results=items, total_before_pagination=n)


def _make_empty_light_results():
    """Create a mock SearchResultEnvelope with no results."""
    @dataclass
    class MockEnvelope:
        results: List[Dict[str, Any]] = field(default_factory=list)
        total_before_pagination: int = 0
        limit: int = 10
        offset: int = 0
        vector_unavailable: bool = False
        exit_code: int = 1

    return MockEnvelope()


# -----------------------------------------------------------------------------
# Inflated limit tests
# -----------------------------------------------------------------------------

class TestInflateLimit:
    """Test the _inflate_limit() calculation."""

    def test_small_limit_uses_floor(self):
        """When user_limit * 3 < 30, should use floor of 30.

        _inflate_limit(5) -> 30 (5*3=15 < 30, use floor)
        """
        assert _inflate_limit(5) == 30

    def test_exact_floor_boundary(self):
        """When user_limit * 3 == 30, should return 30.

        _inflate_limit(10) -> 30 (10*3=30 == floor)
        """
        assert _inflate_limit(10) == 30

    def test_large_limit_uses_multiplier(self):
        """When user_limit * 3 > 30, should use multiplier.

        _inflate_limit(20) -> 60 (20*3=60 > 30)
        """
        assert _inflate_limit(20) == 60

    def test_limit_of_one(self):
        """Edge case: limit=1 should still use floor.

        _inflate_limit(1) -> 30 (1*3=3 < 30)
        """
        assert _inflate_limit(1) == 30


# -----------------------------------------------------------------------------
# Full pipeline tests (happy path)
# -----------------------------------------------------------------------------

class TestHeavySearchHappyPath:
    """Test the full pipeline with all phases succeeding."""

    def test_calls_light_search_with_inflated_limit(self, mock_conn, mock_config):
        """Verify light search is called with inflated limit, not user limit.

        Mock light search, call heavy_search(limit=10).
        Assert light_search was called with limit=30, offset=0.
        """
        light_result = _make_light_results(5)
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result) as mock_ls:
                with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_rerank", return_value=[1, 2, 3, 4, 5]):
                    with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_expand_query", return_value=["term1", "term2", "term3"]):
                        heavy_search(mock_conn, "query", mock_config, limit=10)
        # First call to light_search should have limit=30
        first_call = mock_ls.call_args_list[0]
        options = first_call[0][1]
        assert options.limit == 30
        assert options.offset == 0

    def test_passes_tag_filter_to_light_search(self, mock_conn, mock_config):
        """Verify tag_filter is forwarded to light search unchanged."""
        light_result = _make_light_results(3)
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result) as mock_ls:
                with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_rerank", return_value=[1, 2, 3]):
                    with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_expand_query", return_value=["t1", "t2", "t3"]):
                        heavy_search(mock_conn, "query", mock_config, tag_filter=["python"])
        first_call = mock_ls.call_args_list[0]
        options = first_call[0][1]
        assert "python" in options.tags

    def test_returns_correct_envelope_schema(self, mock_conn, mock_config):
        """Verify output has query, results, total, limit, offset keys."""
        light_result = _make_light_results(5)
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result):
                with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_rerank", return_value=[1, 2, 3, 4, 5]):
                    with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_expand_query", return_value=["t1", "t2", "t3"]):
                        result = heavy_search(mock_conn, "my query", mock_config, limit=5)
        assert "query" in result
        assert "results" in result
        assert "total" in result
        assert "limit" in result
        assert "offset" in result

    def test_applies_user_limit_to_final_results(self, mock_conn, mock_config):
        """Verify final results are limited to user's requested limit, not inflated."""
        light_result = _make_light_results(10)
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result):
                with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_rerank", return_value=list(range(1, 11))):
                    with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_expand_query", return_value=["t1", "t2", "t3"]):
                        result = heavy_search(mock_conn, "query", mock_config, limit=3)
        assert len(result["results"]) <= 3

    def test_applies_user_offset_to_final_results(self, mock_conn, mock_config):
        """Verify final results respect user's offset for pagination."""
        light_result = _make_light_results(10)
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result):
                with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_rerank", return_value=list(range(1, 11))):
                    with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_expand_query", return_value=["t1", "t2", "t3"]):
                        result = heavy_search(mock_conn, "query", mock_config, limit=10, offset=5)
        assert result["offset"] == 5


# -----------------------------------------------------------------------------
# Haiku failure fallback tests
# -----------------------------------------------------------------------------

class TestHeavySearchFallback:
    """Test graceful degradation when Haiku calls fail."""

    def test_rerank_network_error_falls_back(self, mock_conn, mock_config):
        """When rerank raises HaikuNetworkError, use original light search order.

        Final results should be in light search order (not reranked).
        Warning should be printed to stderr.
        """
        light_result = _make_light_results(3)
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result):
                with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_rerank", side_effect=HaikuNetworkError("timeout")):
                    with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_expand_query", return_value=["t1", "t2", "t3"]):
                        result = heavy_search(mock_conn, "query", mock_config, limit=10)
        # Should still return results (fallback, not crash)
        assert "results" in result

    def test_rerank_malformed_response_falls_back(self, mock_conn, mock_config):
        """When rerank raises HaikuMalformedResponse, use original order."""
        light_result = _make_light_results(3)
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result):
                with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_rerank", side_effect=HaikuMalformedResponse("bad")):
                    with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_expand_query", return_value=["t1", "t2", "t3"]):
                        result = heavy_search(mock_conn, "query", mock_config, limit=10)
        assert "results" in result

    def test_expansion_network_error_skips_expansion(self, mock_conn, mock_config):
        """When expansion raises HaikuNetworkError, no expansion results appended.

        Final results should be reranked candidates only.
        Warning should be printed to stderr.
        """
        light_result = _make_light_results(3)
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result):
                with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_rerank", return_value=[1, 2, 3]):
                    with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_expand_query", side_effect=HaikuNetworkError("net")):
                        result = heavy_search(mock_conn, "query", mock_config, limit=10)
        assert "results" in result

    def test_expansion_malformed_response_skips_expansion(self, mock_conn, mock_config):
        """When expansion raises HaikuMalformedResponse, no expansion results."""
        light_result = _make_light_results(3)
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result):
                with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_rerank", return_value=[1, 2, 3]):
                    with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_expand_query", side_effect=HaikuMalformedResponse("bad")):
                        result = heavy_search(mock_conn, "query", mock_config, limit=10)
        assert "results" in result

    def test_both_phases_fail_returns_light_results(self, mock_conn, mock_config):
        """When both rerank and expansion fail, return light search results.

        This is the full degradation path — heavy search becomes light search
        with a wider candidate pool (inflated limit).
        """
        light_result = _make_light_results(3)
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result):
                with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_rerank", side_effect=HaikuNetworkError("net")):
                    with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_expand_query", side_effect=HaikuNetworkError("net")):
                        result = heavy_search(mock_conn, "query", mock_config, limit=10)
        assert "results" in result
        assert len(result["results"]) <= 3

    def test_fallback_still_applies_pagination(self, mock_conn, mock_config):
        """Even on Haiku failure, user's limit/offset are applied to results."""
        light_result = _make_light_results(10)
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result):
                with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_rerank", side_effect=HaikuNetworkError("net")):
                    with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_expand_query", side_effect=HaikuNetworkError("net")):
                        result = heavy_search(mock_conn, "query", mock_config, limit=2)
        assert len(result["results"]) <= 2


# -----------------------------------------------------------------------------
# Empty results shortcut tests
# -----------------------------------------------------------------------------

class TestHeavySearchEmptyResults:
    """Test behavior when light search returns no results."""

    def test_empty_light_results_returns_empty(self, mock_conn, mock_config):
        """When light search returns 0 results, return empty immediately.

        No Haiku calls should be made (wasteful and pointless).
        """
        light_result = _make_empty_light_results()
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result):
                result = heavy_search(mock_conn, "query", mock_config, limit=10)
        assert result["results"] == []

    def test_empty_results_no_haiku_calls(self, mock_conn, mock_config):
        """Verify Haiku rerank and expansion are NOT called on empty results.

        Mock Haiku functions and assert they were never called.
        """
        light_result = _make_empty_light_results()
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result):
                with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_rerank") as mock_rerank:
                    with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_expand_query") as mock_expand:
                        heavy_search(mock_conn, "query", mock_config, limit=10)
        mock_rerank.assert_not_called()
        mock_expand.assert_not_called()

    def test_empty_results_envelope_schema(self, mock_conn, mock_config):
        """Verify empty result still returns correct envelope structure.

        { "query": ..., "results": [], "total": 0, "limit": ..., "offset": ... }
        """
        light_result = _make_empty_light_results()
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result):
                result = heavy_search(mock_conn, "my query", mock_config, limit=10, offset=0)
        assert result["query"] == "my query"
        assert result["results"] == []
        assert result["total"] == 0
        assert result["limit"] == 10
        assert result["offset"] == 0


# -----------------------------------------------------------------------------
# Auth/key error tests
# -----------------------------------------------------------------------------

class TestHeavySearchAuthErrors:
    """Test that auth errors cause hard failure (sys.exit(2))."""

    def test_missing_api_key_exits_2(self, mock_conn, mock_config):
        """When API key env var is not set, heavy_search should sys.exit(2).

        Mock resolve_haiku_api_key to raise HaikuApiKeyError.
        Assert SystemExit with code 2.
        """
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key",
                   side_effect=HaikuApiKeyError("not set")):
            with pytest.raises(SystemExit) as exc_info:
                heavy_search(mock_conn, "query", mock_config, limit=10)
        assert exc_info.value.code == 2

    def test_haiku_auth_401_exits_2(self, mock_conn, mock_config):
        """When Haiku returns 401, heavy_search should sys.exit(2).

        Mock rerank to raise HaikuAuthError.
        Assert SystemExit with code 2 (not a fallback — auth is a hard error).
        """
        light_result = _make_light_results(3)
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result):
                with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_rerank",
                           side_effect=HaikuAuthError("401")):
                    with pytest.raises(SystemExit) as exc_info:
                        heavy_search(mock_conn, "query", mock_config, limit=10)
        assert exc_info.value.code == 2

    def test_haiku_auth_403_exits_2(self, mock_conn, mock_config):
        """When Haiku returns 403, heavy_search should sys.exit(2).

        Same as 401 — forbidden is not a transient error.
        """
        light_result = _make_light_results(3)
        with patch("memory_cli.search.heavy.heavy_search_orchestrator.resolve_haiku_api_key", return_value="key"):
            with patch("memory_cli.search.heavy.heavy_search_orchestrator.light_search", return_value=light_result):
                with patch("memory_cli.search.heavy.heavy_search_orchestrator.haiku_rerank",
                           side_effect=HaikuAuthError("403")):
                    with pytest.raises(SystemExit) as exc_info:
                        heavy_search(mock_conn, "query", mock_config, limit=10)
        assert exc_info.value.code == 2
