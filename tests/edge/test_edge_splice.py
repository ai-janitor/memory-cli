# =============================================================================
# Module: test_edge_splice.py
# Purpose: Test atomic edge splice operation — insert a neuron between an
#   existing edge A->B, producing A->C and C->B.
# Responsibility:
#   - Test successful splice with default (inherited) reason/weight
#   - Test successful splice with overridden reason/weight
#   - Test source edge A->B not found -> exit 1
#   - Test through neuron C not found -> exit 1
#   - Test A->C already exists -> exit 2
#   - Test C->B already exists -> exit 2
#   - Test original A->B edge is removed after splice
#   - Test both new edges are created with correct fields
#   - Test atomicity: if C->B would duplicate, A->B is NOT removed
# =============================================================================

from __future__ import annotations

import time

import pytest

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


def _create_test_edge(conn, source_id, target_id, reason="test reason", weight=1.0):
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO edges (source_id, target_id, reason, weight, created_at) VALUES (?, ?, ?, ?, ?)",
        (source_id, target_id, reason, weight, now_ms)
    )


# -----------------------------------------------------------------------------
# Happy path tests
# -----------------------------------------------------------------------------

class TestEdgeSpliceHappyPath:
    """Test successful splice scenarios."""

    def test_splice_inherits_reason_and_weight(self, migrated_conn):
        """Splice without overrides: A->C and C->B inherit from A->B.

        Given: A->B with reason='linked' and weight=2.5
        When: splice(A, B, through=C)
        Then: A->C has reason='linked', weight=2.5
              C->B has reason='linked', weight=2.5
              A->B is removed
        """
        from memory_cli.edge.edge_splice_atomic_insert_between import edge_splice

        a = _create_test_neuron(migrated_conn, "neuron a")
        b = _create_test_neuron(migrated_conn, "neuron b")
        c = _create_test_neuron(migrated_conn, "neuron c")
        _create_test_edge(migrated_conn, a, b, reason="linked", weight=2.5)

        result = edge_splice(migrated_conn, a, b, through_id=c)

        assert result["removed_edge"]["source_id"] == a
        assert result["removed_edge"]["target_id"] == b
        assert result["edge_a_c"]["source_id"] == a
        assert result["edge_a_c"]["target_id"] == c
        assert result["edge_a_c"]["reason"] == "linked"
        assert result["edge_a_c"]["weight"] == 2.5
        assert result["edge_c_b"]["source_id"] == c
        assert result["edge_c_b"]["target_id"] == b
        assert result["edge_c_b"]["reason"] == "linked"
        assert result["edge_c_b"]["weight"] == 2.5

        # A->B should be gone
        row = migrated_conn.execute(
            "SELECT 1 FROM edges WHERE source_id = ? AND target_id = ?", (a, b)
        ).fetchone()
        assert row is None

    def test_splice_with_overridden_reasons(self, migrated_conn):
        """Splice with custom reasons for A->C and C->B."""
        from memory_cli.edge.edge_splice_atomic_insert_between import edge_splice

        a = _create_test_neuron(migrated_conn, "neuron a")
        b = _create_test_neuron(migrated_conn, "neuron b")
        c = _create_test_neuron(migrated_conn, "neuron c")
        _create_test_edge(migrated_conn, a, b, reason="original")

        result = edge_splice(
            migrated_conn, a, b, through_id=c,
            reason_a_c="a to c reason", reason_c_b="c to b reason"
        )

        assert result["edge_a_c"]["reason"] == "a to c reason"
        assert result["edge_c_b"]["reason"] == "c to b reason"

    def test_splice_with_overridden_weights(self, migrated_conn):
        """Splice with custom weights for A->C and C->B."""
        from memory_cli.edge.edge_splice_atomic_insert_between import edge_splice

        a = _create_test_neuron(migrated_conn, "neuron a")
        b = _create_test_neuron(migrated_conn, "neuron b")
        c = _create_test_neuron(migrated_conn, "neuron c")
        _create_test_edge(migrated_conn, a, b, reason="original", weight=1.0)

        result = edge_splice(
            migrated_conn, a, b, through_id=c,
            weight_a_c=3.0, weight_c_b=0.5
        )

        assert result["edge_a_c"]["weight"] == 3.0
        assert result["edge_c_b"]["weight"] == 0.5

    def test_splice_persisted_in_db(self, migrated_conn):
        """Verify new edges are in DB and old edge is gone after splice."""
        from memory_cli.edge.edge_splice_atomic_insert_between import edge_splice

        a = _create_test_neuron(migrated_conn, "neuron a")
        b = _create_test_neuron(migrated_conn, "neuron b")
        c = _create_test_neuron(migrated_conn, "neuron c")
        _create_test_edge(migrated_conn, a, b, reason="original")

        edge_splice(migrated_conn, a, b, through_id=c)

        # A->B gone
        assert migrated_conn.execute(
            "SELECT 1 FROM edges WHERE source_id=? AND target_id=?", (a, b)
        ).fetchone() is None

        # A->C exists
        ac = migrated_conn.execute(
            "SELECT reason FROM edges WHERE source_id=? AND target_id=?", (a, c)
        ).fetchone()
        assert ac is not None
        assert ac["reason"] == "original"

        # C->B exists
        cb = migrated_conn.execute(
            "SELECT reason FROM edges WHERE source_id=? AND target_id=?", (c, b)
        ).fetchone()
        assert cb is not None
        assert cb["reason"] == "original"


