# =============================================================================
# Module: test_edge_provenance.py
# Purpose: Test provenance tracking for authored vs extracted edges.
#   Verifies provenance and confidence fields are stored, returned, validated,
#   and used in spreading activation weighting.
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
    """In-memory SQLite with full migrated schema including v004 provenance."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as v001
    from memory_cli.db.migrations.v004_add_access_tracking import apply as v004
    from memory_cli.db.migrations.v005_add_edge_provenance import apply as v005

    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    v001(conn)
    v004(conn)
    v005(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


def _create_neuron(conn, content="test content", project="test-project"):
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) "
        "VALUES (?, ?, ?, ?, 'active')",
        (content, now_ms, now_ms, project),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


# -----------------------------------------------------------------------------
# edge_add provenance tests
# -----------------------------------------------------------------------------

class TestEdgeAddProvenance:
    """Test provenance and confidence fields on edge_add."""

    def test_default_provenance_is_authored(self, migrated_conn):
        """Edge created without provenance defaults to 'authored', confidence=1.0."""
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add

        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        result = edge_add(migrated_conn, src, tgt, "test reason")

        assert result["provenance"] == "authored"
        assert result["confidence"] == 1.0

    def test_explicit_extracted_provenance(self, migrated_conn):
        """Edge with provenance='extracted' and custom confidence."""
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add

        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        result = edge_add(
            migrated_conn, src, tgt, "inferred",
            provenance="extracted", confidence=0.7,
        )

        assert result["provenance"] == "extracted"
        assert result["confidence"] == 0.7

    def test_provenance_persisted_in_db(self, migrated_conn):
        """Verify provenance fields are actually in the database."""
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add

        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        edge_add(
            migrated_conn, src, tgt, "inferred",
            provenance="extracted", confidence=0.5,
        )

        row = migrated_conn.execute(
            "SELECT provenance, confidence FROM edges WHERE source_id = ? AND target_id = ?",
            (src, tgt),
        ).fetchone()
        assert row["provenance"] == "extracted"
        assert row["confidence"] == 0.5

    def test_invalid_provenance_rejected(self, migrated_conn):
        """Invalid provenance value raises EdgeAddError."""
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add, EdgeAddError

        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")

        with pytest.raises(EdgeAddError) as exc_info:
            edge_add(migrated_conn, src, tgt, "reason", provenance="guessed")
        assert exc_info.value.exit_code == 2

    def test_confidence_zero_rejected(self, migrated_conn):
        """Confidence=0.0 is invalid (must be > 0.0)."""
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add, EdgeAddError

        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")

        with pytest.raises(EdgeAddError) as exc_info:
            edge_add(migrated_conn, src, tgt, "reason", confidence=0.0)
        assert exc_info.value.exit_code == 2

    def test_confidence_above_one_rejected(self, migrated_conn):
        """Confidence > 1.0 is invalid."""
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add, EdgeAddError

        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")

        with pytest.raises(EdgeAddError) as exc_info:
            edge_add(migrated_conn, src, tgt, "reason", confidence=1.5)
        assert exc_info.value.exit_code == 2

    def test_confidence_negative_rejected(self, migrated_conn):
        """Negative confidence is invalid."""
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add, EdgeAddError

        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")

        with pytest.raises(EdgeAddError) as exc_info:
            edge_add(migrated_conn, src, tgt, "reason", confidence=-0.5)
        assert exc_info.value.exit_code == 2


# -----------------------------------------------------------------------------
# Spreading activation confidence weighting tests
# -----------------------------------------------------------------------------

class TestSpreadingActivationConfidence:
    """Test that edge confidence modulates spreading activation scores."""

    def test_authored_edge_full_activation(self, migrated_conn):
        """Authored edge (confidence=1.0) passes full activation through."""
        from memory_cli.search.spreading_activation_bfs_linear_decay import (
            spread, _compute_activation,
        )

        # depth=1, decay=0.3, weight=1.0, confidence=1.0
        # base = max(0, 1 - 2*0.3) = 0.4; modulated = 0.4 * 1.0 * 1.0 = 0.4
        result = _compute_activation(1.0, 0, 0.3, 1.0, 1.0)
        assert abs(result - 0.4) < 1e-9

    def test_extracted_edge_reduced_activation(self, migrated_conn):
        """Extracted edge (confidence=0.5) halves the activation."""
        from memory_cli.search.spreading_activation_bfs_linear_decay import _compute_activation

        # base = 0.4; modulated = 0.4 * 1.0 * 0.5 = 0.2
        result = _compute_activation(1.0, 0, 0.3, 1.0, 0.5)
        assert abs(result - 0.2) < 1e-9

    def test_low_confidence_edge_nearly_zero_activation(self, migrated_conn):
        """Very low confidence edge (0.1) severely attenuates activation."""
        from memory_cli.search.spreading_activation_bfs_linear_decay import _compute_activation

        # base = 0.4; modulated = 0.4 * 1.0 * 0.1 = 0.04
        result = _compute_activation(1.0, 0, 0.3, 1.0, 0.1)
        assert abs(result - 0.04) < 1e-9

    def test_spreading_activation_authored_vs_extracted_graph(self, migrated_conn):
        """In a graph with both authored and extracted edges,
        authored paths produce higher activation than extracted paths."""
        from memory_cli.search.spreading_activation_bfs_linear_decay import spread

        conn = migrated_conn
        conn.execute("BEGIN")
        # Create 4 neurons: seed(1), authored_neighbor(2), extracted_neighbor(3)
        for i in range(1, 4):
            _create_neuron(conn, f"neuron {i}")

        now = int(time.time() * 1000)
        # Edge 1->2: authored, confidence=1.0, weight=1.0
        conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, weight, created_at, provenance, confidence) "
            "VALUES (1, 2, 'authored edge', 1.0, ?, 'authored', 1.0)",
            (now,),
        )
        # Edge 1->3: extracted, confidence=0.3, weight=1.0
        conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, weight, created_at, provenance, confidence) "
            "VALUES (1, 3, 'extracted edge', 1.0, ?, 'extracted', 0.3)",
            (now,),
        )
        conn.execute("COMMIT")

        seeds = [{"neuron_id": 1, "rrf_score": 0.016}]
        results = spread(conn, seeds, fan_out_depth=1)
        by_id = {r["neuron_id"]: r for r in results}

        # Neuron 2 (authored path): activation = 0.4 * 1.0 * 1.0 = 0.4
        # Neuron 3 (extracted path): activation = 0.4 * 1.0 * 0.3 = 0.12
        assert 2 in by_id
        assert 3 in by_id
        assert by_id[2]["activation_score"] > by_id[3]["activation_score"]
        assert abs(by_id[2]["activation_score"] - 0.4) < 1e-9
        assert abs(by_id[3]["activation_score"] - 0.12) < 1e-9


# -----------------------------------------------------------------------------
# edge_list provenance tests
# -----------------------------------------------------------------------------

class TestEdgeListProvenance:
    """Test that edge_list returns provenance and confidence fields."""

    def test_edge_list_includes_provenance(self, migrated_conn):
        """Listed edges include provenance and confidence fields."""
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        edge_add(
            migrated_conn, src, tgt, "test",
            provenance="extracted", confidence=0.6,
        )

        edges = edge_list(migrated_conn, src, direction="outgoing")
        assert len(edges) == 1
        assert edges[0]["provenance"] == "extracted"
        assert edges[0]["confidence"] == 0.6


# -----------------------------------------------------------------------------
# edge_update provenance tests
# -----------------------------------------------------------------------------

class TestEdgeUpdateProvenance:
    """Test updating provenance and confidence on existing edges."""

    def test_update_provenance(self, migrated_conn):
        """Can update provenance from authored to extracted."""
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add
        from memory_cli.edge.edge_update_by_source_target import edge_update

        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        edge_add(migrated_conn, src, tgt, "test")

        result = edge_update(migrated_conn, src, tgt, provenance="extracted")
        assert result["provenance"] == "extracted"

    def test_update_confidence(self, migrated_conn):
        """Can update confidence score on an edge."""
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add
        from memory_cli.edge.edge_update_by_source_target import edge_update

        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        edge_add(migrated_conn, src, tgt, "test")

        result = edge_update(migrated_conn, src, tgt, confidence=0.8)
        assert result["confidence"] == 0.8

    def test_update_invalid_provenance_rejected(self, migrated_conn):
        """Invalid provenance in update raises error."""
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add
        from memory_cli.edge.edge_update_by_source_target import edge_update, EdgeUpdateError

        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        edge_add(migrated_conn, src, tgt, "test")

        with pytest.raises(EdgeUpdateError) as exc_info:
            edge_update(migrated_conn, src, tgt, provenance="guessed")
        assert exc_info.value.exit_code == 2

    def test_update_invalid_confidence_rejected(self, migrated_conn):
        """Confidence outside (0.0, 1.0] in update raises error."""
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add
        from memory_cli.edge.edge_update_by_source_target import edge_update, EdgeUpdateError

        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        edge_add(migrated_conn, src, tgt, "test")

        with pytest.raises(EdgeUpdateError):
            edge_update(migrated_conn, src, tgt, confidence=0.0)

        with pytest.raises(EdgeUpdateError):
            edge_update(migrated_conn, src, tgt, confidence=1.5)


# -----------------------------------------------------------------------------
# v004 migration test
# -----------------------------------------------------------------------------

class TestV004Migration:
    """Test the v004 migration adds provenance columns correctly."""

    def test_migration_adds_columns(self):
        """Verify v004 migration adds provenance and confidence columns."""
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
        from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as v001
        from memory_cli.db.migrations.v005_add_edge_provenance import apply as v004

        conn = open_connection(":memory:")
        load_and_verify_extensions(conn)
        conn.execute("BEGIN")
        v001(conn)
        conn.execute("COMMIT")

        # Before v004 — columns don't exist
        cols_before = {row[1] for row in conn.execute("PRAGMA table_info(edges)").fetchall()}
        assert "provenance" not in cols_before
        assert "confidence" not in cols_before

        # Apply v004
        conn.execute("BEGIN")
        v004(conn)
        conn.execute("COMMIT")

        # After v004 — columns exist
        cols_after = {row[1] for row in conn.execute("PRAGMA table_info(edges)").fetchall()}
        assert "provenance" in cols_after
        assert "confidence" in cols_after

    def test_existing_edges_get_defaults(self):
        """Pre-existing edges get provenance='authored', confidence=1.0 after migration."""
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
        from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as v001
        from memory_cli.db.migrations.v005_add_edge_provenance import apply as v004

        conn = open_connection(":memory:")
        load_and_verify_extensions(conn)
        conn.execute("BEGIN")
        v001(conn)
        conn.execute("COMMIT")

        # Insert edge before migration
        now = int(time.time() * 1000)
        conn.execute(
            "INSERT INTO neurons (content, created_at, updated_at, project, status) "
            "VALUES ('a', ?, ?, 'test', 'active')", (now, now),
        )
        conn.execute(
            "INSERT INTO neurons (content, created_at, updated_at, project, status) "
            "VALUES ('b', ?, ?, 'test', 'active')", (now, now),
        )
        conn.execute(
            "INSERT INTO edges (source_id, target_id, reason, weight, created_at) "
            "VALUES (1, 2, 'old edge', 1.0, ?)", (now,),
        )
        conn.commit()

        # Apply v004
        conn.execute("BEGIN")
        v004(conn)
        conn.execute("COMMIT")

        row = conn.execute(
            "SELECT provenance, confidence FROM edges WHERE source_id = 1 AND target_id = 2"
        ).fetchone()
        assert row[0] == "authored"
        assert row[1] == 1.0
