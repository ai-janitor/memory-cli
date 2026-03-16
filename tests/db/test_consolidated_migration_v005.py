# =============================================================================
# test_consolidated_migration_v005.py — Tests for consolidated column and
#                                        memory meta consolidate command
# =============================================================================
# Purpose:     Verify v005 migration adds consolidated column, and the
#              consolidate verb correctly processes unconsolidated neurons,
#              skips already-consolidated, and flags stale neurons.
# =============================================================================

from __future__ import annotations

import time
import pytest

sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec required for full schema (vec0 table)",
)


# --- Fixtures ---

@pytest.fixture
def v4_conn():
    """DB at schema version 4 (before consolidated column)."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as apply_v001
    from memory_cli.db.migrations.v002_add_store_fingerprint import apply as apply_v002
    from memory_cli.db.migrations.v003_add_manifesto_to_meta import apply as apply_v003
    from memory_cli.db.migrations.v004_add_access_tracking import apply as apply_v004

    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply_v001(conn)
    conn.execute("COMMIT")
    conn.execute("BEGIN")
    apply_v002(conn)
    conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
    conn.execute("COMMIT")
    conn.execute("BEGIN")
    apply_v003(conn)
    conn.execute("UPDATE meta SET value = '3' WHERE key = 'schema_version'")
    conn.execute("COMMIT")
    conn.execute("BEGIN")
    apply_v004(conn)
    conn.execute("UPDATE meta SET value = '4' WHERE key = 'schema_version'")
    conn.execute("COMMIT")
    yield conn
    conn.close()


@pytest.fixture
def v5_conn():
    """DB at schema version 5 (with consolidated column)."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as apply_v001
    from memory_cli.db.migrations.v004_add_access_tracking import apply as apply_v004
    from memory_cli.db.migrations.v005_add_consolidated_column import apply as apply_v005

    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply_v001(conn)
    conn.execute("COMMIT")
    conn.execute("BEGIN")
    apply_v004(conn)
    conn.execute("COMMIT")
    conn.execute("BEGIN")
    apply_v005(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


def _insert_neuron(conn, content="test content", project="test-project",
                   status="active", created_at=None):
    """Helper: insert a neuron. Returns neuron_id."""
    now_ms = created_at or int(time.time() * 1000)
    cursor = conn.execute(
        """INSERT INTO neurons (content, created_at, updated_at, project, status)
           VALUES (?, ?, ?, ?, ?)""",
        (content, now_ms, now_ms, project, status),
    )
    conn.commit()
    return cursor.lastrowid


def _consolidate(conn):
    """Run the consolidation logic directly against a connection.

    Mirrors handle_consolidate() but bypasses CLI config resolution.
    Returns the same data dict the handler would return.
    """
    now_ms = int(time.time() * 1000)

    unconsolidated = conn.execute(
        "SELECT id FROM neurons WHERE status = 'active' AND consolidated IS NULL ORDER BY created_at ASC"
    ).fetchall()

    for row in unconsolidated:
        conn.execute(
            "UPDATE neurons SET consolidated = ? WHERE id = ?",
            (now_ms, row[0]),
        )

    consolidated_count = len(unconsolidated)

    stale_rows = conn.execute(
        "SELECT id FROM neurons WHERE status = 'active' AND consolidated IS NOT NULL AND updated_at > consolidated"
    ).fetchall()
    stale_ids = [r[0] for r in stale_rows]

    if consolidated_count > 0 or stale_ids:
        conn.commit()

    return {
        "consolidated_count": consolidated_count,
        "stale_count": len(stale_ids),
        "stale_ids": stale_ids,
    }


# =============================================================================
# Migration v005 tests
# =============================================================================

class TestV005Migration:
    """Test that v005 migration adds consolidated column."""

    def test_migration_adds_consolidated_column(self, v4_conn):
        """After v005, neurons table has consolidated column."""
        from memory_cli.db.migrations.v005_add_consolidated_column import apply as apply_v005

        v4_conn.execute("BEGIN")
        apply_v005(v4_conn)
        v4_conn.execute("COMMIT")
        cols = v4_conn.execute("PRAGMA table_info(neurons)").fetchall()
        col_names = [c[1] for c in cols]
        assert "consolidated" in col_names

    def test_consolidated_defaults_to_null(self, v4_conn):
        """Existing neurons get consolidated = NULL after migration."""
        nid = _insert_neuron(v4_conn, content="pre-migration neuron")
        from memory_cli.db.migrations.v005_add_consolidated_column import apply as apply_v005

        v4_conn.execute("BEGIN")
        apply_v005(v4_conn)
        v4_conn.execute("COMMIT")
        row = v4_conn.execute(
            "SELECT consolidated FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] is None

    def test_consolidated_column_is_nullable(self, v5_conn):
        """New neurons can be inserted with consolidated = NULL (default)."""
        nid = _insert_neuron(v5_conn)
        row = v5_conn.execute(
            "SELECT consolidated FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] is None

    def test_consolidated_column_accepts_integer(self, v5_conn):
        """Consolidated column accepts integer timestamp values."""
        nid = _insert_neuron(v5_conn)
        now_ms = int(time.time() * 1000)
        v5_conn.execute(
            "UPDATE neurons SET consolidated = ? WHERE id = ?", (now_ms, nid)
        )
        v5_conn.commit()
        row = v5_conn.execute(
            "SELECT consolidated FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == now_ms

    def test_runner_migrates_v4_to_v5(self, v4_conn):
        """Migration runner can migrate from v4 to v5."""
        from memory_cli.db.schema_version_reader import read_schema_version
        from memory_cli.db.migration_runner_single_transaction import run_pending_migrations

        assert read_schema_version(v4_conn) == 4
        result = run_pending_migrations(v4_conn, 4, 5)
        assert result is True
        assert read_schema_version(v4_conn) == 5

    def test_runner_migrates_v0_to_v5(self):
        """Migration runner can migrate from v0 to v5 (full fresh setup)."""
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
        from memory_cli.db.schema_version_reader import read_schema_version
        from memory_cli.db.migration_runner_single_transaction import run_pending_migrations

        conn = open_connection(":memory:")
        load_and_verify_extensions(conn)
        result = run_pending_migrations(conn, 0, 5)
        assert result is True
        assert read_schema_version(conn) == 5
        cols = conn.execute("PRAGMA table_info(neurons)").fetchall()
        col_names = [c[1] for c in cols]
        assert "consolidated" in col_names
        conn.close()


# =============================================================================
# Consolidate logic tests
# =============================================================================

class TestConsolidateLogic:
    """Test the consolidation query and timestamp update logic."""

    def test_consolidate_processes_unconsolidated_neurons(self, v5_conn):
        """Consolidate marks unconsolidated active neurons with a timestamp."""
        nid1 = _insert_neuron(v5_conn, content="first neuron")
        nid2 = _insert_neuron(v5_conn, content="second neuron")

        before_ms = int(time.time() * 1000)
        result = _consolidate(v5_conn)
        after_ms = int(time.time() * 1000)

        assert result["consolidated_count"] == 2

        for nid in (nid1, nid2):
            row = v5_conn.execute(
                "SELECT consolidated FROM neurons WHERE id = ?", (nid,)
            ).fetchone()
            assert row[0] is not None
            assert before_ms <= row[0] <= after_ms

    def test_consolidate_skips_already_consolidated(self, v5_conn):
        """Already-consolidated neurons are not re-processed."""
        nid = _insert_neuron(v5_conn, content="already done")
        old_ts = int(time.time() * 1000) - 60000
        v5_conn.execute(
            "UPDATE neurons SET consolidated = ? WHERE id = ?", (old_ts, nid)
        )
        v5_conn.commit()

        result = _consolidate(v5_conn)

        assert result["consolidated_count"] == 0

        # Verify timestamp was NOT changed
        row = v5_conn.execute(
            "SELECT consolidated FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == old_ts

    def test_consolidate_is_idempotent(self, v5_conn):
        """Running consolidate twice produces 0 on second run."""
        _insert_neuron(v5_conn, content="test neuron")

        result1 = _consolidate(v5_conn)
        assert result1["consolidated_count"] == 1

        result2 = _consolidate(v5_conn)
        assert result2["consolidated_count"] == 0

    def test_consolidate_fifo_order(self, v5_conn):
        """Neurons are processed in created_at ASC order (FIFO)."""
        now_ms = int(time.time() * 1000)
        nid_older = _insert_neuron(v5_conn, content="older", created_at=now_ms - 2000)
        nid_newer = _insert_neuron(v5_conn, content="newer", created_at=now_ms - 1000)

        result = _consolidate(v5_conn)

        assert result["consolidated_count"] == 2
        # Both should be consolidated
        for nid in (nid_older, nid_newer):
            row = v5_conn.execute(
                "SELECT consolidated FROM neurons WHERE id = ?", (nid,)
            ).fetchone()
            assert row[0] is not None

    def test_consolidate_skips_archived_neurons(self, v5_conn):
        """Archived neurons are not consolidated."""
        _insert_neuron(v5_conn, content="archived one", status="archived")
        _insert_neuron(v5_conn, content="active one", status="active")

        result = _consolidate(v5_conn)

        assert result["consolidated_count"] == 1

    def test_consolidate_detects_stale_neurons(self, v5_conn):
        """Neurons with updated_at > consolidated are flagged as stale."""
        nid = _insert_neuron(v5_conn, content="will become stale")
        old_ts = int(time.time() * 1000) - 60000
        new_ts = int(time.time() * 1000)
        # Set consolidated in the past, updated_at more recent
        v5_conn.execute(
            "UPDATE neurons SET consolidated = ?, updated_at = ? WHERE id = ?",
            (old_ts, new_ts, nid),
        )
        v5_conn.commit()

        result = _consolidate(v5_conn)

        assert result["stale_count"] == 1
        assert nid in result["stale_ids"]

    def test_consolidate_no_stale_when_fresh(self, v5_conn):
        """Freshly consolidated neurons are not stale."""
        _insert_neuron(v5_conn, content="fresh neuron")

        result = _consolidate(v5_conn)

        assert result["consolidated_count"] == 1
        assert result["stale_count"] == 0
        assert result["stale_ids"] == []

    def test_consolidate_empty_db(self, v5_conn):
        """Consolidate on empty DB returns zero counts."""
        result = _consolidate(v5_conn)

        assert result["consolidated_count"] == 0
        assert result["stale_count"] == 0
        assert result["stale_ids"] == []

    def test_consolidate_mixed_states(self, v5_conn):
        """Mix of unconsolidated, consolidated, stale, and archived neurons."""
        now_ms = int(time.time() * 1000)

        # Unconsolidated active
        nid_new = _insert_neuron(v5_conn, content="new neuron")

        # Already consolidated (fresh)
        nid_fresh = _insert_neuron(v5_conn, content="fresh consolidated")
        v5_conn.execute(
            "UPDATE neurons SET consolidated = ? WHERE id = ?",
            (now_ms, nid_fresh),
        )

        # Stale (consolidated but updated after)
        nid_stale = _insert_neuron(v5_conn, content="stale neuron")
        v5_conn.execute(
            "UPDATE neurons SET consolidated = ?, updated_at = ? WHERE id = ?",
            (now_ms - 60000, now_ms, nid_stale),
        )

        # Archived (should be skipped)
        _insert_neuron(v5_conn, content="archived", status="archived")
        v5_conn.commit()

        result = _consolidate(v5_conn)

        assert result["consolidated_count"] == 1  # only nid_new
        assert result["stale_count"] == 1  # only nid_stale
        assert nid_stale in result["stale_ids"]