# -----------------------------------------------------------------------------
# Validation error tests
# -----------------------------------------------------------------------------

class TestEdgeSpliceValidation:
    """Test validation error paths."""

    def test_edge_not_found_exit_1(self, migrated_conn):
        """A->B edge does not exist."""
        from memory_cli.edge.edge_splice_atomic_insert_between import edge_splice, EdgeSpliceError

        a = _create_test_neuron(migrated_conn, "neuron a")
        b = _create_test_neuron(migrated_conn, "neuron b")
        c = _create_test_neuron(migrated_conn, "neuron c")
        # No edge A->B created

        with pytest.raises(EdgeSpliceError) as exc_info:
            edge_splice(migrated_conn, a, b, through_id=c)

        assert exc_info.value.exit_code == 1

    def test_through_neuron_not_found_exit_1(self, migrated_conn):
        """Through neuron C does not exist."""
        from memory_cli.edge.edge_splice_atomic_insert_between import edge_splice, EdgeSpliceError

        a = _create_test_neuron(migrated_conn, "neuron a")
        b = _create_test_neuron(migrated_conn, "neuron b")
        _create_test_edge(migrated_conn, a, b)

        with pytest.raises(EdgeSpliceError) as exc_info:
            edge_splice(migrated_conn, a, b, through_id=99999)

        assert exc_info.value.exit_code == 1

    def test_a_to_c_already_exists_exit_2(self, migrated_conn):
        """Edge A->C already exists — splice would create duplicate."""
        from memory_cli.edge.edge_splice_atomic_insert_between import edge_splice, EdgeSpliceError

        a = _create_test_neuron(migrated_conn, "neuron a")
        b = _create_test_neuron(migrated_conn, "neuron b")
        c = _create_test_neuron(migrated_conn, "neuron c")
        _create_test_edge(migrated_conn, a, b)
        _create_test_edge(migrated_conn, a, c, reason="pre-existing")

        with pytest.raises(EdgeSpliceError) as exc_info:
            edge_splice(migrated_conn, a, b, through_id=c)

        assert exc_info.value.exit_code == 2
        assert "already exists" in str(exc_info.value)

    def test_c_to_b_already_exists_exit_2(self, migrated_conn):
        """Edge C->B already exists — splice would create duplicate."""
        from memory_cli.edge.edge_splice_atomic_insert_between import edge_splice, EdgeSpliceError

        a = _create_test_neuron(migrated_conn, "neuron a")
        b = _create_test_neuron(migrated_conn, "neuron b")
        c = _create_test_neuron(migrated_conn, "neuron c")
        _create_test_edge(migrated_conn, a, b)
        _create_test_edge(migrated_conn, c, b, reason="pre-existing")

        with pytest.raises(EdgeSpliceError) as exc_info:
            edge_splice(migrated_conn, a, b, through_id=c)

        assert exc_info.value.exit_code == 2
        assert "already exists" in str(exc_info.value)

    def test_negative_weight_override_exit_2(self, migrated_conn):
        """Negative weight override should fail validation."""
        from memory_cli.edge.edge_splice_atomic_insert_between import edge_splice, EdgeSpliceError

        a = _create_test_neuron(migrated_conn, "neuron a")
        b = _create_test_neuron(migrated_conn, "neuron b")
        c = _create_test_neuron(migrated_conn, "neuron c")
        _create_test_edge(migrated_conn, a, b)

        with pytest.raises(EdgeSpliceError) as exc_info:
            edge_splice(migrated_conn, a, b, through_id=c, weight_a_c=-1.0)

        assert exc_info.value.exit_code == 2


# -----------------------------------------------------------------------------
# Atomicity tests
# -----------------------------------------------------------------------------

class TestEdgeSpliceAtomicity:
    """Test that splice is atomic — either all changes apply or none."""

    def test_original_edge_preserved_on_duplicate_c_b(self, migrated_conn):
        """If C->B already exists, the original A->B must NOT be removed.

        This tests that validation happens before any writes.
        """
        from memory_cli.edge.edge_splice_atomic_insert_between import edge_splice, EdgeSpliceError

        a = _create_test_neuron(migrated_conn, "neuron a")
        b = _create_test_neuron(migrated_conn, "neuron b")
        c = _create_test_neuron(migrated_conn, "neuron c")
        _create_test_edge(migrated_conn, a, b, reason="must survive")
        _create_test_edge(migrated_conn, c, b, reason="blocker")

        with pytest.raises(EdgeSpliceError):
            edge_splice(migrated_conn, a, b, through_id=c)

        # A->B should still exist (not removed)
        row = migrated_conn.execute(
            "SELECT reason FROM edges WHERE source_id=? AND target_id=?", (a, b)
        ).fetchone()
        assert row is not None
        assert row["reason"] == "must survive"
