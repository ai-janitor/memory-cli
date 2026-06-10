# =============================================================================
# Module: test_final_score_ranking.py
# Purpose: Test final score computation and ranking — stage 8 of the light
#   search pipeline. Verifies the rescaled match-dominant formula (MEM-FIX-0006
#   / backlog #71): match quality (normalized RRF / activation) is the dominant
#   base; affinity / salience / temporal are bounded modifiers around 1.0.
# Rationale: The OLD formula added a rank-ceilinged rrf_score (<=0.033) to a
#   0..1 tag_affinity_score then multiplied by an unbounded salience_weight, so
#   match quality contributed <=4% and old, frequently-accessed, loosely-tagged
#   neurons permanently buried perfect matches. The new formula normalizes the
#   match signal into a 0..1 dominant base and bounds the modifiers, so a top
#   match outranks a mediocre match regardless of modifiers.
# Responsibility:
#   - Test direct_match formula: (rrf/RRF_MAX) * temporal * affinity_mod * salience_mod
#   - Test fan_out formula:      activation     * temporal * affinity_mod * salience_mod
#   - Test tag_affinity formula: capped affinity base * temporal * salience_mod
#   - Test the DOMINANCE INVARIANT (top-rrf + weak modifiers beats mid-rrf + maxed)
#   - Test salience clamp (unbounded upstream -> bounded modifier here)
#   - Test tag_affinity-only pool cannot beat a strong direct match
#   - Test sort order, tiebreaking, and missing-value defaults
# Organization:
#   1. Imports and test data helpers
#   2. Direct match scoring tests
#   3. Fan-out scoring tests
#   4. Tag-affinity pool tests
#   5. Dominance invariant + salience clamp tests
#   6. Sort order and tiebreaking tests
#   7. Missing value default tests
# =============================================================================

from __future__ import annotations

import pytest

from memory_cli.search.final_score_combine_and_rank import (
    compute_final_scores,
    _score_direct_match,
    _score_fan_out,
    _score_tag_affinity,
    RRF_MAX,
    AFFINITY_GAIN,
    SALIENCE_GAIN,
    SALIENCE_CAP,
    TAG_AFFINITY_BASE_CAP,
)


# -----------------------------------------------------------------------------
# Test data helpers
# -----------------------------------------------------------------------------

def _make_direct_candidate(neuron_id, rrf_score, temporal_weight,
                           tag_affinity_score=0.0, salience_weight=1.0):
    """Create a direct_match candidate dict."""
    return {
        "neuron_id": neuron_id,
        "match_type": "direct_match",
        "rrf_score": rrf_score,
        "temporal_weight": temporal_weight,
        "tag_affinity_score": tag_affinity_score,
        "salience_weight": salience_weight,
    }


def _make_fanout_candidate(neuron_id, activation_score, temporal_weight,
                           tag_affinity_score=0.0, salience_weight=1.0):
    """Create a fan_out candidate dict."""
    return {
        "neuron_id": neuron_id,
        "match_type": "fan_out",
        "activation_score": activation_score,
        "temporal_weight": temporal_weight,
        "tag_affinity_score": tag_affinity_score,
        "salience_weight": salience_weight,
    }


def _make_tag_affinity_candidate(neuron_id, tag_affinity_score, temporal_weight=1.0,
                                 salience_weight=1.0):
    """Create a tag_affinity-only candidate dict."""
    return {
        "neuron_id": neuron_id,
        "match_type": "tag_affinity",
        "tag_affinity_score": tag_affinity_score,
        "temporal_weight": temporal_weight,
        "salience_weight": salience_weight,
    }


# -----------------------------------------------------------------------------
# Direct match scoring tests
# -----------------------------------------------------------------------------

