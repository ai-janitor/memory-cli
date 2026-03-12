# =============================================================================
# Module: test_haiku_rerank.py
# Purpose: Test the Haiku re-ranking module — prompt construction, API call
#   mocking, response parsing, defensive ID reconciliation, and error handling.
# Rationale: Re-ranking is the most complex Haiku interaction. The defensive
#   reorder logic (unknown IDs, missing IDs, duplicates) is critical for
#   robustness since we can't control what Haiku returns. Every edge case
#   in the response parser must be tested.
# Responsibility:
#   - Test system prompt construction
#   - Test user message construction with content truncation
#   - Test response parsing: valid JSON array of ints
#   - Test response parsing: strip markdown fences
#   - Test response parsing: int-coercible strings (e.g., "42")
#   - Test defensive reorder: unknown IDs from Haiku are discarded
#   - Test defensive reorder: missing IDs appended at end
#   - Test defensive reorder: duplicate IDs in Haiku response
#   - Test defensive reorder: completely hallucinated response
#   - Test defensive reorder: empty Haiku response
#   - Test auth error (401/403) raises HaikuAuthError
#   - Test network error raises HaikuNetworkError
#   - Test malformed response raises HaikuMalformedResponse
# Organization:
#   1. Imports and fixtures
#   2. Prompt construction tests
#   3. Response parsing tests
#   4. Defensive reorder tests
#   5. Error handling tests
# =============================================================================

from __future__ import annotations

