# =============================================================================
# Module: test_rrf_fusion.py
# Purpose: Test Reciprocal Rank Fusion (RRF) — stage 4 of the light search
#   pipeline. Verifies the k=60 formula, overlap boost, single-list mode,
#   and empty list handling.
# Rationale: RRF is the bridge between two different retrieval signals. The
#   formula must be exact (1/(60+rank+1)), the overlap boost (candidates in
#   both lists get higher scores) must work correctly, and single-list mode
#   (BM25-only) must produce valid scores.
# Responsibility:
#   - Test RRF formula: 1/(k + rank + 1) with k=60
#   - Test overlap boost: candidates in both lists score higher
#   - Test single-list: BM25-only or vector-only produces valid results
#   - Test empty lists: both empty → empty, one empty → other list only
#   - Test match_source labeling: "both", "bm25_only", "vector_only"
#   - Test metadata preservation: BM25 and vector fields carried through
# Organization:
#   1. Imports and test data
#   2. RRF formula tests
#   3. Overlap boost tests
#   4. Single-list and empty-list tests
#   5. Metadata preservation tests
# =============================================================================

from __future__ import annotations

import pytest

from memory_cli.search.rrf_fusion_rank_based_k60 import fuse_rrf, _rrf_score_for_rank, RRF_K


# -----------------------------------------------------------------------------
# Test data helpers
# -----------------------------------------------------------------------------

def _make_bm25_candidate(neuron_id, rank, raw=-1.0, normalized=0.5):
    """Helper to create a BM25 candidate dict."""
    return {
        "neuron_id": neuron_id,
        "bm25_raw": raw,
        "bm25_normalized": normalized,
        "bm25_rank": rank,
    }


def _make_vector_candidate(neuron_id, rank, distance=0.5):
    """Helper to create a vector candidate dict."""
    return {
        "neuron_id": neuron_id,
        "vector_distance": distance,
        "vector_rank": rank,
    }


# -----------------------------------------------------------------------------
# RRF formula tests
# -----------------------------------------------------------------------------

class TestRRFFormula:
    """Test the RRF score computation formula."""

    def test_rank_zero_score(self):
        """Verify rank 0 score = 1/(60+0+1) = 1/61 ≈ 0.01639.

        This is the maximum possible single-list contribution.
        """
        score = _rrf_score_for_rank(0)
        assert abs(score - 1.0 / 61) < 1e-10

    def test_rank_one_score(self):
        """Verify rank 1 score = 1/(60+1+1) = 1/62 ≈ 0.01613."""
        score = _rrf_score_for_rank(1)
        assert abs(score - 1.0 / 62) < 1e-10

    def test_high_rank_score_approaches_zero(self):
        """Verify rank 99 score = 1/(60+99+1) = 1/160 = 0.00625.

        Score decreases monotonically with rank.
        """
        score = _rrf_score_for_rank(99)
        assert abs(score - 1.0 / 160) < 1e-10

    def test_scores_decrease_monotonically_with_rank(self):
        """Verify higher ranks produce lower RRF contributions."""
        scores = [_rrf_score_for_rank(r) for r in range(10)]
        for i in range(len(scores) - 1):
            assert scores[i] > scores[i + 1]


# -----------------------------------------------------------------------------
# Overlap boost tests
# -----------------------------------------------------------------------------

class TestRRFOverlapBoost:
    """Test that candidates appearing in both lists get boosted scores."""

    def test_overlap_candidate_scores_higher(self):
        """Verify a candidate in both BM25 and vector lists has higher
        RRF score than one in only one list.

        Candidate in both: 1/61 + 1/61 = 2/61 ≈ 0.03279
        Candidate in one: 1/61 ≈ 0.01639
        """
        bm25 = [_make_bm25_candidate(1, 0)]
        vector = [_make_vector_candidate(1, 0), _make_vector_candidate(2, 1)]
        results = fuse_rrf(bm25, vector)
        by_id = {r["neuron_id"]: r for r in results}
        # Neuron 1 appears in both lists, neuron 2 only in vector
        assert by_id[1]["rrf_score"] > by_id[2]["rrf_score"]

    def test_overlap_candidate_marked_both(self):
        """Verify match_source='both' for candidates in both lists."""
        bm25 = [_make_bm25_candidate(1, 0)]
        vector = [_make_vector_candidate(1, 0)]
        results = fuse_rrf(bm25, vector)
        assert results[0]["match_source"] == "both"

    def test_overlap_preserves_both_metadata(self):
        """Verify overlapping candidate has both BM25 and vector metadata.

        Assert: bm25_raw, bm25_normalized, bm25_rank are set.
        Assert: vector_distance, vector_rank are set.
        """
        bm25 = [_make_bm25_candidate(1, 0, raw=-2.5, normalized=0.714)]
        vector = [_make_vector_candidate(1, 0, distance=0.35)]
        results = fuse_rrf(bm25, vector)
        r = results[0]
        assert r["bm25_raw"] == -2.5
        assert r["bm25_normalized"] == 0.714
        assert r["bm25_rank"] == 0
        assert r["vector_distance"] == 0.35
        assert r["vector_rank"] == 0


