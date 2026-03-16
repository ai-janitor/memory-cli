# =============================================================================
# Module: test_edge_normalize.py
# Purpose: Test edge type normalization janitor pass — v006 migration,
#   synonym clustering, canonical_reason writes, provenance preservation,
#   and CLI handler for `memory edge normalize`.
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
    """In-memory SQLite with full migrated schema through v006."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as v001
    from memory_cli.db.migrations.v004_add_access_tracking import apply as v004
    from memory_cli.db.migrations.v005_add_edge_provenance import apply as v005
    from memory_cli.db.migrations.v006_add_edge_types_and_canonical_reason import apply as v006

    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    v001(conn)
    v004(conn)
    v005(conn)
    v006(conn)
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


def _create_edge(conn, source_id, target_id, reason, weight=1.0):
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO edges (source_id, target_id, reason, weight, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (source_id, target_id, reason, weight, now_ms),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


# -----------------------------------------------------------------------------
# v006 migration tests
# -----------------------------------------------------------------------------

class TestV006Migration:
    """Test the v006 migration creates edge_types and canonical_reason."""

    def test_migration_creates_edge_types_table(self):
        """Verify v006 migration creates edge_types table."""
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
        from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as v001
        from memory_cli.db.migrations.v004_add_access_tracking import apply as v004
        from memory_cli.db.migrations.v005_add_edge_provenance import apply as v005
        from memory_cli.db.migrations.v006_add_edge_types_and_canonical_reason import apply as v006

        conn = open_connection(":memory:")
        load_and_verify_extensions(conn)
        conn.execute("BEGIN")
        v001(conn)
        v004(conn)
        v005(conn)
        conn.execute("COMMIT")

        # Before v006 — edge_types doesn't exist
        tables_before = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "edge_types" not in tables_before

        # Apply v006
        conn.execute("BEGIN")
        v006(conn)
        conn.execute("COMMIT")

        # After v006 — edge_types exists
        tables_after = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "edge_types" in tables_after

    def test_migration_adds_canonical_reason_column(self):
        """Verify v006 adds canonical_reason to edges table."""
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
        from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as v001
        from memory_cli.db.migrations.v004_add_access_tracking import apply as v004
        from memory_cli.db.migrations.v005_add_edge_provenance import apply as v005
        from memory_cli.db.migrations.v006_add_edge_types_and_canonical_reason import apply as v006

        conn = open_connection(":memory:")
        load_and_verify_extensions(conn)
        conn.execute("BEGIN")
        v001(conn)
        v004(conn)
        v005(conn)
        conn.execute("COMMIT")

        cols_before = {row[1] for row in conn.execute("PRAGMA table_info(edges)").fetchall()}
        assert "canonical_reason" not in cols_before

        conn.execute("BEGIN")
        v006(conn)
        conn.execute("COMMIT")

        cols_after = {row[1] for row in conn.execute("PRAGMA table_info(edges)").fetchall()}
        assert "canonical_reason" in cols_after

    def test_migration_seeds_edge_types(self):
        """Verify v006 seeds common edge types."""
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
        from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as v001
        from memory_cli.db.migrations.v004_add_access_tracking import apply as v004
        from memory_cli.db.migrations.v005_add_edge_provenance import apply as v005
        from memory_cli.db.migrations.v006_add_edge_types_and_canonical_reason import apply as v006

        conn = open_connection(":memory:")
        load_and_verify_extensions(conn)
        conn.execute("BEGIN")
        v001(conn)
        v004(conn)
        v005(conn)
        v006(conn)
        conn.execute("COMMIT")

        types = {
            row[0] for row in conn.execute("SELECT name FROM edge_types").fetchall()
        }
        assert "related_to" in types
        assert "interviewer" in types
        assert "derived_from" in types
        assert "contradicts" in types

    def test_edge_types_has_parent_id(self):
        """Verify edge_types table has parent_id column for hierarchy."""
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
        from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as v001
        from memory_cli.db.migrations.v004_add_access_tracking import apply as v004
        from memory_cli.db.migrations.v005_add_edge_provenance import apply as v005
        from memory_cli.db.migrations.v006_add_edge_types_and_canonical_reason import apply as v006

        conn = open_connection(":memory:")
        load_and_verify_extensions(conn)
        conn.execute("BEGIN")
        v001(conn)
        v004(conn)
        v005(conn)
        v006(conn)
        conn.execute("COMMIT")

        cols = {row[1] for row in conn.execute("PRAGMA table_info(edge_types)").fetchall()}
        assert "id" in cols
        assert "name" in cols
        assert "parent_id" in cols
        assert "description" in cols

    def test_existing_edges_get_null_canonical_reason(self):
        """Pre-existing edges get NULL canonical_reason after migration."""
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
        from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as v001
        from memory_cli.db.migrations.v004_add_access_tracking import apply as v004
        from memory_cli.db.migrations.v005_add_edge_provenance import apply as v005
        from memory_cli.db.migrations.v006_add_edge_types_and_canonical_reason import apply as v006

        conn = open_connection(":memory:")
        load_and_verify_extensions(conn)
        conn.execute("BEGIN")
        v001(conn)
        v004(conn)
        v005(conn)
        conn.execute("COMMIT")

        # Insert edge before v006 migration
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
            "VALUES (1, 2, 'interviewed_by', 1.0, ?)", (now,),
        )
        conn.commit()

        conn.execute("BEGIN")
        v006(conn)
        conn.execute("COMMIT")

        row = conn.execute(
            "SELECT reason, canonical_reason FROM edges WHERE source_id = 1"
        ).fetchone()
        assert row[0] == "interviewed_by"  # original preserved
        assert row[1] is None  # not yet normalized


# -----------------------------------------------------------------------------
# Synonym resolution tests
# -----------------------------------------------------------------------------

class TestSynonymResolution:
    """Test the _resolve_canonical function."""

    def test_known_synonym_maps_to_canonical(self):
        from memory_cli.edge.edge_normalize_janitor_pass import _resolve_canonical

        assert _resolve_canonical("has_interviewer") == "interviewer"
        assert _resolve_canonical("interviewed_by") == "interviewer"
        assert _resolve_canonical("interviewer") == "interviewer"

    def test_case_insensitive(self):
        from memory_cli.edge.edge_normalize_janitor_pass import _resolve_canonical

        assert _resolve_canonical("Has_Interviewer") == "interviewer"
        assert _resolve_canonical("RELATED_TO") == "related_to"

    def test_whitespace_stripped(self):
        from memory_cli.edge.edge_normalize_janitor_pass import _resolve_canonical

        assert _resolve_canonical("  related_to  ") == "related_to"

    def test_spaces_converted_to_underscores(self):
        from memory_cli.edge.edge_normalize_janitor_pass import _resolve_canonical

        assert _resolve_canonical("related to") == "related_to"

    def test_hyphens_converted_to_underscores(self):
        from memory_cli.edge.edge_normalize_janitor_pass import _resolve_canonical

        assert _resolve_canonical("related-to") == "related_to"

    def test_unknown_reason_identity(self):
        from memory_cli.edge.edge_normalize_janitor_pass import _resolve_canonical

        assert _resolve_canonical("custom_type") == "custom_type"
        assert _resolve_canonical("my weird reason") == "my_weird_reason"

    def test_various_clusters(self):
        from memory_cli.edge.edge_normalize_janitor_pass import _resolve_canonical

        assert _resolve_canonical("contradicted_by") == "contradicts"
        assert _resolve_canonical("evidence_for") == "supports"
        assert _resolve_canonical("written_by") == "authored_by"
        assert _resolve_canonical("belongs_to") == "part_of"
        assert _resolve_canonical("resembles") == "similar_to"


# -----------------------------------------------------------------------------
# Janitor pass tests
# -----------------------------------------------------------------------------

class TestEdgeNormalize:
    """Test the edge_normalize janitor pass end-to-end."""

    def test_normalizes_synonym_reasons(self, migrated_conn):
        """Edges with synonym reasons get canonical_reason set."""
        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        _create_edge(migrated_conn, src, tgt, "has_interviewer")

        from memory_cli.edge.edge_normalize_janitor_pass import edge_normalize

        result = edge_normalize(migrated_conn)
        assert result["normalized"] == 1
        assert result["dry_run"] is False
        assert result["mappings"][0]["canonical_reason"] == "interviewer"

        # Verify in DB
        row = migrated_conn.execute(
            "SELECT reason, canonical_reason FROM edges WHERE source_id = ? AND target_id = ?",
            (src, tgt),
        ).fetchone()
        assert row["reason"] == "has_interviewer"  # original preserved
        assert row["canonical_reason"] == "interviewer"

    def test_preserves_original_reason(self, migrated_conn):
        """Original reason column is never modified by normalization."""
        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        _create_edge(migrated_conn, src, tgt, "interviewed_by")

        from memory_cli.edge.edge_normalize_janitor_pass import edge_normalize

        edge_normalize(migrated_conn)

        row = migrated_conn.execute(
            "SELECT reason FROM edges WHERE source_id = ? AND target_id = ?",
            (src, tgt),
        ).fetchone()
        assert row["reason"] == "interviewed_by"

    def test_dry_run_does_not_write(self, migrated_conn):
        """Dry run computes mappings but does not update DB."""
        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        _create_edge(migrated_conn, src, tgt, "has_interviewer")

        from memory_cli.edge.edge_normalize_janitor_pass import edge_normalize

        result = edge_normalize(migrated_conn, dry_run=True)
        assert result["normalized"] == 1
        assert result["dry_run"] is True

        # DB should not be updated
        row = migrated_conn.execute(
            "SELECT canonical_reason FROM edges WHERE source_id = ? AND target_id = ?",
            (src, tgt),
        ).fetchone()
        assert row["canonical_reason"] is None

    def test_unknown_reason_identity_maps(self, migrated_conn):
        """Unknown reasons are identity-mapped (original becomes canonical)."""
        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        _create_edge(migrated_conn, src, tgt, "my_custom_type")

        from memory_cli.edge.edge_normalize_janitor_pass import edge_normalize

        result = edge_normalize(migrated_conn)
        assert result["mappings"][0]["canonical_reason"] == "my_custom_type"

    def test_registers_new_edge_types(self, migrated_conn):
        """Unknown canonical types are registered in edge_types table."""
        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        _create_edge(migrated_conn, src, tgt, "brand_new_type")

        from memory_cli.edge.edge_normalize_janitor_pass import edge_normalize

        result = edge_normalize(migrated_conn)
        assert result["new_types_registered"] >= 1

        row = migrated_conn.execute(
            "SELECT name FROM edge_types WHERE name = 'brand_new_type'"
        ).fetchone()
        assert row is not None

    def test_skips_already_normalized(self, migrated_conn):
        """Edges with non-NULL canonical_reason are skipped."""
        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        edge_id = _create_edge(migrated_conn, src, tgt, "related_to")

        # Manually set canonical_reason
        migrated_conn.execute(
            "UPDATE edges SET canonical_reason = 'related_to' WHERE id = ?",
            (edge_id,),
        )

        from memory_cli.edge.edge_normalize_janitor_pass import edge_normalize

        result = edge_normalize(migrated_conn)
        assert result["total_scanned"] == 0

    def test_multiple_edges_batch(self, migrated_conn):
        """Multiple edges are normalized in a single pass."""
        n1 = _create_neuron(migrated_conn, "n1")
        n2 = _create_neuron(migrated_conn, "n2")
        n3 = _create_neuron(migrated_conn, "n3")
        _create_edge(migrated_conn, n1, n2, "has_interviewer")
        _create_edge(migrated_conn, n2, n3, "contradicted_by")
        _create_edge(migrated_conn, n1, n3, "written_by")

        from memory_cli.edge.edge_normalize_janitor_pass import edge_normalize

        result = edge_normalize(migrated_conn)
        assert result["total_scanned"] == 3
        assert result["normalized"] == 3

        # Verify each got correct canonical
        canonicals = {
            row["reason"]: row["canonical_reason"]
            for row in migrated_conn.execute(
                "SELECT reason, canonical_reason FROM edges"
            ).fetchall()
        }
        assert canonicals["has_interviewer"] == "interviewer"
        assert canonicals["contradicted_by"] == "contradicts"
        assert canonicals["written_by"] == "authored_by"

    def test_idempotent_second_pass(self, migrated_conn):
        """Running normalize twice is idempotent — second pass finds nothing."""
        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        _create_edge(migrated_conn, src, tgt, "related_to")

        from memory_cli.edge.edge_normalize_janitor_pass import edge_normalize

        first = edge_normalize(migrated_conn)
        assert first["normalized"] == 1

        second = edge_normalize(migrated_conn)
        assert second["total_scanned"] == 0
        assert second["normalized"] == 0


# -----------------------------------------------------------------------------
# Edge list canonical_reason tests
# -----------------------------------------------------------------------------

class TestEdgeListCanonicalReason:
    """Test that edge_list returns canonical_reason field."""

    def test_edge_list_includes_canonical_reason(self, migrated_conn):
        """Listed edges include canonical_reason when column exists."""
        from memory_cli.edge.edge_add_with_reason_and_weight import edge_add
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        edge_add(migrated_conn, src, tgt, "has_interviewer")

        # Before normalize — canonical_reason is NULL
        edges = edge_list(migrated_conn, src, direction="outgoing")
        assert len(edges) == 1
        assert edges[0]["canonical_reason"] is None

        # After normalize — canonical_reason is set
        from memory_cli.edge.edge_normalize_janitor_pass import edge_normalize
        edge_normalize(migrated_conn)

        edges = edge_list(migrated_conn, src, direction="outgoing")
        assert edges[0]["reason"] == "has_interviewer"
        assert edges[0]["canonical_reason"] == "interviewer"

    def test_query_by_canonical_reason(self, migrated_conn):
        """Can query edges by canonical_reason directly."""
        src = _create_neuron(migrated_conn, "source")
        tgt1 = _create_neuron(migrated_conn, "target1")
        tgt2 = _create_neuron(migrated_conn, "target2")
        _create_edge(migrated_conn, src, tgt1, "has_interviewer")
        _create_edge(migrated_conn, src, tgt2, "interviewed_by")

        from memory_cli.edge.edge_normalize_janitor_pass import edge_normalize
        edge_normalize(migrated_conn)

        # Both edges should have canonical_reason = "interviewer"
        rows = migrated_conn.execute(
            "SELECT id FROM edges WHERE canonical_reason = 'interviewer'"
        ).fetchall()
        assert len(rows) == 2

    def test_query_by_original_reason_still_works(self, migrated_conn):
        """Original reason column still works for queries."""
        src = _create_neuron(migrated_conn, "source")
        tgt = _create_neuron(migrated_conn, "target")
        _create_edge(migrated_conn, src, tgt, "has_interviewer")

        from memory_cli.edge.edge_normalize_janitor_pass import edge_normalize
        edge_normalize(migrated_conn)

        rows = migrated_conn.execute(
            "SELECT id FROM edges WHERE reason = 'has_interviewer'"
        ).fetchall()
        assert len(rows) == 1
