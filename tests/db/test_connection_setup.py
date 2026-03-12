# =============================================================================
# test_connection_setup.py — Tests for WAL, FK, and busy_timeout pragmas
# =============================================================================
# Purpose:     Verify that open_connection() correctly configures all three
#              required pragmas and handles edge cases (WAL unavailable on
#              :memory:, FK enforcement, busy timeout value).
# Rationale:   Pragma misconfiguration is silent and catastrophic — FK off
#              means orphaned rows, no WAL means lock contention, no busy
#              timeout means immediate failures under concurrency.
# Responsibility:
#   - Test that WAL is set (or warning issued for :memory:)
#   - Test that foreign_keys = ON is enforced
#   - Test that busy_timeout = 5000 is set
#   - Test that the returned connection is usable
#   - Test error handling for pathological inputs
# Organization:
#   One test class per concern, pytest-style functions.
#   Uses tmp_path fixture for file-based DB tests.
# =============================================================================

from __future__ import annotations

import pytest
import sqlite3
import warnings
from pathlib import Path
from memory_cli.db.connection_setup_wal_fk_busy import open_connection


class TestWALPragma:
    """Tests for WAL journal mode configuration."""

    def test_wal_enabled_on_file_db(self, tmp_path: Path) -> None:
        """WAL should be active when using a file-based database.

        # --- Arrange ---
        # Create a temp DB file path using tmp_path fixture

        # --- Act ---
        # conn = open_connection(db_path)

        # --- Assert ---
        # PRAGMA journal_mode should return 'wal'
        """
        # --- Arrange ---
        db_path = tmp_path / "test.db"

        # --- Act ---
        conn = open_connection(db_path)

        # --- Assert ---
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"
        conn.close()

    def test_wal_warning_on_memory_db(self) -> None:
        """WAL may not apply to :memory: DBs — should warn, not crash.

        # --- Arrange ---
        # Use ':memory:' as db_path

        # --- Act ---
        # with warnings.catch_warnings(record=True) as w:
        #   conn = open_connection(':memory:')

        # --- Assert ---
        # Check that a warning was issued (WAL returns 'memory' not 'wal')
        # Connection should still be usable
        """
        # --- Act ---
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            conn = open_connection(":memory:")

        # --- Assert ---
        # At least one RuntimeWarning about WAL should be issued
        runtime_warnings = [w for w in caught if issubclass(w.category, RuntimeWarning)]
        assert len(runtime_warnings) >= 1
        assert any("wal" in str(w.message).lower() or "WAL" in str(w.message) for w in runtime_warnings)
        # Connection should still be usable
        assert conn is not None
        conn.execute("SELECT 1").fetchone()
        conn.close()


class TestForeignKeysPragma:
    """Tests for foreign key enforcement."""

    def test_foreign_keys_enabled(self) -> None:
        """PRAGMA foreign_keys should be ON after connection setup.

        # --- Arrange ---
        # conn = open_connection(':memory:')

        # --- Act ---
        # result = conn.execute('PRAGMA foreign_keys').fetchone()

        # --- Assert ---
        # result[0] should be 1
        """
        # --- Arrange ---
        conn = open_connection(":memory:")

        # --- Act ---
        result = conn.execute("PRAGMA foreign_keys").fetchone()

        # --- Assert ---
        assert result[0] == 1
        conn.close()

    def test_foreign_keys_actually_enforced(self) -> None:
        """FK violations should raise IntegrityError, not silently pass.

        # --- Arrange ---
        # conn = open_connection(':memory:')
        # Create parent and child tables with FK relationship

        # --- Act / Assert ---
        # Insert a child row referencing a non-existent parent
        # Should raise sqlite3.IntegrityError
        """
        # --- Arrange ---
        conn = open_connection(":memory:")
        conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL REFERENCES parent(id))"
        )

        # --- Act / Assert ---
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO child (id, parent_id) VALUES (1, 999)")
        conn.close()


class TestBusyTimeoutPragma:
    """Tests for busy_timeout configuration."""

    def test_busy_timeout_set(self) -> None:
        """PRAGMA busy_timeout should be 5000ms after connection setup.

        # --- Arrange ---
        # conn = open_connection(':memory:')

        # --- Act ---
        # result = conn.execute('PRAGMA busy_timeout').fetchone()

        # --- Assert ---
        # result[0] should be 5000
        """
        # --- Arrange ---
        conn = open_connection(":memory:")

        # --- Act ---
        result = conn.execute("PRAGMA busy_timeout").fetchone()

        # --- Assert ---
        assert result[0] == 5000
        conn.close()


class TestConnectionUsability:
    """Tests that the returned connection is functional."""

    def test_connection_returns_sqlite3_connection(self) -> None:
        """open_connection should return a sqlite3.Connection instance.

        # --- Act ---
        # conn = open_connection(':memory:')

        # --- Assert ---
        # isinstance(conn, sqlite3.Connection) should be True
        """
        # --- Act ---
        conn = open_connection(":memory:")

        # --- Assert ---
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_row_factory_set(self) -> None:
        """Connection should have Row factory for dict-like access.

        # --- Arrange ---
        # conn = open_connection(':memory:')

        # --- Act ---
        # conn.execute('CREATE TABLE t (a TEXT)')
        # conn.execute("INSERT INTO t VALUES ('hello')")
        # row = conn.execute('SELECT a FROM t').fetchone()

        # --- Assert ---
        # row['a'] should equal 'hello' (dict-like access via Row factory)
        """
        # --- Arrange ---
        conn = open_connection(":memory:")

        # --- Act ---
        conn.execute("CREATE TABLE t (a TEXT)")
        conn.execute("INSERT INTO t VALUES ('hello')")
        row = conn.execute("SELECT a FROM t").fetchone()

        # --- Assert ---
        assert row["a"] == "hello"
        conn.close()
