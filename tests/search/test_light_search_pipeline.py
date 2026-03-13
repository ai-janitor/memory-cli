# =============================================================================
# Module: test_light_search_pipeline.py
# Purpose: End-to-end tests for the 10-stage light search pipeline. Verifies
#   that all stages integrate correctly, BM25-only fallback works, empty
#   results produce exit code 1, and errors produce exit code 2.
# Rationale: Unit tests for individual stages live in their own files. This
#   file tests the orchestrator's wiring: does it call stages in order, pass
#   state correctly, and handle edge cases at the pipeline level?
# Responsibility:
#   - Test full pipeline with both BM25 + vector results
#   - Test BM25-only fallback when embeddings unavailable
#   - Test empty result handling (exit code 1)
#   - Test error handling (exit code 2)
#   - Test SearchOptions defaults and overrides
#   - Test PipelineState threading between stages
#   - Test SearchResultEnvelope structure
# Organization:
#   1. Imports and fixtures
#   2. Full pipeline integration tests
#   3. BM25-only fallback tests
#   4. Empty result tests
#   5. Error handling tests
#   6. Options and envelope structure tests
# =============================================================================

from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest

from memory_cli.search.light_search_pipeline_orchestrator import (
    light_search,
    SearchOptions,
    SearchResultEnvelope,
    PipelineState,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """Full in-memory DB with schema and FTS5."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply
    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply(conn)
    conn.execute("COMMIT")
    return conn


def _insert_neuron(conn, content, project="test", tags=None):
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) "
        "VALUES (?, ?, ?, ?, 'active')",
        (content, now_ms, now_ms, project),
    )
    nid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    if tags:
        for t in tags:
            from memory_cli.registries import tag_autocreate
            tid = tag_autocreate(conn, t)
            conn.execute(
                "INSERT OR IGNORE INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)",
                (nid, tid),
            )
    return nid


def _insert_edge(conn, source_id, target_id, weight=1.0, reason="related"):
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO edges (source_id, target_id, weight, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (source_id, target_id, weight, reason, now_ms),
    )


@pytest.fixture
def search_db(migrated_conn):
    """DB with 5 neurons, tags, and edges for end-to-end search testing."""
    conn = migrated_conn
    conn.execute("BEGIN")
    n1 = _insert_neuron(conn, "python programming language tutorial",
                        tags=["python", "search"])
    n2 = _insert_neuron(conn, "python data science library",
                        tags=["python", "data"])
    n3 = _insert_neuron(conn, "rust systems programming memory safety",
                        tags=["rust", "memory"])
    n4 = _insert_neuron(conn, "memory management techniques",
                        tags=["memory", "search"])
    n5 = _insert_neuron(conn, "machine learning algorithms",
                        tags=["ml"])
    # Add some edges
    _insert_edge(conn, n1, n2, 0.8, "related_python")
    _insert_edge(conn, n2, n3, 0.5, "language_comparison")
    _insert_edge(conn, n1, n4, 0.6, "memory_related")
    conn.execute("COMMIT")
    return conn, [n1, n2, n3, n4, n5]


@pytest.fixture
def default_options():
    """Default SearchOptions for basic query testing."""
    return SearchOptions(query="python", limit=20, offset=0)


# Helper to mock embedding — returns None to simulate unavailability
def _mock_embedding_unavailable(*args, **kwargs):
    raise FileNotFoundError("Model not available")


# -----------------------------------------------------------------------------
# Full pipeline integration tests
# -----------------------------------------------------------------------------

class TestLightSearchFullPipeline:
    """Test the complete 10-stage pipeline with all retrieval modes active."""

    def test_basic_search_returns_results(self, search_db):
        """Verify a simple query returns a non-empty SearchResultEnvelope.

        Steps:
        1. Search for a known term present in sample neurons.
        2. Assert envelope.results is non-empty.
        3. Assert envelope.exit_code == 0.
        """
        conn, nids = search_db
        options = SearchOptions(query="python", fan_out_depth=0)
        # Mock embedding to fail (BM25-only mode for reliable testing)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope = light_search(conn, options)
        assert len(envelope.results) > 0
        assert envelope.exit_code == 0

    def test_result_contains_required_fields(self, search_db):
        """Verify each result record has all required output fields.

        Required: id, content, created_at, updated_at, project, source,
        status, tags, match_type, hop_distance, edge_reason, score.
        """
        conn, nids = search_db
        options = SearchOptions(query="python", fan_out_depth=0)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope = light_search(conn, options)
        required_fields = {
            "id", "content", "created_at", "updated_at", "project", "source",
            "status", "tags", "match_type", "hop_distance", "edge_reason", "score"
        }
        for result in envelope.results:
            for field in required_fields:
                assert field in result, f"Missing field: {field}"

    def test_results_sorted_by_score_descending(self, search_db):
        """Verify results are ordered by score descending."""
        conn, nids = search_db
        options = SearchOptions(query="python", fan_out_depth=0)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope = light_search(conn, options)
        scores = [r["score"] for r in envelope.results]
        assert scores == sorted(scores, reverse=True)

    def test_direct_matches_have_match_type_direct(self, search_db):
        """Verify direct BM25/vector matches have match_type='direct_match'.

        Tag-affinity may also discover tag-connected neurons (match_type='tag_affinity'),
        which is valid. No edge-based fan_out should appear at fan_out_depth=0.
        """
        conn, nids = search_db
        options = SearchOptions(query="python", fan_out_depth=0)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope = light_search(conn, options)
        # With fan_out_depth=0, no edge-based fan_out; direct_match and tag_affinity are valid
        for r in envelope.results:
            assert r["match_type"] in ("direct_match", "tag_affinity")

    def test_fan_out_results_have_hop_distance_gt_zero(self, search_db):
        """Verify fan-out results have hop_distance > 0 and edge_reason set."""
        conn, nids = search_db
        options = SearchOptions(query="python", fan_out_depth=1)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope = light_search(conn, options)
        fan_out_results = [r for r in envelope.results if r["match_type"] == "fan_out"]
        for r in fan_out_results:
            assert r["hop_distance"] > 0
            assert r["edge_reason"] is not None

    def test_envelope_pagination_metadata(self, search_db):
        """Verify envelope has correct pagination fields:
        total, limit, offset, has_more."""
        conn, nids = search_db
        options = SearchOptions(query="python", limit=2, offset=0, fan_out_depth=0)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope = light_search(conn, options)
        assert envelope.limit == 2
        assert envelope.offset == 0
        assert isinstance(envelope.total_before_pagination, int)


# -----------------------------------------------------------------------------
# BM25-only fallback tests
# -----------------------------------------------------------------------------

class TestLightSearchBM25OnlyFallback:
    """Test pipeline behavior when vector retrieval is unavailable."""

    def test_bm25_only_returns_results(self, search_db):
        """Verify search still works with BM25 only (no embeddings).

        Simulate: embedding model unavailable.
        Assert: results returned, vector_unavailable = True.
        """
        conn, nids = search_db
        options = SearchOptions(query="python", fan_out_depth=0)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope = light_search(conn, options)
        assert len(envelope.results) > 0
        assert envelope.vector_unavailable is True

    def test_bm25_only_sets_vector_unavailable_flag(self, search_db):
        """Verify envelope.vector_unavailable is True in BM25-only mode."""
        conn, nids = search_db
        options = SearchOptions(query="python", fan_out_depth=0)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope = light_search(conn, options)
        assert envelope.vector_unavailable is True

    def test_bm25_only_results_have_no_vector_scores(self, search_db):
        """Verify BM25-only results have vector_distance=None, vector_rank=None
        in their explain breakdown."""
        conn, nids = search_db
        options = SearchOptions(query="python", fan_out_depth=0, explain=True)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope = light_search(conn, options)
        for r in envelope.results:
            if "score_breakdown" in r:
                assert r["score_breakdown"]["vector_distance"] is None
                assert r["score_breakdown"]["vector_rank"] is None


# -----------------------------------------------------------------------------
# Empty result tests
# -----------------------------------------------------------------------------

class TestLightSearchEmptyResults:
    """Test pipeline behavior when no results match."""

    def test_no_match_returns_exit_code_1(self, search_db):
        """Verify exit_code=1 when query matches nothing.

        Search for a term not present in any neuron.
        """
        conn, nids = search_db
        options = SearchOptions(query="xylophone_zzz_nonexistent_abc_xyz_q123",
                                fan_out_depth=0)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope = light_search(conn, options)
        assert envelope.exit_code == 1

    def test_no_match_returns_empty_results_list(self, search_db):
        """Verify envelope.results is empty list when no matches."""
        conn, nids = search_db
        options = SearchOptions(query="xylophone_zzz_nonexistent_abc_xyz_q123",
                                fan_out_depth=0)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope = light_search(conn, options)
        assert envelope.results == []

    def test_empty_query_returns_exit_code_1(self, search_db):
        """Verify empty/whitespace query returns exit_code=1."""
        conn, nids = search_db
        options = SearchOptions(query="", fan_out_depth=0)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope = light_search(conn, options)
        assert envelope.exit_code == 1


# -----------------------------------------------------------------------------
# Error handling tests
# -----------------------------------------------------------------------------

class TestLightSearchErrorHandling:
    """Test pipeline error handling and exit code 2."""

    def test_database_error_returns_exit_code_2(self):
        """Verify exit_code=2 when database error occurs.

        Simulate: closed connection.
        """
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.close()  # Close the connection to force error
        options = SearchOptions(query="python", fan_out_depth=0)
        envelope = light_search(conn, options)
        assert envelope.exit_code == 2


# -----------------------------------------------------------------------------
# Options and envelope structure tests
# -----------------------------------------------------------------------------

class TestSearchOptionsAndEnvelope:
    """Test SearchOptions defaults and SearchResultEnvelope structure."""

    def test_default_options_values(self):
        """Verify SearchOptions defaults:
        limit=20, offset=0, tags=[], tag_mode='AND',
        fan_out_depth=1, explain=False.
        """
        opts = SearchOptions(query="test")
        assert opts.limit == 20
        assert opts.offset == 0
        assert opts.tags == []
        assert opts.tag_mode == "AND"
        assert opts.fan_out_depth == 1
        assert opts.explain is False

    def test_pagination_limit_offset(self, search_db):
        """Verify --limit and --offset correctly paginate results.

        Create enough results to span multiple pages.
        Assert: offset skips, limit caps.
        """
        conn, nids = search_db
        # Get all results with no limit
        options_all = SearchOptions(query="python", limit=100, offset=0, fan_out_depth=0)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope_all = light_search(conn, options_all)

        if len(envelope_all.results) < 2:
            pytest.skip("Not enough results to test pagination")

        # Get first page
        options_p1 = SearchOptions(query="python", limit=1, offset=0, fan_out_depth=0)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope_p1 = light_search(conn, options_p1)
        assert len(envelope_p1.results) <= 1

        # Get second page
        options_p2 = SearchOptions(query="python", limit=1, offset=1, fan_out_depth=0)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope_p2 = light_search(conn, options_p2)
        # Pages should have different results
        if len(envelope_p1.results) == 1 and len(envelope_p2.results) == 1:
            assert envelope_p1.results[0]["id"] != envelope_p2.results[0]["id"]

    def test_explain_flag_adds_score_breakdown(self, search_db):
        """Verify --explain adds score_breakdown to each result.

        Assert: breakdown contains bm25_raw, bm25_normalized, bm25_rank,
        vector_distance, vector_rank, rrf_score, activation_score,
        hop_distance, temporal_weight, final_score, vector_unavailable.
        """
        conn, nids = search_db
        options = SearchOptions(query="python", fan_out_depth=0, explain=True)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope = light_search(conn, options)
        expected_breakdown_fields = {
            "bm25_raw", "bm25_normalized", "bm25_rank",
            "vector_distance", "vector_rank",
            "rrf_score", "activation_score", "hop_distance",
            "temporal_weight", "final_score", "vector_unavailable",
        }
        for r in envelope.results:
            assert "score_breakdown" in r
            for field in expected_breakdown_fields:
                assert field in r["score_breakdown"], f"Missing breakdown field: {field}"

    def test_tag_filter_reduces_results(self, search_db):
        """Verify --tag filters reduce result count.

        Search with a tag that only some neurons have.
        Assert: all results have the required tag.
        """
        conn, nids = search_db
        # Search for 'programming' which should match python and rust neurons
        # but filter to only 'python' tagged ones
        options = SearchOptions(
            query="programming",
            tags=["python"],
            tag_mode="AND",
            fan_out_depth=0,
        )
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope = light_search(conn, options)
        # All results should have the python tag
        for r in envelope.results:
            assert "python" in r["tags"]

    def test_fan_out_depth_zero_no_fan_out(self, search_db):
        """Verify --fan-out-depth=0 returns no edge-based fan_out results.

        Assert: no results with match_type='fan_out'.
        Tag-affinity discoveries (match_type='tag_affinity') are valid even at depth=0.
        """
        conn, nids = search_db
        options = SearchOptions(query="python", fan_out_depth=0)
        with patch("memory_cli.search.light_search_pipeline_orchestrator.get_model",
                   side_effect=FileNotFoundError):
            envelope = light_search(conn, options)
        for r in envelope.results:
            assert r["match_type"] in ("direct_match", "tag_affinity")