class TestDirectMatchScoring:
    """Test final score computation for direct_match candidates."""

    def test_normalized_rrf_times_temporal(self):
        """Verify base = rrf/RRF_MAX, then * temporal with neutral modifiers.

        rrf_score=0.016, temporal=0.8, no affinity/salience ->
        (0.016/RRF_MAX) * 0.8.
        """
        c = _make_direct_candidate(1, 0.016, 0.8)
        score = _score_direct_match(c)
        expected = (0.016 / RRF_MAX) * 0.8
        assert abs(score - expected) < 1e-10

    def test_perfect_rrf_full_temporal_is_one(self):
        """Verify a perfect dual-list match (rrf=RRF_MAX) with neutral
        modifiers scores exactly 1.0 — the normalized base ceiling."""
        c = _make_direct_candidate(1, RRF_MAX, 1.0)
        score = _score_direct_match(c)
        assert abs(score - 1.0) < 1e-10

    def test_zero_rrf_score(self):
        """Verify rrf_score=0.0 produces final_score=0.0 regardless of modifiers."""
        c = _make_direct_candidate(1, 0.0, 0.9, tag_affinity_score=1.0,
                                   salience_weight=5.0)
        score = _score_direct_match(c)
        assert score == 0.0

    def test_affinity_and_salience_are_bounded_modifiers(self):
        """Verify affinity + salience multiply the base by their bounded mods."""
        c = _make_direct_candidate(1, RRF_MAX, 1.0, tag_affinity_score=1.0,
                                   salience_weight=2.0)
        score = _score_direct_match(c)
        affinity_mod = 1.0 + AFFINITY_GAIN * 1.0
        salience_mod = 1.0 + SALIENCE_GAIN * min(2.0 - 1.0, SALIENCE_CAP)
        expected = 1.0 * 1.0 * affinity_mod * salience_mod
        assert abs(score - expected) < 1e-10


# -----------------------------------------------------------------------------
# Fan-out scoring tests
# -----------------------------------------------------------------------------

class TestFanOutScoring:
    """Test final score computation for fan_out candidates."""

    def test_activation_times_temporal(self):
        """Verify base = activation, then * temporal with neutral modifiers.

        activation=0.4, temporal=0.8 -> 0.32.
        """
        c = _make_fanout_candidate(1, 0.4, 0.8)
        score = _score_fan_out(c)
        assert abs(score - 0.32) < 1e-10

    def test_full_activation_and_temporal(self):
        """Verify activation=1.0, temporal=1.0, neutral mods -> 1.0."""
        c = _make_fanout_candidate(1, 1.0, 1.0)
        score = _score_fan_out(c)
        assert abs(score - 1.0) < 1e-10

    def test_zero_activation_score(self):
        """Verify activation_score=0.0 produces final_score=0.0."""
        c = _make_fanout_candidate(1, 0.0, 0.9, salience_weight=10.0)
        score = _score_fan_out(c)
        assert score == 0.0


# -----------------------------------------------------------------------------
# Tag-affinity pool tests
# -----------------------------------------------------------------------------

class TestTagAffinityPool:
    """Test final score computation for tag_affinity-only candidates."""

    def test_capped_affinity_base(self):
        """Verify base = min(affinity,1.0) * TAG_AFFINITY_BASE_CAP, * temporal."""
        c = _make_tag_affinity_candidate(1, 0.8, temporal_weight=1.0)
        score = _score_tag_affinity(c)
        expected = 0.8 * TAG_AFFINITY_BASE_CAP
        assert abs(score - expected) < 1e-10

    def test_affinity_pool_cannot_beat_strong_direct_match(self):
        """Maxed tag-affinity-only neighbor must not outrank a strong direct match.

        Affinity=1.0, maxed salience, full temporal vs a strong direct match
        (rrf=RRF_MAX) with WEAK modifiers — the direct match must win.
        """
        affinity = _make_tag_affinity_candidate(
            2, tag_affinity_score=1.0, temporal_weight=1.0, salience_weight=100.0
        )
        direct = _make_direct_candidate(1, RRF_MAX, 1.0)  # no affinity, no salience
        result = compute_final_scores([affinity, direct])
        assert result[0]["neuron_id"] == 1  # strong direct match wins


# -----------------------------------------------------------------------------
# Dominance invariant + salience clamp tests
# -----------------------------------------------------------------------------

