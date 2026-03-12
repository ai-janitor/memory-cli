# =============================================================================
# Module: test_heavy_search_merge.py
# Purpose: Test the merge and pagination module — deduplication logic,
#   primary/secondary ordering, pagination edge cases, and envelope format.
# Rationale: Merge is the final assembly step and must be deterministic.
#   The dedup-by-ID logic and pagination math are easy to get wrong at
#   boundaries (empty lists, offset beyond total, overlapping IDs).
#   Thorough unit tests prevent subtle bugs in result ordering.
# Responsibility:
#   - Test deduplication: secondary items with IDs in primary are dropped
#   - Test ordering: primary items first, then unique secondary items
#   - Test pagination: offset and limit applied correctly
#   - Test edge cases: empty primary, empty secondary, both empty
#   - Test edge cases: offset beyond total, limit=0
#   - Test edge cases: overlapping IDs between primary and secondary
#   - Test edge cases: duplicate IDs within secondary list
#   - Test inflated limit calculation used by orchestrator
#   - Test result envelope has correct schema
# Organization:
#   1. Imports and fixtures
#   2. Deduplication tests
#   3. Ordering tests
#   4. Pagination tests
#   5. Edge case tests
#   6. Envelope schema tests
# =============================================================================

from __future__ import annotations

import pytest
from typing import Any, Dict, List

from memory_cli.search.heavy.heavy_search_merge_and_paginate import (
    _apply_pagination,
    _build_result_envelope,
    _deduplicate_by_neuron_id,
    merge_and_paginate,
)


# -----------------------------------------------------------------------------
# Fixtures / helpers
# -----------------------------------------------------------------------------

def _make_result(neuron_id: int, content: str = "", score: float = 0.0) -> Dict[str, Any]:
    """Create a minimal neuron result dict for testing.

    Args:
        neuron_id: The neuron ID.
        content: Optional content string.
        score: Optional relevance score.

    Returns:
        Dict with id, content, score keys.
    """
    return {"id": neuron_id, "content": content, "score": score}


# -----------------------------------------------------------------------------
# Deduplication tests
# -----------------------------------------------------------------------------

class TestMergeDeduplication:
    """Test that duplicate neuron IDs are removed correctly."""

    def test_no_overlap_keeps_all(self):
        """When primary and secondary have no common IDs, all are kept.

        Primary: [1, 2], Secondary: [3, 4] -> [1, 2, 3, 4]
        """
        primary = [_make_result(1), _make_result(2)]
        secondary = [_make_result(3), _make_result(4)]
        result = _deduplicate_by_neuron_id(primary, secondary)
        assert [r["id"] for r in result] == [1, 2, 3, 4]

    def test_full_overlap_keeps_primary_only(self):
        """When all secondary IDs are in primary, secondary is entirely dropped.

        Primary: [1, 2, 3], Secondary: [2, 3] -> [1, 2, 3]
        """
        primary = [_make_result(1), _make_result(2), _make_result(3)]
        secondary = [_make_result(2), _make_result(3)]
        result = _deduplicate_by_neuron_id(primary, secondary)
        assert [r["id"] for r in result] == [1, 2, 3]

    def test_partial_overlap_keeps_unique_secondary(self):
        """When some secondary IDs overlap, only unique secondary items added.

        Primary: [1, 2, 3], Secondary: [2, 4, 3, 5] -> [1, 2, 3, 4, 5]
        """
        primary = [_make_result(1), _make_result(2), _make_result(3)]
        secondary = [_make_result(2), _make_result(4), _make_result(3), _make_result(5)]
        result = _deduplicate_by_neuron_id(primary, secondary)
        assert [r["id"] for r in result] == [1, 2, 3, 4, 5]

    def test_duplicate_within_secondary_keeps_first(self):
        """When secondary has duplicate IDs, first occurrence wins.

        Primary: [1], Secondary: [2, 3, 2, 4, 3] -> [1, 2, 3, 4]
        """
        primary = [_make_result(1)]
        secondary = [_make_result(2), _make_result(3), _make_result(2), _make_result(4), _make_result(3)]
        result = _deduplicate_by_neuron_id(primary, secondary)
        assert [r["id"] for r in result] == [1, 2, 3, 4]

    def test_empty_primary_uses_secondary(self):
        """When primary is empty, result is just secondary (deduplicated).

        Primary: [], Secondary: [1, 2, 3] -> [1, 2, 3]
        """
        primary: List[Dict[str, Any]] = []
        secondary = [_make_result(1), _make_result(2), _make_result(3)]
        result = _deduplicate_by_neuron_id(primary, secondary)
        assert [r["id"] for r in result] == [1, 2, 3]

    def test_empty_secondary_uses_primary(self):
        """When secondary is empty, result is just primary.

        Primary: [1, 2, 3], Secondary: [] -> [1, 2, 3]
        """
        primary = [_make_result(1), _make_result(2), _make_result(3)]
        secondary: List[Dict[str, Any]] = []
        result = _deduplicate_by_neuron_id(primary, secondary)
        assert [r["id"] for r in result] == [1, 2, 3]

    def test_both_empty(self):
        """When both are empty, result is empty.

        Primary: [], Secondary: [] -> []
        """
        result = _deduplicate_by_neuron_id([], [])
        assert result == []