import pytest
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from memory_cli.search.heavy.haiku_rerank_by_neuron_ids import (
    MAX_CONTENT_PREVIEW,
    HaikuAuthError,
    HaikuMalformedResponse,
    HaikuNetworkError,
    _apply_defensive_reorder,
    _build_rerank_system_prompt,
    _build_rerank_user_message,
    _call_haiku_api,
    _parse_rerank_response,
    haiku_rerank,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def sample_candidates() -> List[Dict[str, Any]]:
    """List of 5 candidate neuron dicts with id and content fields.

    IDs: [10, 20, 30, 40, 50]
    Content: short strings for each.
    """
    return [
        {"id": 10, "content": "Python programming"},
        {"id": 20, "content": "SQLite database"},
        {"id": 30, "content": "Machine learning models"},
        {"id": 40, "content": "REST API design"},
        {"id": 50, "content": "Data structures"},
    ]


@pytest.fixture
def long_content_candidate() -> Dict[str, Any]:
    """Candidate with content exceeding MAX_CONTENT_PREVIEW.

    Content is 1000 chars — should be truncated to 500 + "..." in prompt.
    """
    return {"id": 99, "content": "x" * 1000}


# -----------------------------------------------------------------------------
# Prompt construction tests
# -----------------------------------------------------------------------------

class TestRerankPromptConstruction:
    """Test system and user prompt building."""

    def test_system_prompt_requests_json_array(self):
        """System prompt should instruct Haiku to return JSON array of IDs."""
        prompt = _build_rerank_system_prompt()
        assert "JSON" in prompt or "json" in prompt.lower()
        assert "array" in prompt.lower() or "[" in prompt

    def test_system_prompt_requests_all_ids(self):
        """System prompt should instruct Haiku to include ALL provided IDs."""
        prompt = _build_rerank_system_prompt()
        assert "ALL" in prompt or "all" in prompt.lower()

    def test_user_message_includes_query(self, sample_candidates):
        """User message should contain the original query text."""
        msg = _build_rerank_user_message("my search query", sample_candidates)
        assert "my search query" in msg

    def test_user_message_includes_all_candidate_ids(self, sample_candidates):
        """User message should list all candidate neuron IDs."""
        msg = _build_rerank_user_message("query", sample_candidates)
        for c in sample_candidates:
            assert str(c["id"]) in msg

    def test_user_message_truncates_long_content(self, long_content_candidate):
        """Content exceeding MAX_CONTENT_PREVIEW should be truncated.

        Truncated content should end with "..." to indicate truncation.
        """
        msg = _build_rerank_user_message("query", [long_content_candidate])
        assert "..." in msg
        # Ensure the full 1000 chars are NOT present (it got truncated)
        assert "x" * (MAX_CONTENT_PREVIEW + 1) not in msg

    def test_user_message_preserves_short_content(self, sample_candidates):
        """Content within MAX_CONTENT_PREVIEW should not be truncated."""
        msg = _build_rerank_user_message("query", sample_candidates)
        assert "Python programming" in msg
        # No truncation indicator on short content
        assert "Python programming..." not in msg


# -----------------------------------------------------------------------------
# Response parsing tests
# -----------------------------------------------------------------------------

class TestRerankResponseParsing:
    """Test parsing of Haiku API response into ID list."""

    def test_parse_valid_json_array(self):
        """Parse "[42, 17, 3, 88]" into [42, 17, 3, 88]."""
        result = _parse_rerank_response("[42, 17, 3, 88]")
        assert result == [42, 17, 3, 88]

    def test_parse_strips_markdown_fences(self):
        """Parse "```json\\n[42, 17]\\n```" — strip fences, get [42, 17]."""
        result = _parse_rerank_response("```json\n[42, 17]\n```")
        assert result == [42, 17]

    def test_parse_strips_plain_fences(self):
        """Parse "```\\n[42, 17]\\n```" — strip plain fences too."""
        result = _parse_rerank_response("```\n[42, 17]\n```")
        assert result == [42, 17]

    def test_parse_int_coercible_strings(self):
        """Parse '["42", "17"]' — coerce string elements to ints."""
        result = _parse_rerank_response('["42", "17"]')
        assert result == [42, 17]

    def test_parse_empty_array(self):
        """Parse "[]" — return empty list (valid but unusual)."""
        result = _parse_rerank_response("[]")
        assert result == []

    def test_parse_non_json_raises(self):
        """Parse "these are not IDs" — raise HaikuMalformedResponse."""
        with pytest.raises(HaikuMalformedResponse):
            _parse_rerank_response("these are not IDs")

    def test_parse_json_object_raises(self):
        """Parse '{"ids": [1, 2]}' — not an array, raise HaikuMalformedResponse."""
        with pytest.raises(HaikuMalformedResponse):
            _parse_rerank_response('{"ids": [1, 2]}')

    def test_parse_non_integer_elements_raises(self):
        """Parse '["hello", "world"]' — non-int-coercible, raise HaikuMalformedResponse."""
        with pytest.raises(HaikuMalformedResponse):
            _parse_rerank_response('["hello", "world"]')

    def test_parse_mixed_valid_invalid_raises(self):
        """Parse '[42, "hello", 17]' — mixed types, raise HaikuMalformedResponse."""
        with pytest.raises(HaikuMalformedResponse):
            _parse_rerank_response('[42, "hello", 17]')


# -----------------------------------------------------------------------------
# Defensive reorder tests
# -----------------------------------------------------------------------------

class TestDefensiveReorder:
    """Test reconciliation of Haiku IDs with actual candidates."""

    def _make_candidates(self, ids: List[int]) -> List[Dict[str, Any]]:
        return [{"id": i, "content": f"content-{i}"} for i in ids]

    def test_perfect_response_preserves_order(self):
        """When Haiku returns all IDs correctly, preserve Haiku's order.

        Candidates: [10, 20, 30], Haiku: [30, 10, 20] -> [30, 10, 20]
        """
        candidates = self._make_candidates([10, 20, 30])
        result = _apply_defensive_reorder([30, 10, 20], candidates)
        assert result == [30, 10, 20]

    def test_unknown_ids_discarded(self):
        """IDs from Haiku not in candidate set are silently dropped.

        Candidates: [10, 20, 30], Haiku: [30, 999, 10, 20] -> [30, 10, 20]
        """
        candidates = self._make_candidates([10, 20, 30])
        result = _apply_defensive_reorder([30, 999, 10, 20], candidates)
        assert result == [30, 10, 20]

    def test_missing_ids_appended_at_end(self):
        """Candidate IDs missing from Haiku's list are appended.

        Candidates: [10, 20, 30, 40], Haiku: [30, 10] -> [30, 10, 20, 40]
        Missing IDs (20, 40) appended in original candidate order.
        """
        candidates = self._make_candidates([10, 20, 30, 40])
        result = _apply_defensive_reorder([30, 10], candidates)
        assert result == [30, 10, 20, 40]

    def test_duplicate_ids_keep_first(self):
        """Duplicate IDs in Haiku response keep first occurrence only.

        Candidates: [10, 20, 30], Haiku: [30, 10, 30, 20] -> [30, 10, 20]
        """
        candidates = self._make_candidates([10, 20, 30])
        result = _apply_defensive_reorder([30, 10, 30, 20], candidates)
        assert result == [30, 10, 20]

    def test_completely_hallucinated_response(self):
        """All IDs from Haiku are unknown — fall back to original order.

        Candidates: [10, 20, 30], Haiku: [999, 888, 777] -> [10, 20, 30]
        """
        candidates = self._make_candidates([10, 20, 30])
        result = _apply_defensive_reorder([999, 888, 777], candidates)
        assert result == [10, 20, 30]

    def test_empty_haiku_response(self):
        """Empty Haiku response — all candidates appended in original order.

        Candidates: [10, 20, 30], Haiku: [] -> [10, 20, 30]
        """
        candidates = self._make_candidates([10, 20, 30])
        result = _apply_defensive_reorder([], candidates)
        assert result == [10, 20, 30]

    def test_single_candidate(self):
        """Single candidate — trivial case, always returns [id].

        Candidates: [10], Haiku: [10] -> [10]
        """
        candidates = self._make_candidates([10])
        result = _apply_defensive_reorder([10], candidates)
        assert result == [10]


# -----------------------------------------------------------------------------
# Error handling tests
# -----------------------------------------------------------------------------

class TestRerankErrorHandling:
    """Test error conditions from the Haiku API call."""

    def test_auth_401_raises_haiku_auth_error(self):
        """Mock API returning 401 — should raise HaikuAuthError."""
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 401
        with patch("httpx.post", return_value=mock_response):
            with pytest.raises(HaikuAuthError):
                _call_haiku_api("key", "model", "system", "user")

    def test_auth_403_raises_haiku_auth_error(self):
        """Mock API returning 403 — should raise HaikuAuthError."""
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 403
        with patch("httpx.post", return_value=mock_response):
            with pytest.raises(HaikuAuthError):
                _call_haiku_api("key", "model", "system", "user")

    def test_network_timeout_raises_haiku_network_error(self):
        """Mock API timing out — should raise HaikuNetworkError."""
        import httpx
        with patch("httpx.post", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(HaikuNetworkError):
                _call_haiku_api("key", "model", "system", "user")

    def test_rate_limit_429_raises_haiku_network_error(self):
        """Mock API returning 429 — treated as transient, HaikuNetworkError."""
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 429
        with patch("httpx.post", return_value=mock_response):
            with pytest.raises(HaikuNetworkError):
                _call_haiku_api("key", "model", "system", "user")

    def test_server_error_500_raises_haiku_network_error(self):
        """Mock API returning 500 — raise HaikuNetworkError."""
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 500
        with patch("httpx.post", return_value=mock_response):
            with pytest.raises(HaikuNetworkError):
                _call_haiku_api("key", "model", "system", "user")

    def test_connection_refused_raises_haiku_network_error(self):
        """Mock connection refused — raise HaikuNetworkError."""
        import httpx
        with patch("httpx.post", side_effect=httpx.ConnectError("connection refused")):
            with pytest.raises(HaikuNetworkError):
                _call_haiku_api("key", "model", "system", "user")
