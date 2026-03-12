# =============================================================================
# Module: test_haiku_query_expansion.py
# Purpose: Test the Haiku query expansion module — prompt construction,
#   response parsing, term count validation, and error handling.
# Rationale: Query expansion enriches search recall but is only valuable if
#   the terms are well-parsed and bounded. Tests ensure the prompt asks for
#   the right output format, the parser handles edge cases, and the term
#   count constraints (3-8) are enforced.
# Responsibility:
#   - Test system prompt requests JSON array of term strings
#   - Test user message contains original query
#   - Test response parsing: valid JSON array of strings
#   - Test response parsing: strip markdown fences
#   - Test response parsing: strip whitespace from terms
#   - Test response parsing: filter empty strings
#   - Test term count: truncate to MAX_EXPANSION_TERMS (8) if too many
#   - Test term count: raise if fewer than MIN_EXPANSION_TERMS (3)
#   - Test empty response raises HaikuMalformedResponse
#   - Test non-array response raises HaikuMalformedResponse
#   - Test non-string elements raise HaikuMalformedResponse
# Organization:
#   1. Imports and fixtures
#   2. Prompt construction tests
#   3. Response parsing happy path tests
#   4. Term count boundary tests
#   5. Malformed response tests
# =============================================================================

from __future__ import annotations

import json
import pytest
from typing import List
from unittest.mock import MagicMock, patch

from memory_cli.search.heavy.haiku_query_expansion_terms import (
    MAX_EXPANSION_TERMS,
    MIN_EXPANSION_TERMS,
    _build_expansion_system_prompt,
    _build_expansion_user_message,
    _parse_expansion_response,
    haiku_expand_query,
)
from memory_cli.search.heavy.haiku_rerank_by_neuron_ids import HaikuMalformedResponse


# -----------------------------------------------------------------------------
# Prompt construction tests
# -----------------------------------------------------------------------------

class TestExpansionPromptConstruction:
    """Test system and user prompt building for expansion."""

    def test_system_prompt_requests_json_array(self):
        """System prompt should instruct Haiku to return JSON array of strings."""
        prompt = _build_expansion_system_prompt()
        assert "JSON" in prompt or "json" in prompt.lower()
        assert "array" in prompt.lower() or "[" in prompt

    def test_system_prompt_specifies_term_count(self):
        """System prompt should request 3-8 related terms."""
        prompt = _build_expansion_system_prompt()
        assert "3" in prompt and "8" in prompt

    def test_system_prompt_requests_short_terms(self):
        """System prompt should request short terms (1-4 words)."""
        prompt = _build_expansion_system_prompt()
        assert "4" in prompt or "short" in prompt.lower()

    def test_user_message_contains_query(self):
        """User message should contain the original query text."""
        msg = _build_expansion_user_message("my search query")
        assert "my search query" in msg

    def test_user_message_format(self):
        """User message should follow "Query: <query>" format."""
        msg = _build_expansion_user_message("test query")
        assert msg == "Query: test query"


# -----------------------------------------------------------------------------
# Response parsing happy path tests
# -----------------------------------------------------------------------------

