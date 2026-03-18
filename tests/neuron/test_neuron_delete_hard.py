# =============================================================================
# Module: test_neuron_delete_hard.py
# Purpose: Test hard-deletion of a single neuron via neuron_delete — verifies
#   neuron, edges, tags, attrs are all removed permanently.
# Organization:
#   1. Imports and fixtures
#   2. Basic delete tests
#   3. Edge removal tests
#   4. Error cases (not found, no confirm in CLI)
# =============================================================================

from __future__ import annotations

import time
import pytest

sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec required for full schema (vec0 table)"
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """In-memory SQLite with full migrated schema including v004 access tracking."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as apply_v001
    from memory_cli.db.migrations.v004_add_access_tracking import apply as apply_v004

    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply_v001(conn)
    apply_v004(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


def _insert_neuron(conn, content="test neuron", status="active"):
    """Insert a neuron. Returns neuron ID."""
    now_ms = int(time.time() * 1000)
    cursor = conn.execute(
        """INSERT INTO neurons
           (content, created_at, updated_at, project, source, status,
            last_accessed_at, access_count)
           VALUES (?, ?, ?, 'test-project', NULL, ?, NULL, 0)""",
        (content, now_ms, now_ms, status),
    )
    conn.commit()
    return cursor.lastrowid


def _insert_edge(conn, source_id, target_id, weight=1.0):
    """Insert an edge between two neurons."""
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO edges (source_id, target_id, weight, reason, created_at) VALUES (?, ?, ?, 'test', ?)",
        (source_id, target_id, weight, now_ms),
    )
    conn.commit()


def _insert_tag(conn, neuron_id, tag_name):
    """Insert a tag for a neuron."""
    # Ensure tag exists
    conn.execute(
        "INSERT OR IGNORE INTO tags (name, created_at) VALUES (?, ?)",
        (tag_name, int(time.time() * 1000)),
    )
    tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()[0]
    conn.execute(
        "INSERT INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)",
        (neuron_id, tag_id),
    )
    conn.commit()


# -----------------------------------------------------------------------------
# Basic delete tests
# -----------------------------------------------------------------------------

class TestNeuronDeleteBasic:
    """Test that neuron_delete removes the neuron permanently."""

    def test_delete_removes_neuron(self, migrated_conn):
        """Deleted neuron should no longer exist in the neurons table."""
        from memory_cli.neuron.neuron_delete_hard import neuron_delete

        nid = _insert_neuron(migrated_conn, content="to be deleted")
        result = neuron_delete(migrated_conn, nid)

        assert result["deleted"] is True
        assert result["id"] == nid
        row = migrated_conn.execute(
            "SELECT id FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert row is None

    def test_delete_returns_content_preview(self, migrated_conn):
        """Result should include a content preview."""
        from memory_cli.neuron.neuron_delete_hard import neuron_delete

        nid = _insert_neuron(migrated_conn, content="important memory about cats")
        result = neuron_delete(migrated_conn, nid)

        assert "important memory about cats" in result["content_preview"]

    def test_delete_truncates_long_content(self, migrated_conn):
        """Long content should be truncated to 80 chars + ellipsis."""
        from memory_cli.neuron.neuron_delete_hard import neuron_delete

        nid = _insert_neuron(migrated_conn, content="x" * 200)
        result = neuron_delete(migrated_conn, nid)

        assert len(result["content_preview"]) == 83
        assert result["content_preview"].endswith("...")

    def test_delete_archived_neuron(self, migrated_conn):
        """Should be able to delete both active and archived neurons."""
        from memory_cli.neuron.neuron_delete_hard import neuron_delete

        nid = _insert_neuron(migrated_conn, content="archived one", status="archived")
        result = neuron_delete(migrated_conn, nid)

        assert result["deleted"] is True
        row = migrated_conn.execute(
            "SELECT id FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert row is None


# -----------------------------------------------------------------------------
# Edge removal tests
# -----------------------------------------------------------------------------

class TestNeuronDeleteEdges:
    """Test that deletion removes associated edges."""

    def test_delete_removes_outgoing_edges(self, migrated_conn):
        """Edges where the deleted neuron is source should be removed."""
        from memory_cli.neuron.neuron_delete_hard import neuron_delete

        nid = _insert_neuron(migrated_conn, content="source neuron")
        other = _insert_neuron(migrated_conn, content="target neuron")
        _insert_edge(migrated_conn, nid, other)

        result = neuron_delete(migrated_conn, nid)

        assert result["edges_removed"] == 1
        edges = migrated_conn.execute(
            "SELECT COUNT(*) FROM edges WHERE source_id = ?", (nid,)
        ).fetchone()[0]
        assert edges == 0

    def test_delete_removes_incoming_edges(self, migrated_conn):
        """Edges where the deleted neuron is target should be removed."""
        from memory_cli.neuron.neuron_delete_hard import neuron_delete

        nid = _insert_neuron(migrated_conn, content="target neuron")
        other = _insert_neuron(migrated_conn, content="source neuron")
        _insert_edge(migrated_conn, other, nid)

        result = neuron_delete(migrated_conn, nid)

        assert result["edges_removed"] == 1
        edges = migrated_conn.execute(
            "SELECT COUNT(*) FROM edges WHERE target_id = ?", (nid,)
        ).fetchone()[0]
        assert edges == 0

    def test_delete_removes_tags_junction(self, migrated_conn):
        """neuron_tags rows should be removed for the deleted neuron."""
        from memory_cli.neuron.neuron_delete_hard import neuron_delete

        nid = _insert_neuron(migrated_conn, content="tagged neuron")
        _insert_tag(migrated_conn, nid, "test-tag")

        neuron_delete(migrated_conn, nid)

        tag_rows = migrated_conn.execute(
            "SELECT COUNT(*) FROM neuron_tags WHERE neuron_id = ?", (nid,)
        ).fetchone()[0]
        assert tag_rows == 0

    def test_delete_preserves_other_neurons(self, migrated_conn):
        """Deleting one neuron should not affect others."""
        from memory_cli.neuron.neuron_delete_hard import neuron_delete

        nid1 = _insert_neuron(migrated_conn, content="delete me")
        nid2 = _insert_neuron(migrated_conn, content="keep me")

        neuron_delete(migrated_conn, nid1)

        row = migrated_conn.execute(
            "SELECT content FROM neurons WHERE id = ?", (nid2,)
        ).fetchone()
        assert row is not None
        assert row[0] == "keep me"


# -----------------------------------------------------------------------------
# Error cases
# -----------------------------------------------------------------------------

class TestNeuronDeleteErrors:
    """Test error handling for neuron delete."""

    def test_delete_nonexistent_neuron_raises(self, migrated_conn):
        """Deleting a non-existent neuron should raise NeuronDeleteError."""
        from memory_cli.neuron.neuron_delete_hard import neuron_delete, NeuronDeleteError

        with pytest.raises(NeuronDeleteError, match="not found"):
            neuron_delete(migrated_conn, 99999)

    def test_delete_already_deleted_raises(self, migrated_conn):
        """Deleting the same neuron twice should raise on the second call."""
        from memory_cli.neuron.neuron_delete_hard import neuron_delete, NeuronDeleteError

        nid = _insert_neuron(migrated_conn, content="delete twice")
        neuron_delete(migrated_conn, nid)

        with pytest.raises(NeuronDeleteError, match="not found"):
            neuron_delete(migrated_conn, nid)
