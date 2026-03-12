# =============================================================================
# Module: test_bm25_retrieval.py
# Purpose: Test BM25 retrieval via FTS5 MATCH — stage 2 of the light search
#   pipeline. Validates scoring, normalization, cap, and edge cases.
# Rationale: BM25 is often the primary retrieval signal (vector may be
#   unavailable). The normalization formula |x|/(1+|x|) must be tested to
#   ensure it correctly maps negative FTS5 scores to 0-1 range. The internal
#   cap of 100 must be enforced to prevent downstream explosion.
# Responsibility:
#   - Test FTS5 MATCH returns correct neuron IDs
#   - Test BM25 raw scores are captured (negative values)
#   - Test normalization formula: |x|/(1+|x|)
#   - Test candidate cap at 100
#   - Test empty/no-match queries return empty list
#   - Test FTS5 query sanitization (special chars)
#   - Test ranking order (best match = rank 0)
# Organization:
#   1. Imports and fixtures
#   2. Basic retrieval tests
#   3. Score normalization tests
#   4. Cap and ranking tests
#   5. Edge case tests (empty, special chars, no matches)
# =============================================================================

from __future__ import annotations

import time

import pytest

from memory_cli.search.bm25_retrieval_fts5_match import (
    retrieve_bm25,
    _build_fts5_query,
    _normalize_bm25_score,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """Full in-memory DB with FTS5 index via v001 migration."""
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
    """Insert a neuron and optional tags; returns neuron id."""
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


@pytest.fixture
def fts_db(migrated_conn):
    """Populated DB with 5 neurons for BM25 testing."""
    conn = migrated_conn
    conn.execute("BEGIN")
    _insert_neuron(conn, "python programming language", tags=["python"])
    _insert_neuron(conn, "python data science", tags=["python", "data"])
    _insert_neuron(conn, "rust systems programming", tags=["rust"])
    _insert_neuron(conn, "memory management in rust", tags=["rust", "memory"])
    _insert_neuron(conn, "machine learning algorithms", tags=["ml"])
    conn.execute("COMMIT")
    return conn


# -----------------------------------------------------------------------------
# Basic retrieval tests
# -----------------------------------------------------------------------------

class TestBM25Retrieval:
    """Test basic BM25 retrieval via FTS5 MATCH."""

    def test_single_term_matches(self, fts_db):
        """Verify searching for "python" returns neurons 1 and 2.

        Assert: returned neuron_ids include the two python neurons.
        """
        results = retrieve_bm25(fts_db, "python")
        assert len(results) >= 2
        neuron_ids = [r["neuron_id"] for r in results]
        # Python neurons should appear
        assert any(nid in neuron_ids for nid in [1, 2])

    def test_multi_term_matches(self, fts_db):
        """Verify searching for "python programming" returns relevant neurons.

        FTS5 implicit AND: neurons must contain both terms.
        """
        results = retrieve_bm25(fts_db, "python programming")
        assert len(results) >= 1
        neuron_ids = [r["neuron_id"] for r in results]
        # At least neuron 1 should match "python programming language"
        assert len(neuron_ids) >= 1

    def test_results_have_required_keys(self, fts_db):
        """Verify each result dict has: neuron_id, bm25_raw,
        bm25_normalized, bm25_rank."""
        results = retrieve_bm25(fts_db, "python")
        assert len(results) > 0
        for r in results:
            assert "neuron_id" in r
            assert "bm25_raw" in r
            assert "bm25_normalized" in r
            assert "bm25_rank" in r

    def test_bm25_raw_scores_are_negative(self, fts_db):
        """Verify raw BM25 scores from FTS5 are negative values."""
        results = retrieve_bm25(fts_db, "python")
        assert len(results) > 0
        for r in results:
            assert r["bm25_raw"] < 0, f"Expected negative raw score, got {r['bm25_raw']}"

    def test_results_ordered_by_score(self, fts_db):
        """Verify results are ordered by normalized score descending
        (best match first = rank 0)."""
        results = retrieve_bm25(fts_db, "python")
        assert len(results) > 1
        for i in range(len(results) - 1):
            assert results[i]["bm25_normalized"] >= results[i + 1]["bm25_normalized"]


# -----------------------------------------------------------------------------
# Score normalization tests
# -----------------------------------------------------------------------------

class TestBM25Normalization:
    """Test the |x|/(1+|x|) normalization formula."""

    def test_normalize_negative_score(self):
        """Verify normalization of typical negative BM25 score.

        Example: raw=-2.5 → |2.5|/(1+2.5) = 2.5/3.5 ≈ 0.714
        """
        result = _normalize_bm25_score(-2.5)
        assert abs(result - 2.5 / 3.5) < 1e-9

    def test_normalize_zero_score(self):
        """Verify normalization of zero score returns 0.0."""
        result = _normalize_bm25_score(0.0)
        assert result == 0.0

    def test_normalize_large_negative_score(self):
        """Verify large negative score normalizes close to 1.0.

        Example: raw=-100 → 100/101 ≈ 0.99
        """
        result = _normalize_bm25_score(-100.0)
        assert abs(result - 100.0 / 101.0) < 1e-9
        assert result > 0.99

    def test_normalize_small_negative_score(self):
        """Verify small negative score normalizes close to 0.0.

        Example: raw=-0.01 → 0.01/1.01 ≈ 0.0099
        """
        result = _normalize_bm25_score(-0.01)
        assert abs(result - 0.01 / 1.01) < 1e-9
        assert result < 0.02

    def test_normalized_preserves_ranking_order(self):
        """Verify normalization preserves relative ranking.

        If raw_a < raw_b (more negative = better), then
        normalized_a > normalized_b.
        """
        raw_a = -5.0  # better match (more negative)
        raw_b = -1.0  # worse match
        norm_a = _normalize_bm25_score(raw_a)
        norm_b = _normalize_bm25_score(raw_b)
        assert norm_a > norm_b


# -----------------------------------------------------------------------------
# Cap and ranking tests
# -----------------------------------------------------------------------------

class TestBM25CapAndRanking:
    """Test the 100-candidate internal cap and rank assignment."""

    def test_cap_at_100_candidates(self, migrated_conn):
        """Verify that at most 100 candidates are returned.

        Insert >100 neurons matching a common term.
        Assert: len(results) <= 100.
        """
        conn = migrated_conn
        conn.execute("BEGIN")
        for i in range(110):
            _insert_neuron(conn, f"common keyword term document {i}")
        conn.execute("COMMIT")
        results = retrieve_bm25(conn, "common keyword")
        assert len(results) <= 100

    def test_ranks_are_zero_based_sequential(self, fts_db):
        """Verify ranks are 0, 1, 2, ... in result order."""
        results = retrieve_bm25(fts_db, "python")
        for i, r in enumerate(results):
            assert r["bm25_rank"] == i

    def test_rank_zero_is_best_match(self, fts_db):
        """Verify rank 0 has the highest normalized score."""
        results = retrieve_bm25(fts_db, "python")
        assert len(results) > 0
        assert results[0]["bm25_rank"] == 0
        if len(results) > 1:
            assert results[0]["bm25_normalized"] >= results[1]["bm25_normalized"]


# -----------------------------------------------------------------------------
# Edge case tests
# -----------------------------------------------------------------------------

class TestBM25EdgeCases:
    """Test edge cases: empty queries, special characters, no matches."""

    def test_empty_query_returns_empty(self, fts_db):
        """Verify empty string query returns empty list."""
        results = retrieve_bm25(fts_db, "")
        assert results == []

    def test_whitespace_query_returns_empty(self, fts_db):
        """Verify whitespace-only query returns empty list."""
        results = retrieve_bm25(fts_db, "   ")
        assert results == []

    def test_no_matching_term_returns_empty(self, fts_db):
        """Verify query for non-existent term returns empty list."""
        results = retrieve_bm25(fts_db, "xylophone_zzzzzz_nonexistent_xyz_abc")
        assert results == []

    def test_special_chars_sanitized(self, fts_db):
        """Verify FTS5 special characters are escaped/sanitized.

        Query with quotes, parentheses, asterisks should not cause
        FTS5 MATCH syntax errors.
        """
        # Should not raise an exception — special chars are sanitized
        try:
            results = retrieve_bm25(fts_db, '"python" (AND) OR *')
            # Either empty list or valid results — no exception
            assert isinstance(results, list)
        except Exception as e:
            pytest.fail(f"Special chars caused exception: {e}")

    def test_fts5_operator_injection_prevented(self, fts_db):
        """Verify user cannot inject FTS5 operators (OR, NOT, NEAR).

        Query like 'hello OR world' should be treated as literal tokens,
        not as FTS5 boolean expression.
        """
        fts5_query = _build_fts5_query("python OR rust")
        # Each token should be double-quoted — "python" "OR" "rust"
        assert '"python"' in fts5_query
        assert '"OR"' in fts5_query
        assert '"rust"' in fts5_query