class TestExpansionResponseParsing:
    """Test successful parsing of expansion responses."""

    def test_parse_valid_json_array(self):
        """Parse '["term1", "term2", "term3"]' into list of 3 strings."""
        result = _parse_expansion_response('["term1", "term2", "term3"]')
        assert result == ["term1", "term2", "term3"]

    def test_parse_strips_markdown_fences(self):
        """Parse response with ```json fences — strip and parse."""
        response = '```json\n["term1", "term2", "term3"]\n```'
        result = _parse_expansion_response(response)
        assert result == ["term1", "term2", "term3"]

    def test_parse_strips_term_whitespace(self):
        """Parse '["  term1  ", " term2 ", "term3"]' — strip each term."""
        result = _parse_expansion_response('["  term1  ", " term2 ", "term3"]')
        assert result == ["term1", "term2", "term3"]

    def test_parse_filters_empty_strings(self):
        """Parse '["term1", "", "term2", "  ", "term3"]' — filter empties.

        After stripping, "" and "  " become empty and are filtered out.
        Result: ["term1", "term2", "term3"].
        """
        result = _parse_expansion_response('["term1", "", "term2", "  ", "term3"]')
        assert result == ["term1", "term2", "term3"]

    def test_parse_five_terms(self):
        """Parse 5 terms — within range, all returned."""
        terms = ["a", "b", "c", "d", "e"]
        result = _parse_expansion_response(json.dumps(terms))
        assert result == terms

    def test_parse_eight_terms(self):
        """Parse 8 terms — at max, all returned."""
        terms = ["a", "b", "c", "d", "e", "f", "g", "h"]
        result = _parse_expansion_response(json.dumps(terms))
        assert result == terms


# -----------------------------------------------------------------------------
# Term count boundary tests
# -----------------------------------------------------------------------------

class TestExpansionTermCount:
    """Test term count constraints (3-8)."""

    def test_truncate_to_max_terms(self):
        """When Haiku returns more than 8 terms, truncate to first 8."""
        terms = [f"term{i}" for i in range(12)]
        result = _parse_expansion_response(json.dumps(terms))
        assert len(result) == MAX_EXPANSION_TERMS
        assert result == terms[:MAX_EXPANSION_TERMS]

    def test_exactly_three_terms_valid(self):
        """3 terms is the minimum — should be accepted."""
        result = _parse_expansion_response('["a", "b", "c"]')
        assert result == ["a", "b", "c"]

    def test_two_terms_raises(self):
        """Fewer than 3 valid terms — raise HaikuMalformedResponse.

        Not enough useful terms to justify the expansion cost.
        """
        with pytest.raises(HaikuMalformedResponse):
            _parse_expansion_response('["a", "b"]')

    def test_one_term_raises(self):
        """Single term — raise HaikuMalformedResponse."""
        with pytest.raises(HaikuMalformedResponse):
            _parse_expansion_response('["single"]')

    def test_zero_terms_after_filter_raises(self):
        """All terms are empty after stripping — raise HaikuMalformedResponse."""
        with pytest.raises(HaikuMalformedResponse):
            _parse_expansion_response('["", "  ", "   "]')


# -----------------------------------------------------------------------------
# Malformed response tests
# -----------------------------------------------------------------------------

class TestExpansionMalformedResponse:
    """Test error handling for unparseable responses."""

    def test_empty_response_raises(self):
        """Empty string response — raise HaikuMalformedResponse."""
        with pytest.raises(HaikuMalformedResponse):
            _parse_expansion_response("")

    def test_non_json_raises(self):
        """Non-JSON text — raise HaikuMalformedResponse."""
        with pytest.raises(HaikuMalformedResponse):
            _parse_expansion_response("not json at all")

    def test_json_object_raises(self):
        """JSON object instead of array — raise HaikuMalformedResponse."""
        with pytest.raises(HaikuMalformedResponse):
            _parse_expansion_response('{"terms": ["a", "b", "c"]}')

    def test_json_array_of_numbers_raises(self):
        """Array of numbers instead of strings — raise HaikuMalformedResponse."""
        with pytest.raises(HaikuMalformedResponse):
            _parse_expansion_response("[1, 2, 3, 4, 5]")

    def test_null_response_raises(self):
        """JSON null — raise HaikuMalformedResponse."""
        with pytest.raises(HaikuMalformedResponse):
            _parse_expansion_response("null")

    def test_nested_arrays_raises(self):
        """Nested arrays — raise HaikuMalformedResponse.

        '[["term1", "term2"]]' is not a flat list of strings.
        """
        with pytest.raises(HaikuMalformedResponse):
            _parse_expansion_response('[["term1", "term2"], ["term3"]]')
