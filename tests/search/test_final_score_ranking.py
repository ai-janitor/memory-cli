# =============================================================================
# Module: test_final_score_ranking.py
# Purpose: Test final score computation and ranking — stage 8 of the light
#   search pipeline. Verifies score combination formulas for direct matches
#   vs fan-out, sort order, and tiebreaking.
# Rationale: The final score is what determines result ranking — the one
#   number the user sees. The formulas (rrf_score * temporal_weight for
#   direct, activation_score * temporal_weight for fan-out) must be exact.
#   Tiebreaking by neuron_id ensures deterministic ordering.
# Responsibility:
#   - Test direct_match formula: rrf_score * temporal_weight
#   - Test fan_out formula: activation_score * temporal_weight
#   - Test sort order: descending by final_score
#   - Test tiebreaking: ascending by neuron_id when scores equal
#   - Test missing score defaults (0.0 for scores, 1.0 for weights)
#   - Test mixed direct_match + fan_out candidates sort together
# Organization:
#   1. Imports and test data helpers
#   2. Direct match scoring tests
#   3. Fan-out scoring tests
#   4. Sort order and tiebreaking tests
#   5. Missing value default tests
# =============================================================================

from __future__ import annotations

import pytest

from memory_cli.search.final_score_combine_and_rank import (
    compute_final_scores,
    _score_direct_match,
    _score_fan_out,
)


# -----------------------------------------------------------------------------
# Test data helpers
# -----------------------------------------------------------------------------

def _make_direct_candidate(neuron_id, rrf_score, temporal_weight):
    """Create a direct_match candidate dict."""
    return {
        "neuron_id": neuron_id,
        "match_type": "direct_match",
        "rrf_score": rrf_score,
        "temporal_weight": temporal_weight,
    }


def _make_fanout_candidate(neuron_id, activation_score, temporal_weight):
    """Create a fan_out candidate dict."""
    return {
        "neuron_id": neuron_id,
        "match_type": "fan_out",
        "activation_score": activation_score,
        "temporal_weight": temporal_weight,
    }


# -----------------------------------------------------------------------------
# Direct match scoring tests
# -----------------------------------------------------------------------------

class TestDirectMatchScoring:
    """Test final score computation for direct_match candidates."""

    def test_rrf_times_temporal(self):
        """Verify final_score = rrf_score * temporal_weight.

        rrf_score=0.016, temporal_weight=0.8 → final_score=0.0128
        """
        c = _make_direct_candidate(1, 0.016, 0.8)
        score = _score_direct_match(c)
        assert abs(score - 0.0128) < 1e-10

    def test_full_temporal_weight(self):
        """Verify temporal_weight=1.0 passes rrf_score through unchanged.

        rrf_score=0.016, temporal_weight=1.0 → final_score=0.016
        """
        c = _make_direct_candidate(1, 0.016, 1.0)
        score = _score_direct_match(c)
        assert abs(score - 0.016) < 1e-10

    def test_zero_rrf_score(self):
        """Verify rrf_score=0.0 produces final_score=0.0 regardless of weight."""
        c = _make_direct_candidate(1, 0.0, 0.9)
        score = _score_direct_match(c)
        assert score == 0.0


# -----------------------------------------------------------------------------
# Fan-out scoring tests
# -----------------------------------------------------------------------------

class TestFanOutScoring:
    """Test final score computation for fan_out candidates."""

    def test_activation_times_temporal(self):
        """Verify final_score = activation_score * temporal_weight.

        activation_score=0.4, temporal_weight=0.8 → final_score=0.32
        """
        c = _make_fanout_candidate(1, 0.4, 0.8)
        score = _score_fan_out(c)
        assert abs(score - 0.32) < 1e-10

    def test_full_activation_and_temporal(self):
        """Verify activation=1.0, temporal=1.0 → final_score=1.0."""
        c = _make_fanout_candidate(1, 1.0, 1.0)
        score = _score_fan_out(c)
        assert abs(score - 1.0) < 1e-10

    def test_zero_activation_score(self):
        """Verify activation_score=0.0 produces final_score=0.0."""
        c = _make_fanout_candidate(1, 0.0, 0.9)
        score = _score_fan_out(c)
        assert score == 0.0


# -----------------------------------------------------------------------------
# Sort order and tiebreaking tests
# -----------------------------------------------------------------------------

class TestFinalScoreSortOrder:
    """Test that results are sorted correctly."""

    def test_sorted_descending_by_score(self):
        """Verify candidates sorted by final_score descending.

        Higher score = better match = earlier in list.
        """
        candidates = [
            _make_direct_candidate(1, 0.01, 1.0),   # final=0.01
            _make_direct_candidate(2, 0.03, 1.0),   # final=0.03
            _make_direct_candidate(3, 0.005, 1.0),  # final=0.005
        ]
        result = compute_final_scores(candidates)
        scores = [r["final_score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_tiebreak_by_neuron_id_ascending(self):
        """Verify equal scores tiebreak by neuron_id ascending.

        neuron_id=5 with score=0.1 should come after neuron_id=2 with score=0.1.
        """
        candidates = [
            _make_direct_candidate(5, 0.1, 1.0),
            _make_direct_candidate(2, 0.1, 1.0),
        ]
        result = compute_final_scores(candidates)
        assert result[0]["neuron_id"] == 2
        assert result[1]["neuron_id"] == 5

    def test_mixed_direct_and_fanout_sorted_together(self):
        """Verify direct_match and fan_out candidates are interleaved
        based on final_score, not grouped by type.

        A fan_out with score 0.5 should rank above direct_match with score 0.01.
        """
        candidates = [
            _make_direct_candidate(1, 0.01, 1.0),   # final=0.01
            _make_fanout_candidate(2, 0.5, 1.0),     # final=0.5
            _make_direct_candidate(3, 0.02, 1.0),    # final=0.02
        ]
        result = compute_final_scores(candidates)
        # Fan-out neuron 2 (score 0.5) should be first
        assert result[0]["neuron_id"] == 2
        assert result[0]["final_score"] == 0.5

    def test_empty_candidates_returns_empty(self):
        """Verify empty candidate list returns empty list."""
        result = compute_final_scores([])
        assert result == []


# -----------------------------------------------------------------------------
# Missing value default tests
# -----------------------------------------------------------------------------

class TestFinalScoreDefaults:
    """Test default values for missing score components."""

    def test_missing_rrf_score_defaults_to_zero(self):
        """Verify missing rrf_score defaults to 0.0 in computation."""
        c = {"neuron_id": 1, "match_type": "direct_match", "temporal_weight": 0.8}
        score = _score_direct_match(c)
        assert score == 0.0

    def test_missing_activation_score_defaults_to_zero(self):
        """Verify missing activation_score defaults to 0.0."""
        c = {"neuron_id": 1, "match_type": "fan_out", "temporal_weight": 0.8}
        score = _score_fan_out(c)
        assert score == 0.0

    def test_missing_temporal_weight_defaults_to_one(self):
        """Verify missing temporal_weight defaults to 1.0 (no decay penalty)."""
        c = {"neuron_id": 1, "match_type": "direct_match", "rrf_score": 0.016}
        score = _score_direct_match(c)
        assert abs(score - 0.016) < 1e-10

    def test_missing_match_type_defaults_to_direct(self):
        """Verify missing match_type defaults to 'direct_match'."""
        candidates = [
            {"neuron_id": 1, "rrf_score": 0.016, "temporal_weight": 1.0}
        ]
        result = compute_final_scores(candidates)
        assert abs(result[0]["final_score"] - 0.016) < 1e-10
