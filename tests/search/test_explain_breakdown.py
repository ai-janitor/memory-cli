# =============================================================================
# Module: test_explain_breakdown.py
# Purpose: Test --explain score breakdown builder. Verifies all breakdown
#   fields are present, correct values are extracted, and vector_unavailable
#   flag is properly set.
# Rationale: The explain breakdown is the primary debugging tool for search
#   scoring. Every field must be present and correctly populated. The
#   vector_unavailable flag must accurately reflect BM25-only fallback state.
# Responsibility:
#   - Test all breakdown fields are present in output
#   - Test field values match candidate dict values
#   - Test vector_unavailable flag propagation
#   - Test direct_match vs fan_out breakdown differences
#   - Test None values for missing metadata (e.g., no vector match)
# Organization:
#   1. Imports and test data helpers
#   2. Field presence tests
#   3. Field value tests
#   4. Vector unavailable flag tests
#   5. Match type specific tests
# =============================================================================

from __future__ import annotations

import pytest

from memory_cli.search.explain_scoring_breakdown import (
    build_explain_breakdowns,
    _build_single_breakdown,
)


# -----------------------------------------------------------------------------
# Test data helpers
# -----------------------------------------------------------------------------

def _make_full_candidate():
    """Create a candidate dict with all scoring fields populated."""
    return {
        "neuron_id": 1,
        "bm25_raw": -2.5,
        "bm25_normalized": 0.714,
        "bm25_rank": 0,
        "vector_distance": 0.35,
        "vector_rank": 2,
        "rrf_score": 0.0328,
        "activation_score": 1.0,
        "hop_distance": 0,
        "temporal_weight": 0.95,
        "final_score": 0.0312,
        "match_type": "direct_match",
        "match_source": "both",
    }


def _make_bm25_only_candidate():
    """Create a candidate with only BM25 scores (no vector)."""
    return {
        "neuron_id": 2,
        "bm25_raw": -1.0,
        "bm25_normalized": 0.5,
        "bm25_rank": 1,
        "vector_distance": None,
        "vector_rank": None,
        "rrf_score": 0.016,
        "activation_score": 1.0,
        "hop_distance": 0,
        "temporal_weight": 0.8,
        "final_score": 0.0128,
        "match_type": "direct_match",
        "match_source": "bm25_only",
    }


def _make_fan_out_candidate():
    """Create a fan-out candidate with activation but no direct match."""
    return {
        "neuron_id": 3,
        "rrf_score": 0.0,
        "activation_score": 0.4,
        "hop_distance": 1,
        "temporal_weight": 0.9,
        "final_score": 0.36,
        "match_type": "fan_out",
        "edge_reason": "related_concept",
    }


# -----------------------------------------------------------------------------
# Field presence tests
# -----------------------------------------------------------------------------

EXPECTED_FIELDS = {
    "bm25_raw", "bm25_normalized", "bm25_rank",
    "vector_distance", "vector_rank",
    "rrf_score", "activation_score", "hop_distance",
    "tag_affinity_score", "tag_affinity_depth",
    "temporal_weight", "final_score",
    "vector_unavailable", "match_type", "match_source",
}


class TestExplainFieldPresence:
    """Test that all required fields are present in breakdown."""

    def test_all_explain_fields_present(self):
        """Verify score_breakdown contains all spec'd fields:
        bm25_raw, bm25_normalized, bm25_rank,
        vector_distance, vector_rank,
        rrf_score, activation_score, hop_distance,
        temporal_weight, final_score,
        vector_unavailable, match_type, match_source.
        """
        candidate = _make_full_candidate()
        breakdown = _build_single_breakdown(candidate, False)
        assert set(breakdown.keys()) == EXPECTED_FIELDS

    def test_breakdown_attached_to_candidate(self):
        """Verify build_explain_breakdowns() attaches score_breakdown key."""
        candidates = [_make_full_candidate()]
        result = build_explain_breakdowns(candidates, vector_unavailable=False)
        assert "score_breakdown" in result[0]

    def test_batch_processes_all_candidates(self):
        """Verify all candidates in list get breakdowns, not just first."""
        candidates = [
            _make_full_candidate(),
            _make_bm25_only_candidate(),
            _make_fan_out_candidate(),
        ]
        result = build_explain_breakdowns(candidates, vector_unavailable=False)
        for c in result:
            assert "score_breakdown" in c