class TestDominanceInvariant:
    """The core MEM-FIX-0006 guarantee: match quality dominates modifiers."""

    def test_top_rrf_weak_modifiers_beats_mid_rrf_maxed_modifiers(self):
        """Top-of-RRF direct match with weak modifiers must outrank a mid-RRF
        direct match with MAXED affinity + salience — the exact bug from #71
        (GLOBAL-686 perfect match buried under access-count salience)."""
        # Perfect match, no affinity, no salience boost.
        top = _make_direct_candidate(686, RRF_MAX, 0.9998)
        # Mediocre match (rank ~20 -> small rrf), but maxed modifiers.
        mid = _make_direct_candidate(
            42, 1.0 / (60 + 20 + 1), 1.0,
            tag_affinity_score=1.0, salience_weight=50.0,
        )
        result = compute_final_scores([mid, top])
        assert result[0]["neuron_id"] == 686

    def test_salience_clamp_bounds_unbounded_upstream(self):
        """Salience is unbounded upstream; the modifier must clamp its excess.

        A salience_weight of 1000 yields the SAME modifier as one of
        (1 + SALIENCE_CAP), because the excess is clamped to SALIENCE_CAP.
        """
        huge = _make_direct_candidate(1, RRF_MAX, 1.0, salience_weight=1000.0)
        capped = _make_direct_candidate(2, RRF_MAX, 1.0,
                                        salience_weight=1.0 + SALIENCE_CAP)
        assert abs(_score_direct_match(huge) - _score_direct_match(capped)) < 1e-10


# -----------------------------------------------------------------------------
# Sort order and tiebreaking tests
# -----------------------------------------------------------------------------

class TestFinalScoreSortOrder:
    """Test that results are sorted correctly."""

    def test_sorted_descending_by_score(self):
        """Verify candidates sorted by final_score descending."""
        candidates = [
            _make_direct_candidate(1, 0.01, 1.0),
            _make_direct_candidate(2, 0.03, 1.0),
            _make_direct_candidate(3, 0.005, 1.0),
        ]
        result = compute_final_scores(candidates)
        scores = [r["final_score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_tiebreak_by_neuron_id_ascending(self):
        """Verify equal scores tiebreak by neuron_id ascending."""
        candidates = [
            _make_direct_candidate(5, 0.1, 1.0),
            _make_direct_candidate(2, 0.1, 1.0),
        ]
        result = compute_final_scores(candidates)
        assert result[0]["neuron_id"] == 2
        assert result[1]["neuron_id"] == 5

    def test_mixed_direct_and_fanout_sorted_together(self):
        """Verify direct_match and fan_out candidates interleave by final_score.

        A fan_out with activation 0.5 (base 0.5) outranks a direct_match with a
        tiny rrf (base far below 0.5).
        """
        candidates = [
            _make_direct_candidate(1, 0.005, 1.0),   # base ~0.15
            _make_fanout_candidate(2, 0.5, 1.0),     # base 0.5
            _make_direct_candidate(3, 0.008, 1.0),   # base ~0.24
        ]
        result = compute_final_scores(candidates)
        assert result[0]["neuron_id"] == 2

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
        """Verify missing temporal_weight defaults to 1.0 (no decay penalty).

        rrf=RRF_MAX, all other modifiers missing -> base 1.0 passes through.
        """
        c = {"neuron_id": 1, "match_type": "direct_match", "rrf_score": RRF_MAX}
        score = _score_direct_match(c)
        assert abs(score - 1.0) < 1e-10

    def test_missing_salience_and_affinity_default_to_neutral(self):
        """Verify missing salience_weight/tag_affinity_score -> neutral mods."""
        c = {"neuron_id": 1, "match_type": "direct_match",
             "rrf_score": RRF_MAX, "temporal_weight": 1.0}
        score = _score_direct_match(c)
        assert abs(score - 1.0) < 1e-10

    def test_missing_match_type_defaults_to_direct(self):
        """Verify missing match_type defaults to 'direct_match'."""
        candidates = [
            {"neuron_id": 1, "rrf_score": RRF_MAX, "temporal_weight": 1.0}
        ]
        result = compute_final_scores(candidates)
        assert abs(result[0]["final_score"] - 1.0) < 1e-10
