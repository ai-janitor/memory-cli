# =============================================================================
# test_embedding_input_construction.py — Tests for content+tags assembly
# =============================================================================
# Purpose:     Verify that build_embedding_input() correctly assembles the
#              embedding input string from neuron content and tags, handling
#              all edge cases (no tags, empty content, whitespace).
# Rationale:   The embedding input format directly affects retrieval quality.
#              Tags must be lowercased and space-separated. Whitespace handling
#              must be consistent to avoid embedding drift between identical
#              logical inputs with different formatting.
# Responsibility:
#   - Test content only (no tags)
#   - Test content with tags (tags lowercased, space-separated)
#   - Test empty tag list (same as no tags)
#   - Test None tags (same as no tags)
#   - Test empty content with tags (tags only)
#   - Test whitespace normalization (leading/trailing stripped)
#   - Test tags with mixed case are lowercased
#   - Test tags with whitespace are stripped
#   - Test empty string tags are filtered out
# Organization:
#   pytest functions grouped by scenario. No fixtures needed, pure logic.
# =============================================================================

from __future__ import annotations

import pytest

from memory_cli.embedding.embedding_input_content_plus_tags import build_embedding_input


class TestContentOnly:
    """Content with no tags returns just the content."""

    # --- Test: plain content, no tags argument ---
    # result = build_embedding_input("hello world")
    # assert result == "hello world"
    def test_plain_content_no_tags_arg(self):
        result = build_embedding_input("hello world")
        assert result == "hello world"

    # --- Test: plain content, tags=None ---
    # result = build_embedding_input("hello world", tags=None)
    # assert result == "hello world"
    def test_plain_content_tags_none(self):
        result = build_embedding_input("hello world", tags=None)
        assert result == "hello world"

    # --- Test: plain content, tags=[] (empty list) ---
    # result = build_embedding_input("hello world", tags=[])
    # assert result == "hello world"
    def test_plain_content_tags_empty_list(self):
        result = build_embedding_input("hello world", tags=[])
        assert result == "hello world"


class TestContentWithTags:
    """Content + tags produces "<content> <tag1> <tag2>"."""

    # --- Test: single tag ---
    # result = build_embedding_input("hello world", tags=["python"])
    # assert result == "hello world python"
    def test_single_tag(self):
        result = build_embedding_input("hello world", tags=["python"])
        assert result == "hello world python"

    # --- Test: multiple tags ---
    # result = build_embedding_input("hello world", tags=["python", "memory", "cli"])
    # assert result == "hello world python memory cli"
    def test_multiple_tags(self):
        result = build_embedding_input("hello world", tags=["python", "memory", "cli"])
        assert result == "hello world python memory cli"

    # --- Test: tags are lowercased ---
    # result = build_embedding_input("hello", tags=["Python", "MEMORY", "Cli"])
    # assert result == "hello python memory cli"
    def test_tags_are_lowercased(self):
        result = build_embedding_input("hello", tags=["Python", "MEMORY", "Cli"])
        assert result == "hello python memory cli"


class TestEdgeCases:
    """Edge cases: empty content, whitespace, empty tags in list."""

    # --- Test: empty content with tags ---
    # result = build_embedding_input("", tags=["python"])
    # assert result == " python" or assert result == "python"
    # (depends on design decision — document the chosen behavior)
    def test_empty_content_with_tags(self):
        result = build_embedding_input("", tags=["python"])
        # Empty content stripped -> "" + " " + "python" -> " python"
        assert result == " python"

    # --- Test: content with leading/trailing whitespace is stripped ---
    # result = build_embedding_input("  hello world  ", tags=["test"])
    # assert result == "hello world test"
    def test_content_whitespace_stripped(self):
        result = build_embedding_input("  hello world  ", tags=["test"])
        assert result == "hello world test"

    # --- Test: tags with whitespace are stripped ---
    # result = build_embedding_input("hello", tags=["  python  ", " memory "])
    # assert result == "hello python memory"
    def test_tags_whitespace_stripped(self):
        result = build_embedding_input("hello", tags=["  python  ", " memory "])
        assert result == "hello python memory"

    # --- Test: empty string tags are filtered out ---
    # result = build_embedding_input("hello", tags=["python", "", "  ", "memory"])
    # assert result == "hello python memory"
    def test_empty_string_tags_filtered(self):
        result = build_embedding_input("hello", tags=["python", "", "  ", "memory"])
        assert result == "hello python memory"

    # --- Test: all-empty tags treated as no tags ---
    # result = build_embedding_input("hello", tags=["", "  "])
    # assert result == "hello"
    def test_all_empty_tags_treated_as_no_tags(self):
        result = build_embedding_input("hello", tags=["", "  "])
        assert result == "hello"