# -----------------------------------------------------------------------------
# Ordering tests
# -----------------------------------------------------------------------------

class TestMergeOrdering:
    """Test that merge preserves correct ordering."""

    def test_primary_items_come_first(self):
        """Primary items always precede secondary items in output.

        Primary: [10, 20], Secondary: [5, 15] -> [10, 20, 5, 15]
        Secondary items are appended AFTER all primary items.
        """
        primary = [_make_result(10), _make_result(20)]
        secondary = [_make_result(5), _make_result(15)]
        result = _deduplicate_by_neuron_id(primary, secondary)
        ids = [r["id"] for r in result]
        assert ids == [10, 20, 5, 15]

    def test_primary_order_preserved(self):
        """Order within primary list is preserved (Haiku's ranking).

        Primary: [30, 10, 20] -> first three results are [30, 10, 20]
        """
        primary = [_make_result(30), _make_result(10), _make_result(20)]
        secondary: List[Dict[str, Any]] = []
        result = _deduplicate_by_neuron_id(primary, secondary)
        ids = [r["id"] for r in result]
        assert ids == [30, 10, 20]

    def test_secondary_order_preserved(self):
        """Order within unique secondary items is preserved.

        Secondary arrives in search-result order; that order is maintained.
        """
        primary = [_make_result(1)]
        secondary = [_make_result(4), _make_result(2), _make_result(3)]
        result = _deduplicate_by_neuron_id(primary, secondary)
        ids = [r["id"] for r in result]
        assert ids == [1, 4, 2, 3]


# -----------------------------------------------------------------------------
# Pagination tests
# -----------------------------------------------------------------------------

