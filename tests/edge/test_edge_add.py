# =============================================================================
# Module: test_edge_add.py
# Purpose: Test edge creation via edge_add() — happy path, all validation
#   error paths, duplicate detection, self-loop allowance, and weight handling.
# Rationale: edge_add is the primary write path for graph structure. Every
#   validation rule (source exists, target exists, reason non-empty, weight
#   positive, no duplicates) must be tested both for correct rejection and
#   correct acceptance. Self-loops and circular edges are intentional features
#   that need explicit coverage.
# Responsibility:
#   - Test successful edge creation with default weight
#   - Test successful edge creation with custom weight
#   - Test self-loop (source == target) succeeds
#   - Test circular edges (A->B and B->A) both succeed
#   - Test source neuron not found -> exit 1
#   - Test target neuron not found -> exit 1
#   - Test empty reason -> exit 2
#   - Test whitespace-only reason -> exit 2
#   - Test weight <= 0.0 -> exit 2
#   - Test weight == 0.0 -> exit 2
#   - Test duplicate (source, target) -> exit 2 with existing reason
#   - Test returned dict has all expected fields
# Organization:
#   1. Imports and fixtures
#   2. TestEdgeAddHappyPath — successful creation scenarios
#   3. TestEdgeAddValidation — input validation error paths
#   4. TestEdgeAddDuplicate — duplicate edge detection
#   5. TestEdgeAddSelfLoopAndCircular — self-loop and circular graph tests
# =============================================================================

from __future__ import annotations

import time

import pytest
from typing import Any, Dict

# --- Module-level guard: all tests in this file require sqlite_vec ---
# The v001 migration creates a vec0 virtual table, so sqlite_vec must be loaded.
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
    import time
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) VALUES (?, ?, ?, ?, 'active')",
        (content, now_ms, now_ms, project)
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


# -----------------------------------------------------------------------------
# Happy path tests
# -----------------------------------------------------------------------------

class TestEdgeAddHappyPath:
    """Test successful edge creation scenarios."""

    def test_add_edge_default_weight(self, migrated_conn):
        """Create edge with just source, target, reason — default weight 1.0.

        Expects:
        - Edge created successfully (no exception)
        - Returned dict has source_id, target_id, reason, weight, created_at
        - weight == 1.0 (default)
        - reason matches input
        - created_at is a positive integer (milliseconds)
        """
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add

        src = _create_test_neuron(migrated_conn, "source neuron")
        tgt = _create_test_neuron(migrated_conn, "target neuron")

        result = edge_add(migrated_conn, src, tgt, "test reason")

        assert result["source_id"] == src
        assert result["target_id"] == tgt
        assert result["reason"] == "test reason"
        assert result["weight"] == 1.0
        assert isinstance(result["created_at"], int)
        assert result["created_at"] > 0

    def test_add_edge_custom_weight(self, migrated_conn):
        """Create edge with explicit weight value.

        Expects:
        - weight matches the provided value (e.g., 2.5)
        - All other fields correct
        """
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add

        src = _create_test_neuron(migrated_conn, "source neuron")
        tgt = _create_test_neuron(migrated_conn, "target neuron")

        result = edge_add(migrated_conn, src, tgt, "weighted reason", weight=2.5)

        assert result["weight"] == 2.5
        assert result["source_id"] == src
        assert result["target_id"] == tgt

    def test_add_edge_returns_complete_record(self, migrated_conn):
        """Verify returned dict has all expected keys.

        Expected keys: source_id, target_id, reason, weight, created_at
        """
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add

        src = _create_test_neuron(migrated_conn)
        tgt = _create_test_neuron(migrated_conn, "another neuron")

        result = edge_add(migrated_conn, src, tgt, "some reason")

        expected_keys = {"source_id", "target_id", "reason", "weight", "created_at"}
        assert expected_keys == set(result.keys())

    def test_add_edge_persisted_in_db(self, migrated_conn):
        """Verify edge is actually in the database after add.

        Query edges table directly to confirm the row exists
        with correct values.
        """
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add

        src = _create_test_neuron(migrated_conn, "persist-source")
        tgt = _create_test_neuron(migrated_conn, "persist-target")

        edge_add(migrated_conn, src, tgt, "persist reason", weight=1.5)

        row = migrated_conn.execute(
            "SELECT source_id, target_id, reason, weight FROM edges WHERE source_id = ? AND target_id = ?",
            (src, tgt),
        ).fetchone()

        assert row is not None
        assert row["source_id"] == src
        assert row["target_id"] == tgt
        assert row["reason"] == "persist reason"
        assert row["weight"] == 1.5


# -----------------------------------------------------------------------------
# Validation error tests
# -----------------------------------------------------------------------------

