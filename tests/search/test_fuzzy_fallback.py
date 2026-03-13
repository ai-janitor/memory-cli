# =============================================================================
# Module: test_fuzzy_fallback.py
# Purpose: Tests for the fuzzy matching fallback — last-resort search when
#   BM25 + vector return nothing. Verifies fuzzy matching on content, tags,
#   and attr values, threshold filtering, and pipeline integration.
# Rationale: The fuzzy fallback is a safety net that must work correctly when
#   invoked but must NOT interfere with normal search results. Tests verify
#   both the standalone fuzzy_search() function and its integration into the
#   light_search pipeline.
# Responsibility:
#   - Test fuzzy matching on neuron content (misspelled words)
#   - Test fuzzy matching on attr values (name misspellings)
#   - Test fuzzy matching on tag names
#   - Test threshold filtering (low-similarity rejects)
#   - Test that fuzzy is NOT invoked when primary search has results
#   - Test result format compatibility with hydration pipeline
# Organization:
#   1. Imports and fixtures
#   2. Standalone fuzzy_search() tests
#   3. Pipeline integration tests
# =============================================================================

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from memory_cli.search.fuzzy_fallback_levenshtein import fuzzy_search, _fuzzy_ratio
from memory_cli.search.light_search_pipeline_orchestrator import (
    light_search,
    SearchOptions,
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


def _insert_neuron(conn, content, project="test", tags=None, attrs=None):
    """Insert a neuron with optional tags and attrs. Returns neuron_id."""
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) "
        "VALUES (?, ?, ?, ?, 'active')",
        (content, now_ms, now_ms, project),
    )
    nid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Insert into FTS index
    conn.execute(
        "INSERT INTO neurons_fts (rowid, content) VALUES (?, ?)",
        (nid, content),
    )

    if tags:
        for t in tags:
            from memory_cli.registries import tag_autocreate
            tid = tag_autocreate(conn, t)
            conn.execute(
                "INSERT OR IGNORE INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)",
                (nid, tid),
            )

    if attrs:
        for key, value in attrs.items():
            # Ensure attr_key exists
            existing = conn.execute(
                "SELECT id FROM attr_keys WHERE name = ?", (key,)
            ).fetchone()
            if existing:
                ak_id = existing[0]
            else:
                conn.execute(
                    "INSERT INTO attr_keys (name, created_at) VALUES (?, ?)",
                    (key, now_ms),
                )
                ak_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT OR REPLACE INTO neuron_attrs (neuron_id, attr_key_id, value) "
                "VALUES (?, ?, ?)",
                (nid, ak_id, value),
            )

    return nid


@pytest.fixture
def fuzzy_db(migrated_conn):
    """DB with neurons designed for fuzzy matching tests."""
    conn = migrated_conn
    conn.execute("BEGIN")

    # Neuron with a person name — target for "adidit" -> "Aditi" test
    n1 = _insert_neuron(
        conn,
        "Aditi Srivastava is a senior engineer on the platform team",
        tags=["person", "engineering"],
        attrs={"name": "Aditi Srivastava", "email": "aditi@example.com"},
    )

    # Neuron with different content — should not match "adidit"
    n2 = _insert_neuron(
        conn,
        "Python programming language tutorial for beginners",
        tags=["python", "tutorial"],
    )

    # Neuron with a tag that fuzzy-matches "pythn"
    n3 = _insert_neuron(
        conn,
        "Data science workflow automation",
        tags=["python", "data-science"],
    )

    # Neuron with attr value that fuzzy-matches
    n4 = _insert_neuron(
        conn,
        "Meeting notes from quarterly review",
        tags=["meeting"],
        attrs={"attendee": "Michael Johnson", "topic": "quarterly-review"},
    )

    conn.execute("COMMIT")
    return conn, {"n1": n1, "n2": n2, "n3": n3, "n4": n4}


# -----------------------------------------------------------------------------
# Standalone fuzzy_search() tests
# -----------------------------------------------------------------------------

