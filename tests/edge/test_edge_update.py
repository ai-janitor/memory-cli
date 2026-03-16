# =============================================================================
# Module: test_edge_update.py
# Purpose: Test edge update operation — modify reason/weight on an existing
#   edge identified by (source_id, target_id).
# Responsibility:
#   - Test successful update of reason only
#   - Test successful update of weight only
#   - Test successful update of both reason and weight
#   - Test edge not found -> exit 1
#   - Test no fields provided -> exit 2
#   - Test empty reason -> exit 2
#   - Test zero/negative weight -> exit 2
#   - Test created_at is preserved after update
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
    return now_ms


# -----------------------------------------------------------------------------
# Happy path tests
# -----------------------------------------------------------------------------

class TestEdgeUpdateHappyPath:
    """Test successful update scenarios."""

    def test_update_reason_only(self, migrated_conn):
        """Update just the reason, weight stays the same."""
        from memory_cli.edge.edge_update_by_source_target import edge_update

        src = _create_test_neuron(migrated_conn, "source")
        tgt = _create_test_neuron(migrated_conn, "target")
        _create_test_edge(migrated_conn, src, tgt, reason="old reason", weight=2.0)

        result = edge_update(migrated_conn, src, tgt, reason="new reason")

        assert result["reason"] == "new reason"
        assert result["weight"] == 2.0

    def test_update_weight_only(self, migrated_conn):
        """Update just the weight, reason stays the same."""
        from memory_cli.edge.edge_update_by_source_target import edge_update

        src = _create_test_neuron(migrated_conn, "source")
        tgt = _create_test_neuron(migrated_conn, "target")
        _create_test_edge(migrated_conn, src, tgt, reason="kept reason", weight=1.0)

        result = edge_update(migrated_conn, src, tgt, weight=3.5)

        assert result["reason"] == "kept reason"
        assert result["weight"] == 3.5

    def test_update_both_fields(self, migrated_conn):
        """Update both reason and weight simultaneously."""
        from memory_cli.edge.edge_update_by_source_target import edge_update

        src = _create_test_neuron(migrated_conn, "source")
        tgt = _create_test_neuron(migrated_conn, "target")
        _create_test_edge(migrated_conn, src, tgt, reason="old", weight=1.0)

        result = edge_update(migrated_conn, src, tgt, reason="new", weight=5.0)

        assert result["reason"] == "new"
        assert result["weight"] == 5.0

    def test_created_at_preserved(self, migrated_conn):
        """Update should not change created_at timestamp."""
        from memory_cli.edge.edge_update_by_source_target import edge_update

        src = _create_test_neuron(migrated_conn, "source")
        tgt = _create_test_neuron(migrated_conn, "target")
        original_ts = _create_test_edge(migrated_conn, src, tgt, reason="old", weight=1.0)

        result = edge_update(migrated_conn, src, tgt, reason="new")

        assert result["created_at"] == original_ts

    def test_update_persisted_in_db(self, migrated_conn):
        """Verify the update is actually in the database."""
        from memory_cli.edge.edge_update_by_source_target import edge_update

        src = _create_test_neuron(migrated_conn, "source")
        tgt = _create_test_neuron(migrated_conn, "target")
        _create_test_edge(migrated_conn, src, tgt, reason="old", weight=1.0)

        edge_update(migrated_conn, src, tgt, reason="persisted", weight=7.0)

        row = migrated_conn.execute(
            "SELECT reason, weight FROM edges WHERE source_id=? AND target_id=?",
            (src, tgt)
        ).fetchone()
        assert row["reason"] == "persisted"
        assert row["weight"] == 7.0

    def test_reason_stripped(self, migrated_conn):
        """Reason with surrounding whitespace should be stripped."""
        from memory_cli.edge.edge_update_by_source_target import edge_update

        src = _create_test_neuron(migrated_conn, "source")
        tgt = _create_test_neuron(migrated_conn, "target")
        _create_test_edge(migrated_conn, src, tgt, reason="old")

        result = edge_update(migrated_conn, src, tgt, reason="  trimmed  ")

        assert result["reason"] == "trimmed"


# -----------------------------------------------------------------------------
# Validation error tests
# -----------------------------------------------------------------------------

class TestEdgeUpdateValidation:
    """Test validation error paths."""

    def test_no_fields_provided_exit_2(self, migrated_conn):
        """Neither reason nor weight provided -> error."""
        from memory_cli.edge.edge_update_by_source_target import edge_update, EdgeUpdateError

        src = _create_test_neuron(migrated_conn, "source")
        tgt = _create_test_neuron(migrated_conn, "target")
        _create_test_edge(migrated_conn, src, tgt)

        with pytest.raises(EdgeUpdateError) as exc_info:
            edge_update(migrated_conn, src, tgt)

        assert exc_info.value.exit_code == 2

    def test_edge_not_found_exit_1(self, migrated_conn):
        """Edge does not exist."""
        from memory_cli.edge.edge_update_by_source_target import edge_update, EdgeUpdateError

        src = _create_test_neuron(migrated_conn, "source")
        tgt = _create_test_neuron(migrated_conn, "target")
        # No edge created

        with pytest.raises(EdgeUpdateError) as exc_info:
            edge_update(migrated_conn, src, tgt, reason="new")

        assert exc_info.value.exit_code == 1

    def test_empty_reason_exit_2(self, migrated_conn):
        """Empty reason string -> error."""
        from memory_cli.edge.edge_update_by_source_target import edge_update, EdgeUpdateError

        src = _create_test_neuron(migrated_conn, "source")
        tgt = _create_test_neuron(migrated_conn, "target")
        _create_test_edge(migrated_conn, src, tgt)

        with pytest.raises(EdgeUpdateError) as exc_info:
            edge_update(migrated_conn, src, tgt, reason="")

        assert exc_info.value.exit_code == 2

    def test_whitespace_reason_exit_2(self, migrated_conn):
        """Whitespace-only reason -> error."""
        from memory_cli.edge.edge_update_by_source_target import edge_update, EdgeUpdateError

        src = _create_test_neuron(migrated_conn, "source")
        tgt = _create_test_neuron(migrated_conn, "target")
        _create_test_edge(migrated_conn, src, tgt)

        with pytest.raises(EdgeUpdateError) as exc_info:
            edge_update(migrated_conn, src, tgt, reason="   \t  ")

        assert exc_info.value.exit_code == 2

    def test_zero_weight_exit_2(self, migrated_conn):
        """Weight == 0.0 -> error."""
        from memory_cli.edge.edge_update_by_source_target import edge_update, EdgeUpdateError

        src = _create_test_neuron(migrated_conn, "source")
        tgt = _create_test_neuron(migrated_conn, "target")
        _create_test_edge(migrated_conn, src, tgt)

        with pytest.raises(EdgeUpdateError) as exc_info:
            edge_update(migrated_conn, src, tgt, weight=0.0)

        assert exc_info.value.exit_code == 2

    def test_negative_weight_exit_2(self, migrated_conn):
        """Negative weight -> error."""
        from memory_cli.edge.edge_update_by_source_target import edge_update, EdgeUpdateError

        src = _create_test_neuron(migrated_conn, "source")
        tgt = _create_test_neuron(migrated_conn, "target")
        _create_test_edge(migrated_conn, src, tgt)

        with pytest.raises(EdgeUpdateError) as exc_info:
            edge_update(migrated_conn, src, tgt, weight=-1.0)

        assert exc_info.value.exit_code == 2
