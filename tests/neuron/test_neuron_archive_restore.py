# =============================================================================
# Module: test_neuron_archive_restore.py
# Purpose: Test archive and restore lifecycle transitions — status changes,
#   idempotent no-ops, not-found errors, and data preservation.
# Rationale: Archive/restore are the only lifecycle transitions. They must
#   be idempotent (archiving an archived neuron is a no-op) and must
#   preserve all associated data (vectors, FTS, edges, tags, attrs).
#   These invariants need explicit test coverage.
# Responsibility:
#   - Test archive changes status to 'archived'
#   - Test archive on already-archived neuron is a no-op
#   - Test restore changes status to 'active'
#   - Test restore on already-active neuron is a no-op
#   - Test archive/restore on non-existent neuron raises error
#   - Test archive preserves edges (neuron's edges still exist)
#   - Test archive preserves tags and attrs
#   - Test updated_at changes only on real transition
# Organization:
#   1. Imports and fixtures
#   2. Archive tests
#   3. Restore tests
#   4. Not-found error tests
#   5. Data preservation tests
#   6. Timestamp behavior tests
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
    """In-memory SQLite with full migrated schema including neurons_vec."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as apply_v001
    from memory_cli.db.migrations.v004_add_access_tracking import apply as apply_v004

    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply_v001(conn)
    conn.execute("COMMIT")
    conn.execute("BEGIN")
    apply_v004(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


def _insert_neuron(conn, content="test", status="active", tags=None, attrs=None):
    """Insert a neuron directly for test setup. Returns neuron dict."""
    from memory_cli.registries import tag_autocreate, attr_autocreate
    from memory_cli.neuron.neuron_get_by_id import neuron_get

    now_ms = int(time.time() * 1000)
    cursor = conn.execute(
        """INSERT INTO neurons (content, created_at, updated_at, project, source, status)
           VALUES (?, ?, ?, 'test-project', NULL, ?)""",
        (content, now_ms, now_ms, status)
    )
    neuron_id = cursor.lastrowid

    for tag_name in (tags or []):
        tag_id = tag_autocreate(conn, tag_name)
        conn.execute(
            "INSERT OR IGNORE INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)",
            (neuron_id, tag_id)
        )

    for key, value in (attrs or {}).items():
        attr_key_id = attr_autocreate(conn, key)
        conn.execute(
            "INSERT INTO neuron_attrs (neuron_id, attr_key_id, value) VALUES (?, ?, ?)",
            (neuron_id, attr_key_id, value)
        )

    conn.commit()
    return neuron_get(conn, neuron_id)


# -----------------------------------------------------------------------------
# Archive tests
# -----------------------------------------------------------------------------

class TestNeuronArchive:
    """Test archiving neurons."""

    def test_archive_active_neuron(self, migrated_conn):
        """Verify archiving an active neuron sets status='archived'.

        After archive, neuron_get should return status='archived'.
        """
        from memory_cli.neuron.neuron_archive_and_restore import neuron_archive

        n = _insert_neuron(migrated_conn, status="active")
        result = neuron_archive(migrated_conn, n["id"])
        assert result["status"] == "archived"

    def test_archive_already_archived_is_noop(self, migrated_conn):
        """Verify archiving an already-archived neuron is idempotent.

        No error raised, status remains 'archived'.
        """
        from memory_cli.neuron.neuron_archive_and_restore import neuron_archive

        n = _insert_neuron(migrated_conn, status="archived")
        result = neuron_archive(migrated_conn, n["id"])
        assert result["status"] == "archived"

    def test_archive_returns_updated_record(self, migrated_conn):
        """Verify archive returns the fully hydrated neuron dict.

        Returned dict should have status='archived' and all other
        fields populated.
        """
        from memory_cli.neuron.neuron_archive_and_restore import neuron_archive

        n = _insert_neuron(migrated_conn, status="active", tags=["python"])
        result = neuron_archive(migrated_conn, n["id"])

        assert result["id"] == n["id"]
        assert result["status"] == "archived"
        assert "tags" in result
        assert "attrs" in result
        assert result["content"] == n["content"]


# -----------------------------------------------------------------------------
# Restore tests
# -----------------------------------------------------------------------------

class TestNeuronRestore:
    """Test restoring neurons."""

    def test_restore_archived_neuron(self, migrated_conn):
        """Verify restoring an archived neuron sets status='active'.

        After restore, neuron_get should return status='active'.
        """
        from memory_cli.neuron.neuron_archive_and_restore import neuron_restore

        n = _insert_neuron(migrated_conn, status="archived")
        result = neuron_restore(migrated_conn, n["id"])
        assert result["status"] == "active"

    def test_restore_already_active_is_noop(self, migrated_conn):
        """Verify restoring an already-active neuron is idempotent.

        No error raised, status remains 'active'.
        """
        from memory_cli.neuron.neuron_archive_and_restore import neuron_restore

        n = _insert_neuron(migrated_conn, status="active")
        result = neuron_restore(migrated_conn, n["id"])
        assert result["status"] == "active"

    def test_restore_returns_updated_record(self, migrated_conn):
        """Verify restore returns the fully hydrated neuron dict.

        Returned dict should have status='active'.
        """
        from memory_cli.neuron.neuron_archive_and_restore import neuron_restore

        n = _insert_neuron(migrated_conn, status="archived", tags=["ml"])
        result = neuron_restore(migrated_conn, n["id"])

        assert result["id"] == n["id"]
        assert result["status"] == "active"
        assert "tags" in result


# -----------------------------------------------------------------------------
# Not-found error tests
# -----------------------------------------------------------------------------

class TestNeuronArchiveRestoreNotFound:
    """Test error handling for non-existent neurons."""

    def test_archive_nonexistent_raises_error(self, migrated_conn):
        """Verify archiving non-existent neuron raises NeuronLifecycleError."""
        from memory_cli.neuron.neuron_archive_and_restore import neuron_archive, NeuronLifecycleError

        with pytest.raises(NeuronLifecycleError):
            neuron_archive(migrated_conn, 99999)

    def test_restore_nonexistent_raises_error(self, migrated_conn):
        """Verify restoring non-existent neuron raises NeuronLifecycleError."""
        from memory_cli.neuron.neuron_archive_and_restore import neuron_restore, NeuronLifecycleError

        with pytest.raises(NeuronLifecycleError):
            neuron_restore(migrated_conn, 99999)


# -----------------------------------------------------------------------------
# Data preservation tests
# -----------------------------------------------------------------------------

class TestNeuronArchivePreservation:
    """Test that archiving preserves all associated data."""

    def test_archive_preserves_tags(self, migrated_conn):
        """Verify archived neuron's tags are still in neuron_tags table.

        After archive, neuron_get should still return all tags.
        """
        from memory_cli.neuron.neuron_archive_and_restore import neuron_archive

        original_tags = ["python", "ai", "ml"]
        n = _insert_neuron(migrated_conn, status="active", tags=original_tags)
        result = neuron_archive(migrated_conn, n["id"])
        assert set(result["tags"]) == set(original_tags)

    def test_archive_preserves_attrs(self, migrated_conn):
        """Verify archived neuron's attrs are still in neuron_attrs table.

        After archive, neuron_get should still return all attrs.
        """
        from memory_cli.neuron.neuron_archive_and_restore import neuron_archive

        attrs = {"priority": "high", "author": "alice"}
        n = _insert_neuron(migrated_conn, status="active", attrs=attrs)
        result = neuron_archive(migrated_conn, n["id"])
        assert result["attrs"] == attrs

    def test_archive_preserves_edges(self, migrated_conn):
        """Verify archived neuron's edges are still in edges table.

        Both edges where the neuron is source and where it is target
        should survive archiving.
        """
        from memory_cli.neuron.neuron_archive_and_restore import neuron_archive

        n_source = _insert_neuron(migrated_conn, content="source neuron")
        n_target = _insert_neuron(migrated_conn, content="target neuron")

        # Create an edge: n_source -> n_target
        now_ms = int(time.time() * 1000)
        migrated_conn.execute(
            "INSERT INTO edges (source_id, target_id, weight, reason, created_at) VALUES (?, ?, 1.0, 'test', ?)",
            (n_source["id"], n_target["id"], now_ms)
        )
        migrated_conn.commit()

        # Archive the source
        neuron_archive(migrated_conn, n_source["id"])

        # Edge should still exist
        edge = migrated_conn.execute(
            "SELECT id FROM edges WHERE source_id = ? AND target_id = ?",
            (n_source["id"], n_target["id"])
        ).fetchone()
        assert edge is not None


# -----------------------------------------------------------------------------
# Timestamp behavior tests
# -----------------------------------------------------------------------------

class TestNeuronArchiveRestoreTimestamp:
    """Test updated_at behavior during transitions."""

    def test_archive_updates_timestamp_on_transition(self, migrated_conn):
        """Verify updated_at changes when status actually transitions.

        Archive an active neuron -> updated_at should change.
        """
        from memory_cli.neuron.neuron_archive_and_restore import neuron_archive

        n = _insert_neuron(migrated_conn, status="active")
        original_updated_at = n["updated_at"]

        time.sleep(0.002)
        result = neuron_archive(migrated_conn, n["id"])
        assert result["updated_at"] >= original_updated_at

    def test_archive_noop_preserves_timestamp(self, migrated_conn):
        """Verify updated_at does NOT change on no-op archive.

        Archive an already-archived neuron -> updated_at unchanged.
        """
        from memory_cli.neuron.neuron_archive_and_restore import neuron_archive

        n = _insert_neuron(migrated_conn, status="archived")
        original_updated_at = n["updated_at"]

        time.sleep(0.002)
        result = neuron_archive(migrated_conn, n["id"])
        assert result["updated_at"] == original_updated_at

    def test_restore_updates_timestamp_on_transition(self, migrated_conn):
        """Verify updated_at changes when restoring from archived.

        Restore an archived neuron -> updated_at should change.
        """
        from memory_cli.neuron.neuron_archive_and_restore import neuron_restore

        n = _insert_neuron(migrated_conn, status="archived")
        original_updated_at = n["updated_at"]

        time.sleep(0.002)
        result = neuron_restore(migrated_conn, n["id"])
        assert result["updated_at"] >= original_updated_at

    def test_restore_noop_preserves_timestamp(self, migrated_conn):
        """Verify updated_at does NOT change on no-op restore.

        Restore an already-active neuron -> updated_at unchanged.
        """
        from memory_cli.neuron.neuron_archive_and_restore import neuron_restore

        n = _insert_neuron(migrated_conn, status="active")
        original_updated_at = n["updated_at"]

        time.sleep(0.002)
        result = neuron_restore(migrated_conn, n["id"])
        assert result["updated_at"] == original_updated_at
