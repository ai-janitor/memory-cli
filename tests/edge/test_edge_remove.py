# =============================================================================
# Module: test_edge_remove.py
# Purpose: Test edge removal via edge_remove() — successful deletion, not-found
#   error, and verification that neurons remain unaffected after edge removal.
# Rationale: Edge removal must be precise — only the relationship row is
#   deleted, both endpoint neurons stay intact. The not-found case must return
#   exit code 1 (not 2) because it's a "resource not found" error, not a
#   validation error. We also need to verify that removing an edge from A->B
#   does not remove a B->A edge if one exists (direction matters).
# Responsibility:
#   - Test removing an existing edge succeeds and returns deleted edge info
#   - Test removing a non-existent edge raises EdgeRemoveError (exit 1)
#   - Test that neurons at both endpoints still exist after edge removal
#   - Test that neuron data (content, tags, attrs) is unmodified after edge removal
#   - Test that removing A->B does not affect B->A
#   - Test that removing an edge from a self-loop works correctly
# Organization:
#   1. Imports and fixtures
#   2. TestEdgeRemoveHappyPath — successful removal scenarios
#   3. TestEdgeRemoveNotFound — not-found error path
#   4. TestEdgeRemoveNeuronsUnaffected — verify neurons survive edge removal
# =============================================================================

from __future__ import annotations

import time

import pytest
from typing import Any, Dict

