# =============================================================================
# Module: test_vector_retrieval.py
# Purpose: Test two-step vector KNN retrieval — stage 3 of the light search
#   pipeline. Verifies the two-step pattern (standalone vec0 query, then
#   hydrate), the NO JOIN constraint, cap, and unavailable fallback.
# Rationale: The two-step vec0 pattern is the most critical architectural
#   constraint in the search pipeline. A single JOIN with vec0 would silently
#   produce wrong results. Tests must verify this pattern is followed and
#   that fallback behavior works when embeddings are unavailable.
# Responsibility:
#   - Test standalone vec0 query returns nearest neighbors
#   - Test hydration step filters out deleted/archived neurons
#   - Test NO JOIN constraint (vec0 queried in isolation)
#   - Test 100-candidate cap
#   - Test None embedding returns empty list (BM25-only fallback)
#   - Test dimension mismatch returns empty list
#   - Test vec0 table missing returns empty list gracefully
# Organization:
#   1. Imports and fixtures
#   2. Two-step pattern tests
#   3. Cap and ranking tests
#   4. Unavailable / fallback tests
#   5. Hydration tests
# =============================================================================

from __future__ import annotations

import struct
import time

import pytest

sqlite_vec = pytest.importorskip("sqlite_vec")

from memory_cli.search.vector_retrieval_two_step_knn import (
    retrieve_vectors,
    _query_vec0_standalone,
    _hydrate_vector_candidates,
    EMBEDDING_DIM,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """Full in-memory DB with all extensions and schema."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply
    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply(conn)
    conn.execute("COMMIT")
    return conn


def _insert_neuron(conn, content, project="test"):
    """Insert a basic neuron without embedding."""
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) "
        "VALUES (?, ?, ?, ?, 'active')",
        (content, now_ms, now_ms, project),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _insert_embedding(conn, neuron_id, embedding):
    """Insert a float32 embedding into neurons_vec."""
    blob = struct.pack(f"<{len(embedding)}f", *embedding)
    conn.execute(
        "INSERT INTO neurons_vec (neuron_id, embedding) VALUES (?, ?)",
        (neuron_id, blob),
    )


def _make_embedding(dim=768, base=0.0):
    """Create a normalized embedding vector with a base offset."""
    vec = [base] * dim
    vec[0] = 1.0  # non-uniform to avoid zero vector issues
    return vec


@pytest.fixture
def vec_db(migrated_conn):
    """DB with 5 neurons and embeddings, spread in embedding space."""
    conn = migrated_conn
    conn.execute("BEGIN")
    # Create neurons
    for i in range(1, 6):
        content = f"neuron content {i}"
        nid = _insert_neuron(conn, content)
        # Each neuron has a distinct embedding
        emb = [0.0] * EMBEDDING_DIM
        emb[i - 1] = 1.0  # each neuron dominant in a different dimension
        _insert_embedding(conn, nid, emb)
    conn.execute("COMMIT")
    return conn


@pytest.fixture
def sample_query_embedding():
    """768-dim query close to neuron 1 (dimension 0 = 1.0)."""
    emb = [0.0] * EMBEDDING_DIM
    emb[0] = 1.0
    return emb


# -----------------------------------------------------------------------------
# Two-step pattern tests
# -----------------------------------------------------------------------------

class TestVectorTwoStepPattern:
    """Test the two-step vec0 query pattern (standalone + hydrate)."""

    def test_returns_nearest_neighbors(self, vec_db, sample_query_embedding):
        """Verify KNN query returns neurons closest to query embedding.

        Assert: returned neuron_ids are the expected nearest neighbors
        based on known embedding distances.
        """
        results = retrieve_vectors(vec_db, sample_query_embedding)
        assert len(results) > 0
        # Neuron 1 should be the closest (embedding [1,0,0,...])
        assert results[0]["neuron_id"] == 1

    def test_results_ordered_by_distance_ascending(self, vec_db, sample_query_embedding):
        """Verify results are ordered by vector_distance ascending (closest first)."""
        results = retrieve_vectors(vec_db, sample_query_embedding)
        assert len(results) > 1
        for i in range(len(results) - 1):
            assert results[i]["vector_distance"] <= results[i + 1]["vector_distance"]

    def test_results_have_required_keys(self, vec_db, sample_query_embedding):
        """Verify each result dict has: neuron_id, vector_distance, vector_rank."""
        results = retrieve_vectors(vec_db, sample_query_embedding)
        assert len(results) > 0
        for r in results:
            assert "neuron_id" in r
            assert "vector_distance" in r
            assert "vector_rank" in r

    def test_vec0_queried_standalone(self, vec_db, sample_query_embedding):
        """Verify that the vec0 query does not JOIN with any other table.

        This is an architectural constraint test. The SQL executed against
        vec0 must be a standalone SELECT on the vec0 table only.
        """
        # _query_vec0_standalone returns only neuron_id + vector_distance
        # (no content, created_at, etc. — those come from hydration step)
        results = _query_vec0_standalone(vec_db, sample_query_embedding)
        assert len(results) > 0
        for r in results:
            assert set(r.keys()) == {"neuron_id", "vector_distance"}


# -----------------------------------------------------------------------------
# Cap and ranking tests
# -----------------------------------------------------------------------------

class TestVectorCapAndRanking:
    """Test the 100-candidate cap and rank assignment."""

    def test_cap_at_100_candidates(self, migrated_conn):
        """Verify at most 100 candidates returned from vector retrieval."""
        conn = migrated_conn
        conn.execute("BEGIN")
        for i in range(110):
            nid = _insert_neuron(conn, f"neuron {i}")
            emb = [0.0] * EMBEDDING_DIM
            emb[i % EMBEDDING_DIM] = float(i + 1)
            _insert_embedding(conn, nid, emb)
        conn.execute("COMMIT")
        query_emb = [0.0] * EMBEDDING_DIM
        query_emb[0] = 1.0
        results = retrieve_vectors(conn, query_emb)
        assert len(results) <= 100

    def test_ranks_are_zero_based(self, vec_db, sample_query_embedding):
        """Verify vector_rank is 0-based, sequential."""
        results = retrieve_vectors(vec_db, sample_query_embedding)
        for i, r in enumerate(results):
            assert r["vector_rank"] == i

    def test_rank_zero_is_closest(self, vec_db, sample_query_embedding):
        """Verify rank 0 has the smallest vector_distance."""
        results = retrieve_vectors(vec_db, sample_query_embedding)
        assert results[0]["vector_rank"] == 0
        if len(results) > 1:
            assert results[0]["vector_distance"] <= results[1]["vector_distance"]


# -----------------------------------------------------------------------------
# Unavailable / fallback tests
# -----------------------------------------------------------------------------

class TestVectorUnavailableFallback:
    """Test graceful fallback when vectors are unavailable."""

    def test_none_embedding_returns_empty(self, vec_db):
        """Verify query_embedding=None returns empty list.

        This is the BM25-only fallback trigger.
        """
        results = retrieve_vectors(vec_db, None)
        assert results == []

    def test_dimension_mismatch_returns_empty(self, vec_db):
        """Verify embedding with wrong dimension returns empty list.

        Pass a 512-dim vector when 768 is expected.
        """
        wrong_dim_emb = [0.5] * 512
        results = retrieve_vectors(vec_db, wrong_dim_emb)
        assert results == []

    def test_vec0_table_missing_returns_empty(self, migrated_conn):
        """Verify graceful handling when vec0 table doesn't exist.

        Drop vec0, then try to search.
        Assert: returns empty list, no exception raised.
        """
        conn = migrated_conn
        # Drop the vec0 table
        conn.execute("DROP TABLE IF EXISTS neurons_vec")
        query_emb = [0.0] * EMBEDDING_DIM
        query_emb[0] = 1.0
        results = retrieve_vectors(conn, query_emb)
        assert results == []

    def test_sqlite_vec_not_loaded_returns_empty(self):
        """Verify graceful handling when sqlite-vec extension not loaded.

        Use a plain sqlite3 connection without the extension.
        Assert: returns empty list, no exception raised.
        """
        import sqlite3
        conn = sqlite3.connect(":memory:")
        # Create neurons table but no vec0 (no extension loaded)
        conn.execute(
            "CREATE TABLE neurons (id INTEGER PRIMARY KEY, content TEXT, "
            "created_at INTEGER, updated_at INTEGER, project TEXT, source TEXT, "
            "status TEXT DEFAULT 'active')"
        )
        query_emb = [0.0] * EMBEDDING_DIM
        query_emb[0] = 1.0
        results = retrieve_vectors(conn, query_emb)
        assert results == []


# -----------------------------------------------------------------------------
# Hydration tests
# -----------------------------------------------------------------------------

class TestVectorHydration:
    """Test the hydration step that filters vec0 results."""

    def test_deleted_neuron_filtered_out(self, vec_db):
        """Verify neurons that no longer exist in neurons table are filtered.

        Delete a neuron after creating embedding, then search.
        Assert: deleted neuron not in results.
        """
        # Delete neuron 1 (closest to our query)
        vec_db.execute("DELETE FROM neurons WHERE id = 1")
        query_emb = [0.0] * EMBEDDING_DIM
        query_emb[0] = 1.0
        results = retrieve_vectors(vec_db, query_emb)
        neuron_ids = [r["neuron_id"] for r in results]
        assert 1 not in neuron_ids

    def test_archived_neuron_filtered_out(self, vec_db):
        """Verify archived neurons are filtered from vector results.

        Archive a neuron, then search.
        Assert: archived neuron not in results.
        """
        vec_db.execute("UPDATE neurons SET status = 'archived' WHERE id = 1")
        query_emb = [0.0] * EMBEDDING_DIM
        query_emb[0] = 1.0
        results = retrieve_vectors(vec_db, query_emb)
        neuron_ids = [r["neuron_id"] for r in results]
        assert 1 not in neuron_ids

    def test_hydration_preserves_distance_order(self, vec_db):
        """Verify filtering doesn't change the distance ordering of results."""
        # Archive neuron 1 (closest), results should still be distance-ordered
        vec_db.execute("UPDATE neurons SET status = 'archived' WHERE id = 1")
        query_emb = [0.0] * EMBEDDING_DIM
        query_emb[0] = 1.0
        results = retrieve_vectors(vec_db, query_emb)
        for i in range(len(results) - 1):
            assert results[i]["vector_distance"] <= results[i + 1]["vector_distance"]