class TestEdgeAddValidation:
    """Test input validation error paths with correct exit codes."""

    def test_source_not_found_exit_1(self, migrated_conn):
        """Source neuron ID does not exist in neurons table.

        Expects:
        - EdgeAddError raised
        - exit_code == 1
        - Message mentions the source ID
        """
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add, EdgeAddError

        tgt = _create_test_neuron(migrated_conn)
        nonexistent_src = 99999

        with pytest.raises(EdgeAddError) as exc_info:
            edge_add(migrated_conn, nonexistent_src, tgt, "some reason")

        assert exc_info.value.exit_code == 1
        assert str(nonexistent_src) in str(exc_info.value)

    def test_target_not_found_exit_1(self, migrated_conn):
        """Target neuron ID does not exist in neurons table.

        Expects:
        - EdgeAddError raised
        - exit_code == 1
        - Message mentions the target ID
        """
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add, EdgeAddError

        src = _create_test_neuron(migrated_conn)
        nonexistent_tgt = 99999

        with pytest.raises(EdgeAddError) as exc_info:
            edge_add(migrated_conn, src, nonexistent_tgt, "some reason")

        assert exc_info.value.exit_code == 1
        assert str(nonexistent_tgt) in str(exc_info.value)

    def test_empty_reason_exit_2(self, migrated_conn):
        """Empty string reason.

        Expects:
        - EdgeAddError raised
        - exit_code == 2
        - Message mentions reason cannot be empty
        """
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add, EdgeAddError

        src = _create_test_neuron(migrated_conn)
        tgt = _create_test_neuron(migrated_conn, "another")

        with pytest.raises(EdgeAddError) as exc_info:
            edge_add(migrated_conn, src, tgt, "")

        assert exc_info.value.exit_code == 2
        assert "empty" in str(exc_info.value).lower()

    def test_whitespace_only_reason_exit_2(self, migrated_conn):
        """Whitespace-only reason (spaces, tabs, newlines).

        Input: "   \\t\\n  " -> stripped to empty -> error.
        Expects: EdgeAddError with exit_code == 2
        """
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add, EdgeAddError

        src = _create_test_neuron(migrated_conn)
        tgt = _create_test_neuron(migrated_conn, "another")

        with pytest.raises(EdgeAddError) as exc_info:
            edge_add(migrated_conn, src, tgt, "   \t\n  ")

        assert exc_info.value.exit_code == 2

    def test_zero_weight_exit_2(self, migrated_conn):
        """Weight == 0.0 is invalid (must be strictly positive).

        Expects:
        - EdgeAddError raised
        - exit_code == 2
        - Message mentions weight must be > 0.0
        """
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add, EdgeAddError

        src = _create_test_neuron(migrated_conn)
        tgt = _create_test_neuron(migrated_conn, "another")

        with pytest.raises(EdgeAddError) as exc_info:
            edge_add(migrated_conn, src, tgt, "valid reason", weight=0.0)

        assert exc_info.value.exit_code == 2
        assert "0.0" in str(exc_info.value) or "weight" in str(exc_info.value).lower()

    def test_negative_weight_exit_2(self, migrated_conn):
        """Negative weight is invalid.

        Expects:
        - EdgeAddError raised
        - exit_code == 2
        """
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add, EdgeAddError

        src = _create_test_neuron(migrated_conn)
        tgt = _create_test_neuron(migrated_conn, "another")

        with pytest.raises(EdgeAddError) as exc_info:
            edge_add(migrated_conn, src, tgt, "valid reason", weight=-1.0)

        assert exc_info.value.exit_code == 2


# -----------------------------------------------------------------------------
# Duplicate edge tests
# -----------------------------------------------------------------------------

class TestEdgeAddDuplicate:
    """Test duplicate edge detection on (source_id, target_id) pair."""

    def test_duplicate_edge_exit_2(self, migrated_conn):
        """Create same (source, target) edge twice — second should fail.

        Expects:
        - First edge_add succeeds
        - Second edge_add raises EdgeAddError with exit_code == 2
        - Error message includes the existing edge's reason
        """
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add, EdgeAddError

        src = _create_test_neuron(migrated_conn)
        tgt = _create_test_neuron(migrated_conn, "another")

        edge_add(migrated_conn, src, tgt, "first reason")

        with pytest.raises(EdgeAddError) as exc_info:
            edge_add(migrated_conn, src, tgt, "second reason")

        assert exc_info.value.exit_code == 2
        assert "first reason" in str(exc_info.value)

    def test_reverse_direction_not_duplicate(self, migrated_conn):
        """A->B and B->A are different edges, not duplicates.

        Expects:
        - edge_add(A, B, reason1) succeeds
        - edge_add(B, A, reason2) also succeeds (different direction)
        - Both edges exist in DB
        """
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add

        a = _create_test_neuron(migrated_conn, "neuron a")
        b = _create_test_neuron(migrated_conn, "neuron b")

        edge_add(migrated_conn, a, b, "a to b")
        edge_add(migrated_conn, b, a, "b to a")

        count = migrated_conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        assert count == 2


# -----------------------------------------------------------------------------
# Self-loop and circular graph tests
# -----------------------------------------------------------------------------

class TestEdgeAddSelfLoopAndCircular:
    """Test that self-loops and circular graphs are allowed."""

    def test_self_loop_allowed(self, migrated_conn):
        """Edge where source_id == target_id should succeed.

        Expects:
        - edge_add(A, A, reason) succeeds
        - Returned edge has source_id == target_id
        """
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add

        a = _create_test_neuron(migrated_conn, "self-ref neuron")

        result = edge_add(migrated_conn, a, a, "self reference")

        assert result["source_id"] == a
        assert result["target_id"] == a

    def test_circular_graph_allowed(self, migrated_conn):
        """A->B and B->A can both exist (circular graph).

        Expects:
        - Both edges created successfully
        - Both edges retrievable from DB
        """
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add

        a = _create_test_neuron(migrated_conn, "circular a")
        b = _create_test_neuron(migrated_conn, "circular b")

        result_ab = edge_add(migrated_conn, a, b, "a references b")
        result_ba = edge_add(migrated_conn, b, a, "b references a")

        assert result_ab["source_id"] == a and result_ab["target_id"] == b
        assert result_ba["source_id"] == b and result_ba["target_id"] == a

        count = migrated_conn.execute(
            "SELECT COUNT(*) FROM edges WHERE (source_id=? AND target_id=?) OR (source_id=? AND target_id=?)",
            (a, b, b, a),
        ).fetchone()[0]
        assert count == 2