# --- Module-level guard: all tests in this file require sqlite_vec ---
sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec required for full schema (vec0 table)"
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """In-memory SQLite with full migrated schema including neurons_vec."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply

    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


def _create_test_neuron(conn, content="test content", project="test-project"):
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) VALUES (?, ?, ?, ?, 'active')",
        (content, now_ms, now_ms, project)
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _create_test_edge(conn, source_id, target_id, reason="test-link", weight=1.0, created_at=None):
    if created_at is None:
        created_at = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO edges (source_id, target_id, reason, weight, created_at) VALUES (?, ?, ?, ?, ?)",
        (source_id, target_id, reason, weight, created_at)
    )


# -----------------------------------------------------------------------------
# Happy path tests
# -----------------------------------------------------------------------------

class TestEdgeRemoveHappyPath:
    """Test successful edge removal."""

    def test_remove_existing_edge(self, migrated_conn):
        """Remove an edge that exists in the database.

        Expects:
        - No exception raised
        - Returned dict has the deleted edge's source_id, target_id, reason, weight
        - Edge no longer exists in DB (SELECT returns no row)
        """
        from memory_cli.edge.edge_remove_by_source_target import edge_remove

        src = _create_test_neuron(migrated_conn, "source neuron")
        tgt = _create_test_neuron(migrated_conn, "target neuron")
        _create_test_edge(migrated_conn, src, tgt, "link reason")

        result = edge_remove(migrated_conn, src, tgt)

        assert result["source_id"] == src
        assert result["target_id"] == tgt
        assert result["reason"] == "link reason"

        # Verify no longer in DB
        row = migrated_conn.execute(
            "SELECT * FROM edges WHERE source_id=? AND target_id=?", (src, tgt)
        ).fetchone()
        assert row is None

    def test_remove_returns_deleted_edge_info(self, migrated_conn):
        """Verify the returned dict contains correct edge data.

        The returned dict should match the edge that was deleted, allowing
        the CLI to display "Removed edge from X to Y (reason: ...)".
        """
        from memory_cli.edge.edge_remove_by_source_target import edge_remove

        src = _create_test_neuron(migrated_conn, "src")
        tgt = _create_test_neuron(migrated_conn, "tgt")
        _create_test_edge(migrated_conn, src, tgt, "the reason", weight=2.0)

        result = edge_remove(migrated_conn, src, tgt)

        assert result["source_id"] == src
        assert result["target_id"] == tgt
        assert result["reason"] == "the reason"
        assert result["weight"] == 2.0
        assert "created_at" in result

    def test_remove_self_loop_edge(self, migrated_conn):
        """Remove a self-loop edge (source == target).

        Expects:
        - Edge removed successfully
        - Neuron still exists (self-loops don't imply self-deletion)
        """
        from memory_cli.edge.edge_remove_by_source_target import edge_remove

        a = _create_test_neuron(migrated_conn, "self-ref")
        _create_test_edge(migrated_conn, a, a, "self reference")

        result = edge_remove(migrated_conn, a, a)

        assert result["source_id"] == a
        assert result["target_id"] == a

        # Neuron still exists
        row = migrated_conn.execute("SELECT id FROM neurons WHERE id=?", (a,)).fetchone()
        assert row is not None


# -----------------------------------------------------------------------------
# Not-found error tests
# -----------------------------------------------------------------------------

class TestEdgeRemoveNotFound:
    """Test edge not-found error paths."""

    def test_edge_not_found_exit_1(self, migrated_conn):
        """Remove an edge that doesn't exist.

        Expects:
        - EdgeRemoveError raised
        - exit_code == 1
        - Message mentions the source and target IDs
        """
        from memory_cli.edge.edge_remove_by_source_target import edge_remove, EdgeRemoveError

        src = _create_test_neuron(migrated_conn)
        tgt = _create_test_neuron(migrated_conn, "another")

        with pytest.raises(EdgeRemoveError) as exc_info:
            edge_remove(migrated_conn, src, tgt)

        assert exc_info.value.exit_code == 1
        assert str(src) in str(exc_info.value)
        assert str(tgt) in str(exc_info.value)

    def test_wrong_direction_not_found(self, migrated_conn):
        """Edge exists A->B but trying to remove B->A (which doesn't exist).

        Expects:
        - EdgeRemoveError raised with exit_code == 1
        - The A->B edge is unaffected
        """
        from memory_cli.edge.edge_remove_by_source_target import edge_remove, EdgeRemoveError

        a = _create_test_neuron(migrated_conn, "neuron a")
        b = _create_test_neuron(migrated_conn, "neuron b")
        _create_test_edge(migrated_conn, a, b, "a to b")

        with pytest.raises(EdgeRemoveError) as exc_info:
            edge_remove(migrated_conn, b, a)  # B->A doesn't exist

        assert exc_info.value.exit_code == 1

        # A->B still exists
        row = migrated_conn.execute(
            "SELECT * FROM edges WHERE source_id=? AND target_id=?", (a, b)
        ).fetchone()
        assert row is not None

    def test_remove_already_removed_edge(self, migrated_conn):
        """Remove an edge, then try to remove it again.

        Expects:
        - First remove succeeds
        - Second remove raises EdgeRemoveError(exit_code=1)
        """
        from memory_cli.edge.edge_remove_by_source_target import edge_remove, EdgeRemoveError

        src = _create_test_neuron(migrated_conn)
        tgt = _create_test_neuron(migrated_conn, "another")
        _create_test_edge(migrated_conn, src, tgt, "once only")

        edge_remove(migrated_conn, src, tgt)

        with pytest.raises(EdgeRemoveError) as exc_info:
            edge_remove(migrated_conn, src, tgt)

        assert exc_info.value.exit_code == 1


# -----------------------------------------------------------------------------
# Neurons unaffected tests
# -----------------------------------------------------------------------------

class TestEdgeRemoveNeuronsUnaffected:
    """Verify that neurons are completely unaffected by edge removal."""

    def test_source_neuron_still_exists(self, migrated_conn):
        """After removing edge A->B, neuron A still exists with all data.

        Query neuron A directly — it should have the same content, tags,
        attrs, status as before the edge removal.
        """
        from memory_cli.edge.edge_remove_by_source_target import edge_remove

        src = _create_test_neuron(migrated_conn, "source content")
        tgt = _create_test_neuron(migrated_conn, "target content")
        _create_test_edge(migrated_conn, src, tgt)

        edge_remove(migrated_conn, src, tgt)

        row = migrated_conn.execute(
            "SELECT id, content, status FROM neurons WHERE id=?", (src,)
        ).fetchone()
        assert row is not None
        assert row["content"] == "source content"
        assert row["status"] == "active"

    def test_target_neuron_still_exists(self, migrated_conn):
        """After removing edge A->B, neuron B still exists with all data.

        Query neuron B directly — it should be completely unmodified.
        """
        from memory_cli.edge.edge_remove_by_source_target import edge_remove

        src = _create_test_neuron(migrated_conn, "source content")
        tgt = _create_test_neuron(migrated_conn, "target content")
        _create_test_edge(migrated_conn, src, tgt)

        edge_remove(migrated_conn, src, tgt)

        row = migrated_conn.execute(
            "SELECT id, content, status FROM neurons WHERE id=?", (tgt,)
        ).fetchone()
        assert row is not None
        assert row["content"] == "target content"
        assert row["status"] == "active"

    def test_other_edges_unaffected(self, migrated_conn):
        """Removing one edge doesn't affect other edges from/to the same neurons.

        Setup: edges A->B, A->C. Remove A->B.
        Expects: A->C still exists and is unmodified.
        """
        from memory_cli.edge.edge_remove_by_source_target import edge_remove

        a = _create_test_neuron(migrated_conn, "neuron a")
        b = _create_test_neuron(migrated_conn, "neuron b")
        c = _create_test_neuron(migrated_conn, "neuron c")
        _create_test_edge(migrated_conn, a, b, "a to b")
        _create_test_edge(migrated_conn, a, c, "a to c")

        edge_remove(migrated_conn, a, b)

        # A->C still exists
        row = migrated_conn.execute(
            "SELECT reason FROM edges WHERE source_id=? AND target_id=?", (a, c)
        ).fetchone()
        assert row is not None
        assert row["reason"] == "a to c"

    def test_circular_remove_one_direction(self, migrated_conn):
        """Remove A->B from circular pair (A->B, B->A).

        Expects:
        - A->B removed
        - B->A still exists and is unmodified
        - Both neurons still exist
        """
        from memory_cli.edge.edge_remove_by_source_target import edge_remove

        a = _create_test_neuron(migrated_conn, "neuron a")
        b = _create_test_neuron(migrated_conn, "neuron b")
        _create_test_edge(migrated_conn, a, b, "a to b")
        _create_test_edge(migrated_conn, b, a, "b to a")

        edge_remove(migrated_conn, a, b)

        # A->B removed
        row_ab = migrated_conn.execute(
            "SELECT * FROM edges WHERE source_id=? AND target_id=?", (a, b)
        ).fetchone()
        assert row_ab is None

        # B->A still exists
        row_ba = migrated_conn.execute(
            "SELECT reason FROM edges WHERE source_id=? AND target_id=?", (b, a)
        ).fetchone()
        assert row_ba is not None
        assert row_ba["reason"] == "b to a"

        # Both neurons exist
        for neuron_id in (a, b):
            row = migrated_conn.execute(
                "SELECT id FROM neurons WHERE id=?", (neuron_id,)
            ).fetchone()
            assert row is not None