class TestFuzzySearchStandalone:
    """Test the fuzzy_search() function directly."""

    def test_fuzzy_matches_misspelled_name_in_content(self, fuzzy_db):
        """'adidit' should fuzzy-match 'Aditi' in neuron content."""
        conn, nids = fuzzy_db
        results = fuzzy_search(conn, "adidit", limit=10, threshold=0.4)
        assert len(results) > 0
        # The Aditi neuron should be in results
        matched_ids = [r["neuron_id"] for r in results]
        assert nids["n1"] in matched_ids

    def test_fuzzy_matches_attr_value(self, fuzzy_db):
        """'Micheal' (misspelled) should fuzzy-match 'Michael' in attr value."""
        conn, nids = fuzzy_db
        results = fuzzy_search(conn, "Micheal", limit=10, threshold=0.4)
        assert len(results) > 0
        matched_ids = [r["neuron_id"] for r in results]
        assert nids["n4"] in matched_ids

    def test_fuzzy_matches_tag_name(self, fuzzy_db):
        """'pythn' should fuzzy-match 'python' tag."""
        conn, nids = fuzzy_db
        results = fuzzy_search(conn, "pythn", limit=10, threshold=0.4)
        assert len(results) > 0
        # At least one result should have matched on tag
        tag_matches = [r for r in results if r["fuzzy_matched_field"].startswith("tag:")]
        assert len(tag_matches) > 0

    def test_fuzzy_result_format(self, fuzzy_db):
        """Verify fuzzy results have the required fields for hydration."""
        conn, nids = fuzzy_db
        results = fuzzy_search(conn, "adidit", limit=10, threshold=0.4)
        assert len(results) > 0
        required_fields = {
            "neuron_id", "match_type", "fuzzy_score",
            "fuzzy_matched_field", "final_score", "hop_distance", "edge_reason",
        }
        for r in results:
            for f in required_fields:
                assert f in r, f"Missing field: {f}"
            assert r["match_type"] == "fuzzy"
            assert 0.0 <= r["fuzzy_score"] <= 1.0
            assert r["hop_distance"] == 0
            assert r["edge_reason"] is None

    def test_fuzzy_threshold_filters_low_scores(self, fuzzy_db):
        """High threshold should return fewer or no results."""
        conn, nids = fuzzy_db
        # With threshold 0.99, almost nothing should match
        results = fuzzy_search(conn, "adidit", limit=10, threshold=0.99)
        assert len(results) == 0

    def test_fuzzy_empty_query_returns_empty(self, fuzzy_db):
        """Empty query should return no results."""
        conn, nids = fuzzy_db
        results = fuzzy_search(conn, "", limit=10, threshold=0.4)
        assert results == []

    def test_fuzzy_limit_caps_results(self, fuzzy_db):
        """Limit parameter should cap the number of results."""
        conn, nids = fuzzy_db
        results = fuzzy_search(conn, "a", limit=1, threshold=0.1)
        assert len(results) <= 1

    def test_fuzzy_results_sorted_by_score_descending(self, fuzzy_db):
        """Results should be sorted by fuzzy_score descending."""
        conn, nids = fuzzy_db
        results = fuzzy_search(conn, "python", limit=10, threshold=0.3)
        scores = [r["fuzzy_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_fuzzy_exact_substring_scores_1(self, fuzzy_db):
        """Exact substring match in content should score 1.0."""
        conn, nids = fuzzy_db
        results = fuzzy_search(conn, "Aditi", limit=10, threshold=0.4)
        assert len(results) > 0
        aditi_result = [r for r in results if r["neuron_id"] == nids["n1"]]
        assert len(aditi_result) == 1
        assert aditi_result[0]["fuzzy_score"] == 1.0


# -----------------------------------------------------------------------------
# Pipeline integration tests
# -----------------------------------------------------------------------------

class TestFuzzyFallbackInPipeline:
    """Test fuzzy fallback integration in light_search pipeline."""

    def test_fuzzy_fires_when_primary_returns_nothing(self, fuzzy_db):
        """When BM25 returns nothing, fuzzy fallback should kick in."""
        conn, nids = fuzzy_db
        # "adidit" won't match BM25 but should fuzzy-match "Aditi"
        options = SearchOptions(query="adidit", fan_out_depth=0)
        with patch(
            "memory_cli.search.light_search_pipeline_orchestrator.get_model",
            side_effect=FileNotFoundError,
        ):
            envelope = light_search(conn, options)
        # Should find results via fuzzy fallback
        assert len(envelope.results) > 0
        assert envelope.exit_code == 0
        # All results should be fuzzy type
        for r in envelope.results:
            assert r["match_type"] == "fuzzy"
            assert "fuzzy_score" in r
            assert "fuzzy_matched_field" in r

    def test_fuzzy_does_not_fire_when_primary_has_results(self, fuzzy_db):
        """When BM25 returns results, fuzzy should NOT be called."""
        conn, nids = fuzzy_db
        # "python" will match BM25 directly
        options = SearchOptions(query="python", fan_out_depth=0)
        with patch(
            "memory_cli.search.light_search_pipeline_orchestrator.get_model",
            side_effect=FileNotFoundError,
        ):
            envelope = light_search(conn, options)
        # Results should be direct_match, not fuzzy
        assert len(envelope.results) > 0
        for r in envelope.results:
            assert r["match_type"] == "direct_match"
            assert "fuzzy_score" not in r

    def test_fuzzy_results_have_full_neuron_data(self, fuzzy_db):
        """Fuzzy results should be fully hydrated with content, tags, etc."""
        conn, nids = fuzzy_db
        options = SearchOptions(query="adidit", fan_out_depth=0)
        with patch(
            "memory_cli.search.light_search_pipeline_orchestrator.get_model",
            side_effect=FileNotFoundError,
        ):
            envelope = light_search(conn, options)
        assert len(envelope.results) > 0
        for r in envelope.results:
            assert "id" in r
            assert "content" in r
            assert "tags" in r
            assert "created_at" in r


# -----------------------------------------------------------------------------
# _fuzzy_ratio unit tests
# -----------------------------------------------------------------------------

class TestFuzzyRatio:
    """Test the _fuzzy_ratio helper function."""

    def test_identical_strings_score_1(self):
        assert _fuzzy_ratio("hello", "hello") == 1.0

    def test_completely_different_score_low(self):
        assert _fuzzy_ratio("abc", "xyz") < 0.3

    def test_similar_strings_score_high(self):
        # "adidit" vs "aditi" should be reasonably similar
        score = _fuzzy_ratio("adidit", "aditi")
        assert score > 0.5

    def test_empty_strings(self):
        assert _fuzzy_ratio("", "") == 1.0
        assert _fuzzy_ratio("hello", "") == 0.0
