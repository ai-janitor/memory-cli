# =============================================================================
# test_task_prefix.py — Tests for prefix constants and prepend logic
# =============================================================================
# Purpose:     Verify that task prefix constants have the correct values and
#              that prepend_prefix() correctly handles both operation types
#              and rejects invalid ones.
# Rationale:   Wrong prefixes silently degrade embedding quality — documents
#              and queries would be encoded incorrectly. These tests are a
#              safety net against accidental prefix changes.
# Responsibility:
#   - Test INDEX_PREFIX value is exactly "search_document: "
#   - Test QUERY_PREFIX value is exactly "search_query: "
#   - Test prepend_prefix with "index" operation
#   - Test prepend_prefix with "query" operation
#   - Test invalid operation raises ValueError
# Organization:
#   Simple pytest functions — no fixtures needed, pure logic tests.
# =============================================================================

from __future__ import annotations

import pytest

from memory_cli.embedding.task_prefix_search_document_query import (
    INDEX_PREFIX,
    QUERY_PREFIX,
    prepend_prefix,
)


class TestPrefixConstants:
    """Prefix constants must match nomic-embed-text-v1.5 expected format."""

    # --- Test: INDEX_PREFIX is "search_document: " ---
    # from memory_cli.embedding.task_prefix_search_document_query import INDEX_PREFIX
    # assert INDEX_PREFIX == "search_document: "
    # Note: trailing space is critical
    def test_index_prefix_value(self):
        assert INDEX_PREFIX == "search_document: "

    # --- Test: QUERY_PREFIX is "search_query: " ---
    # from memory_cli.embedding.task_prefix_search_document_query import QUERY_PREFIX
    # assert QUERY_PREFIX == "search_query: "
    # Note: trailing space is critical
    def test_query_prefix_value(self):
        assert QUERY_PREFIX == "search_query: "


class TestPrependPrefix:
    """prepend_prefix() applies the correct prefix based on operation type."""

    # --- Test: index operation prepends "search_document: " ---
    # result = prepend_prefix("hello world", "index")
    # assert result == "search_document: hello world"
    def test_index_operation_prepends_document_prefix(self):
        result = prepend_prefix("hello world", "index")
        assert result == "search_document: hello world"

    # --- Test: query operation prepends "search_query: " ---
    # result = prepend_prefix("hello world", "query")
    # assert result == "search_query: hello world"
    def test_query_operation_prepends_query_prefix(self):
        result = prepend_prefix("hello world", "query")
        assert result == "search_query: hello world"

    # --- Test: empty text gets prefix only ---
    # result = prepend_prefix("", "index")
    # assert result == "search_document: "
    def test_empty_text_gets_prefix_only(self):
        result = prepend_prefix("", "index")
        assert result == "search_document: "

    # --- Test: text with existing prefix-like content is not double-prefixed ---
    # result = prepend_prefix("search_document: already prefixed", "index")
    # assert result == "search_document: search_document: already prefixed"
    # (prepend is mechanical — no dedup logic)
    def test_no_dedup_of_existing_prefix_content(self):
        result = prepend_prefix("search_document: already prefixed", "index")
        assert result == "search_document: search_document: already prefixed"


class TestInvalidOperation:
    """Invalid operation types must raise ValueError."""

    # --- Test: unknown string raises ValueError ---
    # with pytest.raises(ValueError):
    #   prepend_prefix("text", "embed")
    def test_unknown_string_raises(self):
        with pytest.raises(ValueError):
            prepend_prefix("text", "embed")  # type: ignore[arg-type]

    # --- Test: None raises ValueError ---
    # with pytest.raises(ValueError):
    #   prepend_prefix("text", None)
    def test_none_raises(self):
        with pytest.raises(ValueError):
            prepend_prefix("text", None)  # type: ignore[arg-type]

    # --- Test: empty string raises ValueError ---
    # with pytest.raises(ValueError):
    #   prepend_prefix("text", "")
    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            prepend_prefix("text", "")  # type: ignore[arg-type]