# -----------------------------------------------------------------------------
# Field value tests
# -----------------------------------------------------------------------------

class TestExplainFieldValues:
    """Test that breakdown field values match candidate data."""

    def test_bm25_fields_match_candidate(self):
        """Verify bm25_raw, bm25_normalized, bm25_rank match candidate values."""
        candidate = _make_full_candidate()
        breakdown = _build_single_breakdown(candidate, False)
        assert breakdown["bm25_raw"] == -2.5
        assert breakdown["bm25_normalized"] == 0.714
        assert breakdown["bm25_rank"] == 0

    def test_vector_fields_match_candidate(self):
        """Verify vector_distance, vector_rank match candidate values."""
        candidate = _make_full_candidate()
        breakdown = _build_single_breakdown(candidate, False)
        assert breakdown["vector_distance"] == 0.35
        assert breakdown["vector_rank"] == 2

    def test_rrf_score_matches(self):
        """Verify rrf_score matches candidate's rrf_score."""
        candidate = _make_full_candidate()
        breakdown = _build_single_breakdown(candidate, False)
        assert breakdown["rrf_score"] == 0.0328

    def test_activation_score_matches(self):
        """Verify activation_score matches candidate's activation_score."""
        candidate = _make_full_candidate()
        breakdown = _build_single_breakdown(candidate, False)
        assert breakdown["activation_score"] == 1.0

    def test_temporal_weight_matches(self):
        """Verify temporal_weight matches candidate's temporal_weight."""
        candidate = _make_full_candidate()
        breakdown = _build_single_breakdown(candidate, False)
        assert breakdown["temporal_weight"] == 0.95

    def test_final_score_matches(self):
        """Verify final_score matches candidate's final_score."""
        candidate = _make_full_candidate()
        breakdown = _build_single_breakdown(candidate, False)
        assert breakdown["final_score"] == 0.0312


# -----------------------------------------------------------------------------
# Vector unavailable flag tests
# -----------------------------------------------------------------------------

class TestExplainVectorUnavailable:
    """Test vector_unavailable flag in breakdown."""

    def test_vector_available_flag_false(self):
        """Verify vector_unavailable=False when vectors were available."""
        candidate = _make_full_candidate()
        breakdown = _build_single_breakdown(candidate, vector_unavailable=False)
        assert breakdown["vector_unavailable"] is False

    def test_vector_unavailable_flag_true(self):
        """Verify vector_unavailable=True when BM25-only fallback used."""
        candidate = _make_bm25_only_candidate()
        breakdown = _build_single_breakdown(candidate, vector_unavailable=True)
        assert breakdown["vector_unavailable"] is True

    def test_flag_consistent_across_all_breakdowns(self):
        """Verify all breakdowns in a batch share the same vector_unavailable value."""
        candidates = [
            _make_full_candidate(),
            _make_bm25_only_candidate(),
        ]
        result = build_explain_breakdowns(candidates, vector_unavailable=True)
        for c in result:
            assert c["score_breakdown"]["vector_unavailable"] is True


# -----------------------------------------------------------------------------
# Match type specific tests
# -----------------------------------------------------------------------------

class TestExplainMatchTypeSpecific:
    """Test breakdown differences between direct_match and fan_out."""

    def test_direct_match_has_match_source(self):
        """Verify direct_match breakdown includes match_source field."""
        candidate = _make_full_candidate()
        breakdown = _build_single_breakdown(candidate, False)
        assert breakdown["match_source"] == "both"

    def test_fan_out_match_source_is_none(self):
        """Verify fan_out breakdown has match_source=None (not a direct match)."""
        candidate = _make_fan_out_candidate()
        breakdown = _build_single_breakdown(candidate, False)
        assert breakdown["match_source"] is None

    def test_fan_out_bm25_fields_are_none(self):
        """Verify fan_out breakdown has bm25_raw=None, bm25_rank=None."""
        candidate = _make_fan_out_candidate()
        breakdown = _build_single_breakdown(candidate, False)
        assert breakdown["bm25_raw"] is None
        assert breakdown["bm25_rank"] is None

    def test_fan_out_vector_fields_are_none(self):
        """Verify fan_out breakdown has vector_distance=None, vector_rank=None."""
        candidate = _make_fan_out_candidate()
        breakdown = _build_single_breakdown(candidate, False)
        assert breakdown["vector_distance"] is None
        assert breakdown["vector_rank"] is None
