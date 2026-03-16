# =============================================================================
# test_access_tracking_migration_v004.py — Tests for access tracking columns
# =============================================================================
# Purpose:     Verify v004 migration adds last_accessed_at and access_count
#              columns, neuron_get bumps counters, and search hydration bumps
#              counters on hit.
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
def v3_conn():
    """DB at schema version 3 (before access tracking)."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply as apply_v001
    from memory_cli.db.migrations.v002_add_store_fingerprint import apply as apply_v002
    from memory_cli.db.migrations.v003_add_manifesto_to_meta import apply as apply_v003

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
    yield conn
    conn.close()


@pytest.fixture
def v4_conn():
    """DB at schema version 4 (with access tracking columns)."""
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


def _insert_neuron(conn, content="test content", project="test-project"):
    """Helper: insert a neuron. Returns neuron_id."""
    now_ms = int(time.time() * 1000)
    cursor = conn.execute(
        """INSERT INTO neurons (content, created_at, updated_at, project, status)
           VALUES (?, ?, ?, ?, 'active')""",
        (content, now_ms, now_ms, project),
    )
    conn.commit()
    return cursor.lastrowid


# =============================================================================
# Migration v004 tests
# =============================================================================

class TestV004Migration:
    """Test that v004 migration adds access tracking columns."""

    def test_migration_adds_last_accessed_at_column(self, v3_conn):
        """After v004, neurons table has last_accessed_at column."""
        from memory_cli.db.migrations.v004_add_access_tracking import apply as apply_v004

        v3_conn.execute("BEGIN")
        apply_v004(v3_conn)
        v3_conn.execute("COMMIT")
        cols = v3_conn.execute("PRAGMA table_info(neurons)").fetchall()
        col_names = [c[1] for c in cols]
        assert "last_accessed_at" in col_names

    def test_migration_adds_access_count_column(self, v3_conn):
        """After v004, neurons table has access_count column."""
        from memory_cli.db.migrations.v004_add_access_tracking import apply as apply_v004

        v3_conn.execute("BEGIN")
        apply_v004(v3_conn)
        v3_conn.execute("COMMIT")
        cols = v3_conn.execute("PRAGMA table_info(neurons)").fetchall()
        col_names = [c[1] for c in cols]
        assert "access_count" in col_names

    def test_access_count_defaults_to_zero(self, v3_conn):
        """Existing neurons get access_count = 0 after migration."""
        nid = _insert_neuron(v3_conn, content="pre-migration neuron")
        from memory_cli.db.migrations.v004_add_access_tracking import apply as apply_v004

        v3_conn.execute("BEGIN")
        apply_v004(v3_conn)
        v3_conn.execute("COMMIT")
        row = v3_conn.execute(
            "SELECT access_count FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == 0

    def test_last_accessed_at_defaults_to_null(self, v3_conn):
        """Existing neurons get last_accessed_at = NULL after migration."""
        nid = _insert_neuron(v3_conn, content="pre-migration neuron")
        from memory_cli.db.migrations.v004_add_access_tracking import apply as apply_v004

        v3_conn.execute("BEGIN")
        apply_v004(v3_conn)
        v3_conn.execute("COMMIT")
        row = v3_conn.execute(
            "SELECT last_accessed_at FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] is None

    def test_runner_migrates_v3_to_v4(self, v3_conn):
        """Migration runner can migrate from v3 to v4."""
        from memory_cli.db.schema_version_reader import read_schema_version
        from memory_cli.db.migration_runner_single_transaction import run_pending_migrations

        assert read_schema_version(v3_conn) == 3
        result = run_pending_migrations(v3_conn, 3, 4)
        assert result is True
        assert read_schema_version(v3_conn) == 4

    def test_runner_migrates_v0_to_v4(self):
        """Migration runner can migrate from v0 to v4 (full fresh setup)."""
        from memory_cli.db.connection_setup_wal_fk_busy import open_connection
        from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
        from memory_cli.db.schema_version_reader import read_schema_version
        from memory_cli.db.migration_runner_single_transaction import run_pending_migrations

        conn = open_connection(":memory:")
        load_and_verify_extensions(conn)
        result = run_pending_migrations(conn, 0, 4)
        assert result is True
        assert read_schema_version(conn) == 4
        cols = conn.execute("PRAGMA table_info(neurons)").fetchall()
        col_names = [c[1] for c in cols]
        assert "last_accessed_at" in col_names
        assert "access_count" in col_names
        conn.close()


# =============================================================================
# neuron_get access tracking tests
# =============================================================================

class TestNeuronGetAccessTracking:
    """Test that neuron_get bumps access_count and last_accessed_at."""

    def test_get_increments_access_count(self, v4_conn):
        """Each neuron_get call increments access_count by 1."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        nid = _insert_neuron(v4_conn)
        neuron_get(v4_conn, nid)
        row = v4_conn.execute(
            "SELECT access_count FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == 1

    def test_get_sets_last_accessed_at(self, v4_conn):
        """neuron_get sets last_accessed_at to current time (ms)."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        nid = _insert_neuron(v4_conn)
        before_ms = int(time.time() * 1000)
        neuron_get(v4_conn, nid)
        after_ms = int(time.time() * 1000)
        row = v4_conn.execute(
            "SELECT last_accessed_at FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert before_ms <= row[0] <= after_ms

    def test_multiple_gets_increment_count(self, v4_conn):
        """Multiple neuron_get calls accumulate access_count."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        nid = _insert_neuron(v4_conn)
        for _ in range(5):
            neuron_get(v4_conn, nid)
        row = v4_conn.execute(
            "SELECT access_count FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == 5

    def test_nonexistent_neuron_no_crash(self, v4_conn):
        """neuron_get on nonexistent ID returns None without crashing."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        result = neuron_get(v4_conn, 99999)
        assert result is None


# =============================================================================
# Search hydration access tracking tests
# =============================================================================

class TestSearchHydrationAccessTracking:
    """Test that search hydration bumps access tracking on hits."""

    def test_hydration_increments_access_count(self, v4_conn):
        """hydrate_results bumps access_count for each matched neuron."""
        from memory_cli.search.search_result_hydration_and_envelope import hydrate_results

        nid = _insert_neuron(v4_conn, content="searchable content")
        candidates = [{"neuron_id": nid, "final_score": 0.9}]
        hydrate_results(v4_conn, candidates)
        row = v4_conn.execute(
            "SELECT access_count FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == 1

    def test_hydration_sets_last_accessed_at(self, v4_conn):
        """hydrate_results sets last_accessed_at for matched neurons."""
        from memory_cli.search.search_result_hydration_and_envelope import hydrate_results

        nid = _insert_neuron(v4_conn, content="searchable content")
        before_ms = int(time.time() * 1000)
        candidates = [{"neuron_id": nid, "final_score": 0.9}]
        hydrate_results(v4_conn, candidates)
        after_ms = int(time.time() * 1000)
        row = v4_conn.execute(
            "SELECT last_accessed_at FROM neurons WHERE id = ?", (nid,)
        ).fetchone()
        assert before_ms <= row[0] <= after_ms

    def test_hydration_bumps_multiple_neurons(self, v4_conn):
        """hydrate_results bumps all matched neurons in a single batch."""
        from memory_cli.search.search_result_hydration_and_envelope import hydrate_results

        nid1 = _insert_neuron(v4_conn, content="first")
        nid2 = _insert_neuron(v4_conn, content="second")
        candidates = [
            {"neuron_id": nid1, "final_score": 0.9},
            {"neuron_id": nid2, "final_score": 0.8},
        ]
        hydrate_results(v4_conn, candidates)
        for nid in (nid1, nid2):
            row = v4_conn.execute(
                "SELECT access_count FROM neurons WHERE id = ?", (nid,)
            ).fetchone()
            assert row[0] == 1

    def test_empty_candidates_no_error(self, v4_conn):
        """hydrate_results with empty candidates returns empty list."""
        from memory_cli.search.search_result_hydration_and_envelope import hydrate_results

        result = hydrate_results(v4_conn, [])
        assert result == []