# -----------------------------------------------------------------------------
# Single-list and empty-list tests
# -----------------------------------------------------------------------------

class TestRRFSingleListAndEmpty:
    """Test RRF with one or both lists empty."""

    def test_both_empty_returns_empty(self):
        """Verify empty BM25 + empty vector → empty fused list."""
        results = fuse_rrf([], [])
        assert results == []

    def test_bm25_only_returns_bm25_candidates(self):
        """Verify BM25 candidates + empty vector → BM25-only fused list.

        All candidates should have match_source='bm25_only'.
        """
        bm25 = [_make_bm25_candidate(1, 0), _make_bm25_candidate(2, 1)]
        results = fuse_rrf(bm25, [])
        assert len(results) == 2
        for r in results:
            assert r["match_source"] == "bm25_only"

    def test_vector_only_returns_vector_candidates(self):
        """Verify empty BM25 + vector candidates → vector-only fused list.

        All candidates should have match_source='vector_only'.
        """
        vector = [_make_vector_candidate(1, 0), _make_vector_candidate(2, 1)]
        results = fuse_rrf([], vector)
        assert len(results) == 2
        for r in results:
            assert r["match_source"] == "vector_only"

    def test_single_list_scores_are_valid(self):
        """Verify single-list candidates have valid RRF scores > 0."""
        bm25 = [_make_bm25_candidate(1, 0)]
        results = fuse_rrf(bm25, [])
        assert results[0]["rrf_score"] > 0


# -----------------------------------------------------------------------------
# Metadata preservation tests
# -----------------------------------------------------------------------------

class TestRRFMetadataPreservation:
    """Test that BM25 and vector metadata is preserved through fusion."""

    def test_bm25_metadata_preserved(self):
        """Verify bm25_raw, bm25_normalized, bm25_rank are preserved."""
        bm25 = [_make_bm25_candidate(5, 0, raw=-3.0, normalized=0.75)]
        results = fuse_rrf(bm25, [])
        r = results[0]
        assert r["bm25_raw"] == -3.0
        assert r["bm25_normalized"] == 0.75
        assert r["bm25_rank"] == 0

    def test_vector_metadata_preserved(self):
        """Verify vector_distance, vector_rank are preserved."""
        vector = [_make_vector_candidate(5, 0, distance=0.25)]
        results = fuse_rrf([], vector)
        r = results[0]
        assert r["vector_distance"] == 0.25
        assert r["vector_rank"] == 0

    def test_missing_metadata_is_none(self):
        """Verify metadata from missing list is None.

        BM25-only candidate: vector_distance=None, vector_rank=None.
        Vector-only candidate: bm25_raw=None, bm25_rank=None.
        """
        bm25 = [_make_bm25_candidate(1, 0)]
        vector = [_make_vector_candidate(2, 0)]
        results = fuse_rrf(bm25, vector)
        by_id = {r["neuron_id"]: r for r in results}
        # BM25-only neuron 1
        assert by_id[1]["vector_distance"] is None
        assert by_id[1]["vector_rank"] is None
        # Vector-only neuron 2
        assert by_id[2]["bm25_raw"] is None
        assert by_id[2]["bm25_rank"] is None

    def test_results_sorted_by_rrf_score_descending(self):
        """Verify fused results are sorted by rrf_score descending."""
        bm25 = [_make_bm25_candidate(1, 0), _make_bm25_candidate(2, 1)]
        vector = [_make_vector_candidate(1, 0)]  # neuron 1 in both = higher score
        results = fuse_rrf(bm25, vector)
        for i in range(len(results) - 1):
            assert results[i]["rrf_score"] >= results[i + 1]["rrf_score"]