class TestMergePagination:
    """Test offset and limit application."""

    def test_first_page(self):
        """offset=0, limit=3 on 10 results -> first 3 items."""
        items = [_make_result(i) for i in range(10)]
        result = _apply_pagination(items, limit=3, offset=0)
        assert len(result) == 3
        assert [r["id"] for r in result] == [0, 1, 2]

    def test_second_page(self):
        """offset=3, limit=3 on 10 results -> items 3-5."""
        items = [_make_result(i) for i in range(10)]
        result = _apply_pagination(items, limit=3, offset=3)
        assert len(result) == 3
        assert [r["id"] for r in result] == [3, 4, 5]

    def test_last_page_partial(self):
        """offset=8, limit=3 on 10 results -> last 2 items (partial page)."""
        items = [_make_result(i) for i in range(10)]
        result = _apply_pagination(items, limit=3, offset=8)
        assert len(result) == 2
        assert [r["id"] for r in result] == [8, 9]

    def test_offset_beyond_total(self):
        """offset=20, limit=5 on 10 results -> empty list."""
        items = [_make_result(i) for i in range(10)]
        result = _apply_pagination(items, limit=5, offset=20)
        assert result == []

    def test_limit_larger_than_total(self):
        """offset=0, limit=100 on 10 results -> all 10 items."""
        items = [_make_result(i) for i in range(10)]
        result = _apply_pagination(items, limit=100, offset=0)
        assert len(result) == 10

    def test_zero_limit(self):
        """limit=0 -> empty list (defensive, shouldn't happen in practice)."""
        items = [_make_result(i) for i in range(10)]
        result = _apply_pagination(items, limit=0, offset=0)
        assert result == []

    def test_pagination_does_not_affect_total(self):
        """Total in envelope should reflect pre-pagination count.

        10 results, limit=3, offset=0 -> total=10, results has 3 items.
        """
        primary = [_make_result(i) for i in range(10)]
        envelope = merge_and_paginate("query", primary, [], limit=3, offset=0)
        assert envelope["total"] == 10
        assert len(envelope["results"]) == 3


# -----------------------------------------------------------------------------
# Edge case tests
# -----------------------------------------------------------------------------

class TestMergeEdgeCases:
    """Test unusual but valid inputs."""

    def test_single_result_in_primary(self):
        """One result in primary, empty secondary -> one result."""
        primary = [_make_result(42)]
        envelope = merge_and_paginate("q", primary, [], limit=10, offset=0)
        assert len(envelope["results"]) == 1
        assert envelope["results"][0]["id"] == 42

    def test_single_result_in_secondary(self):
        """Empty primary, one result in secondary -> one result."""
        secondary = [_make_result(99)]
        envelope = merge_and_paginate("q", [], secondary, limit=10, offset=0)
        assert len(envelope["results"]) == 1
        assert envelope["results"][0]["id"] == 99

    def test_large_result_sets(self):
        """Verify merge handles 100+ items without issues.

        No assertion on performance — just correctness.
        """
        primary = [_make_result(i) for i in range(100)]
        secondary = [_make_result(i + 100) for i in range(100)]
        envelope = merge_and_paginate("q", primary, secondary, limit=50, offset=0)
        assert envelope["total"] == 200
        assert len(envelope["results"]) == 50


# -----------------------------------------------------------------------------
# Envelope schema tests
# -----------------------------------------------------------------------------

class TestResultEnvelope:
    """Test the output envelope structure."""

    def _make_envelope(self):
        return merge_and_paginate("test query", [_make_result(1)], [], limit=10, offset=0)

    def test_envelope_has_query(self):
        """Envelope must include original query string."""
        env = self._make_envelope()
        assert "query" in env
        assert env["query"] == "test query"

    def test_envelope_has_results(self):
        """Envelope must include results list."""
        env = self._make_envelope()
        assert "results" in env
        assert isinstance(env["results"], list)

    def test_envelope_has_total(self):
        """Envelope must include total count (pre-pagination)."""
        env = self._make_envelope()
        assert "total" in env
        assert isinstance(env["total"], int)

    def test_envelope_has_limit(self):
        """Envelope must include requested limit."""
        env = self._make_envelope()
        assert "limit" in env
        assert env["limit"] == 10

    def test_envelope_has_offset(self):
        """Envelope must include requested offset."""
        env = self._make_envelope()
        assert "offset" in env
        assert env["offset"] == 0

    def test_envelope_no_extra_keys(self):
        """Envelope should have exactly 5 keys — no heavy search indicators.

        Output schema must be identical to light search. No "mode" or "method" key.
        """
        env = self._make_envelope()
        assert set(env.keys()) == {"query", "results", "total", "limit", "offset"}
